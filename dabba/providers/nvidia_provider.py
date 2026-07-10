"""
NVIDIA NIM provider — OpenAI-compatible API at integrate.api.nvidia.com/v1
Model IDs verified against the live catalog (July 2026).
"""
from __future__ import annotations
from typing import Iterator, List
from dabba.providers.base import (
    BaseProvider, ModelInfo,
    tools_to_openai_schema, openai_tool_calls_to_tags, remap_tool_role_for_provider,
)


NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TIMEOUT_SECONDS = 60.0
SLOW_REASONING_TIMEOUT_SECONDS = 300.0

MODELS = [
    # Meta Llama
    ModelInfo("meta/llama-3.3-70b-instruct",              "Llama 3.3 70B",        "nvidia", "high",   "Meta Llama 3.3 70B Instruct",          128000, 0.23, 0.23,  False, True),
    ModelInfo("meta/llama-3.1-8b-instruct",               "Llama 3.1 8B",         "nvidia", "medium", "Meta Llama 3.1 8B Instruct",           128000, 0.05, 0.05,  False, True),
    ModelInfo("meta/llama-3.2-3b-instruct",               "Llama 3.2 3B",         "nvidia", "low",    "Meta Llama 3.2 3B fast",               128000, 0.04, 0.04,  False, True),
    # NVIDIA Nemotron
    ModelInfo("nvidia/llama-3.1-nemotron-70b-instruct",   "Nemotron 70B",         "nvidia", "xhigh",  "NVIDIA Nemotron reasoning model",      128000, 0.35, 0.35,  False, True),
    ModelInfo("nvidia/llama-3.3-nemotron-super-49b-v1",   "Nemotron Super 49B",   "nvidia", "high",   "NVIDIA Nemotron Super",                128000, 0.42, 0.42,  False, True),
    # DeepSeek — only the full R1 is confirmed live on NVIDIA NIM
    ModelInfo("deepseek-ai/deepseek-r1",                  "DeepSeek R1",          "nvidia", "max",    "DeepSeek R1 full reasoning model",     128000, 0.55, 2.19,  True,  True),
    ModelInfo("deepseek-ai/deepseek-r1-distill-qwen-7b",  "DeepSeek R1 Qwen 7B",  "nvidia", "high",   "DeepSeek R1 distilled (Qwen base)",    128000, 0.08, 0.08,  True,  True),
    # Mistral
    ModelInfo("mistralai/mistral-7b-instruct-v0.3",       "Mistral 7B",           "nvidia", "medium", "Mistral 7B Instruct",                  32768,  0.04, 0.04,  False, True),
    ModelInfo("mistralai/mixtral-8x7b-instruct-v0.1",     "Mixtral 8x7B",         "nvidia", "high",   "Mixtral MoE 8x7B",                     32768,  0.24, 0.24,  False, True),
    ModelInfo("mistralai/mistral-large-2-instruct",       "Mistral Large 2",      "nvidia", "xhigh",  "Mistral Large 2",                      128000, 2.00, 6.00,  False, True),
    # Microsoft Phi
    ModelInfo("microsoft/phi-3.5-mini-instruct",          "Phi-3.5 Mini",         "nvidia", "medium", "Microsoft Phi-3.5 Mini 128K",          128000, 0.05, 0.05,  False, True),
    ModelInfo("microsoft/phi-3-medium-128k-instruct",     "Phi-3 Medium",         "nvidia", "high",   "Microsoft Phi-3 Medium 128K",          128000, 0.12, 0.12,  False, True),
    # Qwen
    ModelInfo("qwen/qwen2.5-72b-instruct",                "Qwen 2.5 72B",         "nvidia", "high",   "Qwen 2.5 72B Instruct",                32768,  0.35, 0.35,  False, True),
    ModelInfo("qwen/qwen2.5-coder-32b-instruct",          "Qwen 2.5 Coder 32B",   "nvidia", "high",   "Qwen 2.5 Coder specialized",           32768,  0.20, 0.20,  False, True),
    # Z.ai GLM — free endpoint on NVIDIA NIM (build.nvidia.com/z-ai/glm-5.2)
    ModelInfo("z-ai/glm-5.2",                             "GLM 5.2",              "nvidia", "max",    "Flagship LLM for agentic workflows, coding, and long-horizon reasoning", 1000000, 0.0, 0.0,  True,  True),
]

# Models confirmed EOL on NVIDIA NIM — kept here as reference, NOT in active list:
#   google/gemma-3-27b-it       — EOL 2026-05-12
#   google/gemma-3-12b-it       — EOL 2026-05-12
#   deepseek-ai/deepseek-r1-distill-llama-8b — 404 (ID changed / removed)


class NvidiaProvider(BaseProvider):
    name = "nvidia"

    def _timeout_for_model(self, model: str) -> float:
        model_l = model.lower()
        if model_l == "z-ai/glm-5.2" or "deepseek-r1" in model_l:
            return SLOW_REASONING_TIMEOUT_SECONDS
        return DEFAULT_TIMEOUT_SECONDS

    def _is_reasoning_model(self, model: str) -> bool:
        model_l = model.lower()
        return (
            "r1" in model_l
            or "nemotron" in model_l
            or model_l == "z-ai/glm-5.2"
        )

    def _build_params(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> dict:
        params: dict = dict(model=model, messages=remap_tool_role_for_provider(messages), max_tokens=max_tokens)

        # NVIDIA's GLM runtime enables its long reasoning phase by default.
        # With the UI's deliberately small output limit (256 tokens), that can
        # consume the entire budget before a final answer is emitted and makes
        # an ordinary chat look stuck. Keep GLM fast at low/medium effort and
        # only enable the long thinking path when the registry explicitly asks
        # for it (high/xhigh/max effort).
        if model.lower() == "z-ai/glm-5.2":
            params["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": bool(kwargs.get("thinking", False)),
                }
            }

        # Reasoning models work better without explicit temperature.
        if not self._is_reasoning_model(model):
            params["temperature"] = temperature

        tools = kwargs.get("tools")
        if tools:
            params["tools"] = tools_to_openai_schema(tools)
            params["tool_choice"] = "auto"

        return params

    def _client(self, key: str, model: str):
        from openai import OpenAI
        return OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=key,
            timeout=self._timeout_for_model(model),
            max_retries=0,
        )

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> str:
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError(
                "NVIDIA API key not set.  In Dabba: press F2, pick any NVIDIA model, "
                "then paste your key.  Get a free key at build.nvidia.com"
            )

        # Explicit timeout — see anthropic_provider.py for why this matters.
        # max_retries=0: the SDK defaults to 2 retries, which silently turns a
        # single timeout into multiple waits with no feedback. GLM 5.2 and R1
        # can cold-start or spend longer reasoning, so they get a larger single
        # request window while ordinary NVIDIA models still fail quickly.
        client = self._client(key, model)
        params = self._build_params(messages, model, max_tokens=max_tokens, temperature=temperature, **kwargs)

        try:
            resp = client.chat.completions.create(**params)
            message = resp.choices[0].message
            text = (message.content or "").strip()
            tag_text = openai_tool_calls_to_tags(message)
            return (text + "\n" + tag_text).strip() if tag_text else text
        except Exception as exc:
            msg = str(exc)
            if "410" in msg or "end of life" in msg.lower():
                raise RuntimeError(
                    f"Model '{model}' is no longer available on NVIDIA NIM (EOL). "
                    "Press F2 to pick a different model."
                ) from exc
            if "404" in msg:
                raise RuntimeError(
                    f"Model '{model}' not found on NVIDIA NIM (404). "
                    "Press F2 to pick a different model."
                ) from exc
            raise

    def stream_chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> Iterator[str]:
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError(
                "NVIDIA API key not set.  In Dabba: press F2, pick any NVIDIA model, "
                "then paste your key.  Get a free key at build.nvidia.com"
            )

        client = self._client(key, model)
        params = self._build_params(messages, model, max_tokens=max_tokens, temperature=temperature, **kwargs)

        try:
            stream = client.chat.completions.create(**params, stream=True)
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                text = getattr(delta, "content", None) if delta else None
                if text:
                    yield text
        except Exception as exc:
            msg = str(exc)
            if "410" in msg or "end of life" in msg.lower():
                raise RuntimeError(
                    f"Model '{model}' is no longer available on NVIDIA NIM (EOL). "
                    "Press F2 to pick a different model."
                ) from exc
            if "404" in msg:
                raise RuntimeError(
                    f"Model '{model}' not found on NVIDIA NIM (404). "
                    "Press F2 to pick a different model."
                ) from exc
            raise

    def list_models(self) -> List[ModelInfo]:
        return MODELS
