from __future__ import annotations
from typing import Dict, List
from dabba.providers.base import (
    BaseProvider, ModelInfo,
    tools_to_anthropic_schema, anthropic_tool_use_to_tags, remap_tool_role_for_provider,
)


MODELS = [
    ModelInfo("claude-opus-4-8",        "Claude Opus 4.8",   "anthropic", "max",    "Most capable, best reasoning",     200000, 15.0,  75.0,  True,  True),
    ModelInfo("claude-sonnet-4-6",      "Claude Sonnet 4.6", "anthropic", "high",   "Balanced power and speed",         200000, 3.0,   15.0,  True,  True),
    ModelInfo("claude-haiku-4-5-20251001","Claude Haiku 4.5","anthropic", "medium", "Fast, lightweight",                200000, 0.8,   4.0,   False, True),
]


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, thinking=False, **kwargs) -> str:
        import anthropic as sdk
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError("Anthropic API key not set. Run: /keys set anthropic <key>")

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
        if temperature is not None:
            params["temperature"] = temperature
        # Anthropic has no presence/frequency penalty — only top_p and
        # stop_sequences (its name for OpenAI's "stop").
        if kwargs.get("top_p") is not None:
            params["top_p"] = kwargs["top_p"]
        if kwargs.get("stop"):
            params["stop_sequences"] = kwargs["stop"]
        if thinking and max_tokens >= 1024:
            params["thinking"] = {"type": "enabled", "budget_tokens": min(max_tokens // 2, 8000)}
            params.pop("temperature", None)  # thinking doesn't support temperature

        # Native function-calling — see openai_provider.py for why this
        # matters more than the prompted <tool_call> tag convention alone.
        tools = kwargs.get("tools")
        if tools:
            params["tools"] = tools_to_anthropic_schema(tools)

        resp = client.messages.create(**params)
        # Extract text (skip thinking blocks), then append any native tool_use
        # blocks as dabba's own <tool_call> tag text.
        parts = [b.text for b in resp.content if hasattr(b, "text")]
        text = "\n".join(parts).strip()
        tag_text = anthropic_tool_use_to_tags(resp.content)
        return (text + "\n" + tag_text).strip() if tag_text else text

    def list_models(self) -> List[ModelInfo]:
        return MODELS
