"""
Hugging Face provider — OpenAI-compatible chat completions via HF's unified
"Inference Providers" router at router.huggingface.co/v1.

Model IDs are routed with an explicit "hf/" prefix (e.g.
"hf/meta-llama/Llama-3.1-8B-Instruct") because Hugging Face repo IDs use the
same "namespace/model" shape as NVIDIA NIM's catalog (dabba/providers/
nvidia_provider.py) — without a prefix, registry.py's _guess_provider can't
tell "meta/llama-3.3-70b-instruct" (NIM) from "meta-llama/Llama-3.1-8B-
Instruct" (HF) apart. The prefix is stripped before the real model id is
sent to HF's API.
"""
from __future__ import annotations
from typing import List
from dabba.providers.base import (
    BaseProvider, ModelInfo,
    tools_to_openai_schema, openai_tool_calls_to_tags, remap_tool_role_for_provider,
)
from dabba.utils.logging import get_logger

logger = get_logger("dabba.providers.huggingface_provider")

HF_BASE_URL = "https://router.huggingface.co/v1"

# Free-tier availability on HF's Inference Providers router varies by model
# and changes over time — these are commonly-available instruct models as
# of the model's addition, not a guarantee. cost_input/cost_output are left
# at 0.0 since HF's own providers set pricing per-backend, not HF itself.
MODELS = [
    ModelInfo("hf/meta-llama/Llama-3.1-8B-Instruct",  "Llama 3.1 8B (HF)",   "huggingface", "medium", "Meta Llama 3.1 8B via HF Inference Providers", 128000, 0.0, 0.0, False, True),
    ModelInfo("hf/meta-llama/Llama-3.3-70B-Instruct", "Llama 3.3 70B (HF)",  "huggingface", "high",   "Meta Llama 3.3 70B via HF Inference Providers", 128000, 0.0, 0.0, False, True),
    ModelInfo("hf/Qwen/Qwen2.5-72B-Instruct",         "Qwen 2.5 72B (HF)",   "huggingface", "high",   "Qwen 2.5 72B via HF Inference Providers",        32768, 0.0, 0.0, False, True),
    ModelInfo("hf/deepseek-ai/DeepSeek-V3",           "DeepSeek V3 (HF)",   "huggingface", "xhigh",  "DeepSeek V3 via HF Inference Providers — closest open model to frontier quality", 64000, 0.0, 0.0, True, True),
]


class HuggingFaceProvider(BaseProvider):
    name = "huggingface"

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> str:
        from openai import OpenAI
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError(
                "Hugging Face token not set. In Dabba: press F2, pick an hf/ model, "
                "then paste your token. Get a free token at huggingface.co/settings/tokens "
                "(needs 'Make calls to Inference Providers' permission)."
            )

        # Strip the "hf/" routing prefix — HF's API expects the bare repo id.
        real_model = model[3:] if model.startswith("hf/") else model

        # Explicit timeout — larger open models can be slow to cold-start on
        # the free tier, same reasoning as anthropic_provider.py/nvidia_provider.py.
        # max_retries=0: the SDK defaults to 2 retries, silently turning one
        # 120s timeout into up to 360s of wait with no feedback — fail fast
        # instead (UI has Retry).
        client = OpenAI(base_url=HF_BASE_URL, api_key=key, timeout=120.0, max_retries=0)

        params = dict(
            model=real_model,
            messages=remap_tool_role_for_provider(messages),
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # Native function-calling — HF's router speaks the OpenAI-compatible
        # tools= schema for models that support it (Llama 3.x, Qwen, etc.),
        # so reuse the exact same adapters as openai_provider.py. Without
        # this, HF models fell back to the weak prompted <tool_call> tag
        # convention and frequently narrated instead of acting.
        tools = kwargs.get("tools")
        if tools:
            params["tools"] = tools_to_openai_schema(tools)
            params["tool_choice"] = "auto"

        try:
            resp = client.chat.completions.create(**params)
            message = resp.choices[0].message
            text = (message.content or "").strip()
            tag_text = openai_tool_calls_to_tags(message)
            return (text + "\n" + tag_text).strip() if tag_text else text
        except Exception as exc:
            msg = str(exc)
            # Not every HF-router backend supports the tools= parameter — some
            # reject it with a 400/422. Retry once without tools so the model
            # still answers, falling back to the prompted <tool_call> tag
            # convention the system prompt describes (weaker, but functional).
            if "tools" in params and ("400" in msg or "422" in msg):
                logger.warning(
                    "HF model '%s' rejected native tools= (%s); retrying without it.",
                    real_model, msg[:120],
                )
                params.pop("tools", None)
                params.pop("tool_choice", None)
                resp = client.chat.completions.create(**params)
                content = resp.choices[0].message.content
                return (content or "").strip()
            if "404" in msg:
                raise RuntimeError(
                    f"Model '{real_model}' not found or not deployed on any HF Inference "
                    "Provider (404). Check huggingface.co/models?inference_provider=all "
                    "for currently-served models, or press F2 to pick a different model."
                ) from exc
            if "401" in msg or "403" in msg:
                raise RuntimeError(
                    "Hugging Face token rejected (401/403). Check it has 'Make calls to "
                    "Inference Providers' permission at huggingface.co/settings/tokens."
                ) from exc
            raise

    def list_models(self) -> List[ModelInfo]:
        return MODELS
