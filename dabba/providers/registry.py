"""
Provider registry — resolves a model ID to the right provider + routes chat calls.
"""
from __future__ import annotations
from typing import Dict, Iterator, List, Optional, TYPE_CHECKING

from dabba.providers.base import BaseProvider, ModelInfo, EFFORT_PARAMS
from dabba.providers.anthropic_provider import AnthropicProvider
from dabba.providers.openai_provider import OpenAIProvider
from dabba.providers.google_provider import GoogleProvider
from dabba.providers.ollama_provider import OllamaProvider
from dabba.providers.nvidia_provider import NvidiaProvider
from dabba.providers.huggingface_provider import HuggingFaceProvider
from dabba.providers.dabba_provider import DabbaProvider

if TYPE_CHECKING:
    from dabba.cli.config import CliConfig


# Build catalog once
_ANTHROPIC    = AnthropicProvider()
_OPENAI       = OpenAIProvider()
_GOOGLE       = GoogleProvider()
_OLLAMA       = OllamaProvider()
_NVIDIA       = NvidiaProvider()
_HUGGINGFACE  = HuggingFaceProvider()


def _make_dabba(endpoint: str) -> DabbaProvider:
    return DabbaProvider(endpoint=endpoint)


MODEL_CATALOG: List[ModelInfo] = (
    _ANTHROPIC.list_models()
    + _OPENAI.list_models()
    + _GOOGLE.list_models()
    + _NVIDIA.list_models()
    + _HUGGINGFACE.list_models()
    + _OLLAMA.list_models()
    + DabbaProvider().list_models()
)

_MODEL_MAP: Dict[str, ModelInfo] = {m.id: m for m in MODEL_CATALOG}


class ProviderRegistry:
    """Routes a model ID to its provider and executes chat."""

    def __init__(self, config: "CliConfig"):
        self.config = config
        self._dabba = _make_dabba(config.api_endpoint)

    def _get_provider(self, model: str) -> tuple[BaseProvider, str]:
        """Return (provider, api_key) for the given model id."""
        info = _MODEL_MAP.get(model)
        provider_name = info.provider if info else self._guess_provider(model)

        provider_map: Dict[str, BaseProvider] = {
            "anthropic":    _ANTHROPIC,
            "openai":       _OPENAI,
            "google":       _GOOGLE,
            "ollama":       _OLLAMA,
            "nvidia":       _NVIDIA,
            "huggingface":  _HUGGINGFACE,
            "dabba":        self._dabba,
        }
        provider = provider_map.get(provider_name, self._dabba)
        api_key  = self.config.api_keys.get(provider_name, "")
        return provider, api_key

    def _guess_provider(self, model: str) -> str:
        model_l = model.lower()
        if model_l.startswith("claude"):
            return "anthropic"
        if model_l.startswith(("gpt", "o1", "o3", "text-")):
            return "openai"
        if model_l.startswith("gemini"):
            return "google"
        # Explicit "hf/" prefix routes to Hugging Face — must be checked before
        # the bare "/" check below, since HF repo ids (org/Model-Name) and NVIDIA
        # NIM ids (meta/, mistralai/, qwen/, ...) are otherwise indistinguishable.
        if model_l.startswith("hf/"):
            return "huggingface"
        # NVIDIA NIM models use namespace/model format: meta/, mistralai/, nvidia/, deepseek-ai/, qwen/
        if "/" in model_l:
            return "nvidia"
        if ":" in model_l or model_l in ("llama", "mistral", "phi", "qwen", "deepseek", "gemma", "codellama"):
            return "ollama"
        return "dabba"

    def chat(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        effort: Optional[str] = None,
        **kwargs,
    ) -> str:
        model  = model  or self.config.default_model
        effort = effort or getattr(self.config, "effort", "medium")

        params = EFFORT_PARAMS.get(effort, EFFORT_PARAMS["medium"]).copy()
        params.update(kwargs)

        # Enable thinking for Claude on high+ effort
        info = _MODEL_MAP.get(model)
        if info and info.supports_thinking and effort in ("high", "xhigh", "max"):
            params["thinking"] = True

        provider, api_key = self._get_provider(model)
        return provider.chat(messages, model, api_key=api_key, **params)

    def stream_chat(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        effort: Optional[str] = None,
        **kwargs,
    ) -> Iterator[str]:
        model = model or self.config.default_model
        effort = effort or getattr(self.config, "effort", "medium")

        params = EFFORT_PARAMS.get(effort, EFFORT_PARAMS["medium"]).copy()
        params.update(kwargs)

        # Keep streaming behavior consistent with chat(): reasoning-capable
        # providers should only enter their long thinking mode at high effort.
        info = _MODEL_MAP.get(model)
        if info and info.supports_thinking and effort in ("high", "xhigh", "max"):
            params["thinking"] = True

        provider, api_key = self._get_provider(model)
        stream_chat = getattr(provider, "stream_chat", None)
        if stream_chat is None:
            yield provider.chat(messages, model, api_key=api_key, **params)
            return

        yield from stream_chat(messages, model, api_key=api_key, **params)

    def list_all_models(self) -> List[ModelInfo]:
        """Return all models in display order."""
        return (
            self._dabba.list_models()
            + _ANTHROPIC.list_models()
            + _OPENAI.list_models()
            + _GOOGLE.list_models()
            + _NVIDIA.list_models()
            + _HUGGINGFACE.list_models()
            + _OLLAMA.list_models()
        )

    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        return _MODEL_MAP.get(model_id)
