from __future__ import annotations
from typing import List
from dabba.providers.base import (
    BaseProvider,
    ModelInfo,
    tools_to_openai_schema,
    openai_tool_calls_to_tags,
    remap_tool_role_for_provider,
)


class LocalOpenAIProvider(BaseProvider):
    name = "local"

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> str:
        from openai import OpenAI
        import os
        import yaml
        from pathlib import Path

        usage_out = kwargs.pop("usage_out", None)
        # Local server typically doesn't require a real API key; use a placeholder
        key = kwargs.get("api_key", "") or "none"

        base_url = os.environ.get("LOCAL_OPENAI_BASE_URL")
        if not base_url:
            config_path = Path.home() / ".config" / "dabba" / "cli_config.yaml"
            if config_path.exists():
                try:
                    with open(config_path, "r") as f:
                        raw = yaml.safe_load(f) or {}
                        base_url = raw.get("local_openai_base_url")
                except Exception:
                    pass
        if not base_url:
            base_url = "http://localhost:8000/v1"

        client = OpenAI(base_url=base_url, api_key=key, timeout=60.0, max_retries=0)

        params = dict(model=model, messages=remap_tool_role_for_provider(messages))
        params["max_tokens"] = max_tokens
        params["temperature"] = temperature

        tools = kwargs.get("tools")
        if tools:
            params["tools"] = tools_to_openai_schema(tools)
            params["tool_choice"] = "auto"

        resp = client.chat.completions.create(**params)
        message = resp.choices[0].message
        text = (message.content or "").strip()

        usage = getattr(resp, "usage", None)
        if usage is not None and usage_out is not None:
            usage_out.update(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                }
            )

        tag_text = openai_tool_calls_to_tags(message)
        return (text + "\n" + tag_text).strip() if tag_text else text

    def list_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                "DavidAU/Llama3.3-8B-Instruct-Thinking-Heretic-Uncensored-Claude-4.5-Opus-High-Reasoning",
                "Llama 3.3 8B Thinking Heretic",
                "local",
                "max",
                "Local Llama 3.3 8B Thinking Heretic served at port 8000",
                128000,
                0.0,
                0.0,
                True,
                True,
            )
        ]
