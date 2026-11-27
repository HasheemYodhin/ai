"""Shared transport for hosted OpenAI-compatible Chat Completions APIs."""

from types import SimpleNamespace

from dabba.providers.base import (
    BaseProvider,
    ReasoningDelta,
    openai_tool_calls_to_tags,
    remap_tool_role_for_provider,
    tools_to_openai_schema,
)


class ChatCompletionsProvider(BaseProvider):
    base_url: str
    key_env: str
    stream_usage = False

    def _client(self, key):
        from openai import OpenAI

        if not key:
            raise RuntimeError(
                f"API key not set. Configure {self.key_env} or save a provider key."
            )
        return OpenAI(base_url=self.base_url, api_key=key, timeout=60.0, max_retries=0)

    def _params(self, messages, model, max_tokens, temperature, options):
        params = {
            "messages": remap_tool_role_for_provider(messages),
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if options.get("tools"):
            params["tools"] = tools_to_openai_schema(options["tools"])
            params["tool_choice"] = "auto"
        return params

    @staticmethod
    def _record_usage(usage, target):
        if usage is not None and target is not None:
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                target[field] = getattr(usage, field, None) or 0

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs):
        params = self._params(messages, model, max_tokens, temperature, kwargs)
        with self._client(kwargs.get("api_key")) as client:
            response = client.chat.completions.create(**params)
        self._record_usage(response.usage, kwargs.get("usage_out"))
        if not response.choices:
            return ""
        message = response.choices[0].message
        return "\n".join(
            filter(
                None,
                ((message.content or "").strip(), openai_tool_calls_to_tags(message)),
            )
        )

    def stream_chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs):
        params = self._params(messages, model, max_tokens, temperature, kwargs)
        cancel = kwargs.get("cancel_event")
        if cancel is not None and cancel.is_set():
            return
        if self.stream_usage:
            params["stream_options"] = {"include_usage": True}

        calls = {}
        with self._client(kwargs.get("api_key")) as client:
            with client.chat.completions.create(**params, stream=True) as stream:
                for chunk in stream:
                    if cancel is not None and cancel.is_set():
                        return
                    self._record_usage(chunk.usage, kwargs.get("usage_out"))
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, "reasoning_content", None)
                    if (
                        isinstance(reasoning, str)
                        and reasoning
                        and kwargs.get("include_reasoning")
                    ):
                        yield ReasoningDelta(reasoning)
                    if delta.content:
                        yield delta.content
                    for part in delta.tool_calls or ():
                        call = calls.setdefault(
                            part.index,
                            SimpleNamespace(
                                id=None, function=SimpleNamespace(name="", arguments="")
                            ),
                        )
                        if part.id:
                            call.id = part.id
                        if part.function:
                            call.function.name += part.function.name or ""
                            call.function.arguments += part.function.arguments or ""

        tags = openai_tool_calls_to_tags(
            SimpleNamespace(tool_calls=[calls[index] for index in sorted(calls)])
        )
        if tags:
            yield "\n" + tags
