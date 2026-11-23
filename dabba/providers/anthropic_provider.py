from __future__ import annotations
from typing import List
from dabba.providers.base import (
    BaseProvider,
    ModelInfo,
    tools_to_anthropic_schema,
    anthropic_tool_use_to_tags,
    remap_tool_role_for_provider,
)

MODELS = [
    ModelInfo(
        "claude-fable-5-2",
        "Claude Fable 5.2",
        "anthropic",
        "max",
        "Most capable, long-horizon reasoning",
        1000000,
        8.0,
        40.0,
        True,
        True,
        max_output_tokens=128000,
        supports_vision=True,
    ),
    ModelInfo(
        "claude-opus-5-5",
        "Claude Opus 5.5",
        "anthropic",
        "max",
        "Best for complex coding and agents",
        1000000,
        4.0,
        20.0,
        True,
        True,
        max_output_tokens=128000,
        supports_vision=True,
    ),
    ModelInfo(
        "claude-sonnet-5-5",
        "Claude Sonnet 5.5",
        "anthropic",
        "high",
        "Balanced power and speed",
        1000000,
        2.0,
        10.0,
        True,
        True,
        max_output_tokens=128000,
        supports_vision=True,
    ),
    ModelInfo(
        "claude-haiku-5-5",
        "Claude Haiku 5.5",
        "anthropic",
        "medium",
        "Fast, lightweight",
        1000000,
        0.1,
        0.5,
        True,
        True,
        max_output_tokens=128000,
        supports_vision=True,
    ),
]

# Claude 5.x models think adaptively by default and return HTTP 400 for
# temperature/top_p/top_k and for a thinking budget_tokens setting. Their
# reasoning depth is controlled only through output_config.effort.
ADAPTIVE_THINKING_MODELS = {
    "claude-fable-5-2",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
}

# Models that support server-side refusal fallbacks. With fallbacks="default",
# a safety-classifier decline is re-run on a suitable model inside the same
# call instead of returning an empty reply. Haiku 5.5 has no server-side fallback.
REFUSAL_FALLBACK_MODELS = {"claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5"}
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def chat(
        self,
        messages,
        model,
        max_tokens=4096,
        temperature=0.7,
        thinking=False,
        **kwargs,
    ) -> str:
        import anthropic as sdk

        usage_out = kwargs.pop("usage_out", None)
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError(
                "Anthropic API key not set. Run: /keys set anthropic <key>"
            )

        # Explicit timeout so a hung connection fails predictably instead of
        # blocking (previously the SDK default applied, which is much longer
        # and — since llm_generate runs this synchronously — froze the whole
        # server's event loop for the entire wait). max_retries=0: the SDK
        # defaults to 2 retries, silently turning one 60s timeout into up to
        # 180s of wait with no feedback — fail fast instead (UI has Retry).
        client = sdk.Anthropic(api_key=key, timeout=60.0, max_retries=0)

        # Separate system prompt. Also remap role="tool" -> role="user" first —
        # Anthropic's API only accepts "user"/"assistant" roles and would
        # reject a literal "tool" role outright (see remap_tool_role_for_provider's
        # docstring in base.py for the full reasoning).
        system = ""
        chat_msgs = []
        for m in remap_tool_role_for_provider(messages):
            if m["role"] == "system":
                system = m["content"]
            else:
                chat_msgs.append({"role": m["role"], "content": m["content"]})

        params = dict(
            model=model,
            max_tokens=max_tokens,
            messages=chat_msgs,
        )
        if system:
            params["system"] = system
        if model in ADAPTIVE_THINKING_MODELS:
            # Sampling params and thinking budgets are rejected (400) on these
            # models, so map Dabba's effort tier straight to the API's effort.
            # Opus 5.5 and Haiku 5.5 default to "medium", so always send it.
            effort = kwargs.get("effort")
            params["output_config"] = {
                "effort": effort if effort in VALID_EFFORTS else "medium"
            }
        else:
            # Older models (e.g. a saved claude-sonnet-4-6 selection) keep the
            # previous request shape.
            if temperature is not None:
                params["temperature"] = temperature
            # Anthropic has no presence/frequency penalty — only top_p.
            if kwargs.get("top_p") is not None:
                params["top_p"] = kwargs["top_p"]
            if thinking and max_tokens >= 1024:
                params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": min(max_tokens // 2, 8000),
                }
                params.pop("temperature", None)  # thinking doesn't support temperature
        # stop_sequences is Anthropic's name for OpenAI's "stop".
        if kwargs.get("stop"):
            params["stop_sequences"] = kwargs["stop"]

        # Native function-calling — see openai_provider.py for why this
        # matters more than the prompted <tool_call> tag convention alone.
        tools = kwargs.get("tools")
        if tools:
            params["tools"] = tools_to_anthropic_schema(tools)

        if model in REFUSAL_FALLBACK_MODELS:
            resp = client.beta.messages.create(
                **params,
                betas=[REFUSAL_FALLBACK_BETA],
                fallbacks="default",
            )
        else:
            resp = client.messages.create(**params)

        # A refusal is HTTP 200 with no usable text; surface it instead of
        # returning an empty reply. With fallbacks enabled this means every
        # model in the chain declined.
        if getattr(resp, "stop_reason", None) == "refusal":
            details = getattr(resp, "stop_details", None)
            reason = getattr(details, "explanation", None) or "safety policy"
            raise RuntimeError(f"Claude declined this request ({reason}).")
        # Extract text (skip thinking blocks), then append any native tool_use
        # blocks as dabba's own <tool_call> tag text.
        parts = [b.text for b in resp.content if hasattr(b, "text")]
        text = "\n".join(parts).strip()

        # Anthropic reports input/output separately, not a combined total —
        # see base.py's BaseProvider docstring for why usage_out is an
        # explicit per-call param rather than an instance attribute.
        usage = getattr(resp, "usage", None)
        if usage is not None and usage_out is not None:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            usage_out.update(
                {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
            )

        tag_text = anthropic_tool_use_to_tags(resp.content)
        return (text + "\n" + tag_text).strip() if tag_text else text

    def list_models(self) -> List[ModelInfo]:
        return MODELS
