from __future__ import annotations
from typing import Dict, List
from dabba.providers.base import (
    BaseProvider, ModelInfo,
    tools_to_openai_schema, openai_tool_calls_to_tags, remap_tool_role_for_provider,
)


MODELS = [
    ModelInfo("gpt-5.5",      "GPT-5.5",      "openai", "max",    "Flagship multimodal model",      256000, 5.0,  20.0,  False, True),
    ModelInfo("gpt-5.4",      "GPT-5.4",      "openai", "high",   "Balanced multimodal model",      256000, 3.0,  12.0,  False, True),
    ModelInfo("gpt-5.3",      "GPT-5.3",      "openai", "medium", "Fast and affordable",             128000, 1.0,  4.0,   False, True),
    ModelInfo("o3",           "o3",           "openai", "max",    "Best reasoning model",           200000, 10.0, 40.0,  True,  True),
]


class OpenAIProvider(BaseProvider):
    name = "openai"

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> str:
        from openai import OpenAI
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError("OpenAI API key not set. Run: /keys set openai <key>")

        # Explicit timeout — see anthropic_provider.py for why this matters:
        # llm_generate runs this synchronously, so an unbounded hang here
        # would freeze the whole server's event loop. max_retries=0: the SDK
        # defaults to 2 retries, silently turning one 60s timeout into up to
        # 180s of wait with no feedback — fail fast instead (UI has Retry).
        client = OpenAI(api_key=key, timeout=60.0, max_retries=0)

        params = dict(model=model, messages=remap_tool_role_for_provider(messages))

        # o-series models use max_completion_tokens, not max_tokens, and no temperature
        is_reasoning = model.startswith("o")
        if is_reasoning:
            params["max_completion_tokens"] = max_tokens
        else:
            params["max_tokens"] = max_tokens
            params["temperature"] = temperature
            # Nucleus sampling + repetition controls — only meaningful outside
            # the o-series reasoning models, which don't expose them.
            if kwargs.get("top_p") is not None:
                params["top_p"] = kwargs["top_p"]
            if kwargs.get("presence_penalty") is not None:
                params["presence_penalty"] = kwargs["presence_penalty"]
            if kwargs.get("frequency_penalty") is not None:
                params["frequency_penalty"] = kwargs["frequency_penalty"]
        if kwargs.get("stop"):
            params["stop"] = kwargs["stop"]

        # Native function-calling — makes tool use reliable regardless of
        # whether the model would have spontaneously emitted a <tool_call>
        # tag on its own (it often doesn't, especially GPT-4o on multi-step
        # agentic tasks — see agent_loop.py's _tool_dicts()/tools= plumbing).
        tools = kwargs.get("tools")
        if tools:
            params["tools"] = tools_to_openai_schema(tools)
            params["tool_choice"] = "auto"

        resp = client.chat.completions.create(**params)
        message = resp.choices[0].message
        text = (message.content or "").strip()
        tag_text = openai_tool_calls_to_tags(message)
        return (text + "\n" + tag_text).strip() if tag_text else text

    def list_models(self) -> List[ModelInfo]:
        return MODELS
