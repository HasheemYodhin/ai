"""
Provider registry — resolves a model ID to the right provider + routes chat calls.
"""

from __future__ import annotations

import os
from threading import Event
from typing import Dict, Iterator, List, Optional, TYPE_CHECKING

from dabba.providers.base import BaseProvider, ModelInfo, EFFORT_PARAMS
from dabba.providers.anthropic_provider import AnthropicProvider
from dabba.providers.openai_provider import OpenAIProvider
from dabba.providers.google_provider import GoogleProvider
from dabba.providers.ollama_provider import OllamaProvider
from dabba.providers.nvidia_provider import DEFAULT_CAPACITY_FALLBACK, NvidiaProvider
from dabba.providers.huggingface_provider import HuggingFaceProvider
from dabba.providers.dabba_provider import DabbaProvider
from dabba.providers.local_provider import LocalOpenAIProvider
from dabba.platform.provider_gateway import ProviderGateway

if TYPE_CHECKING:
    from dabba.cli.config import CliConfig


# Build catalog once
_ANTHROPIC = AnthropicProvider()
_OPENAI = OpenAIProvider()
_GOOGLE = GoogleProvider()
_OLLAMA = OllamaProvider()
_NVIDIA = NvidiaProvider()
_HUGGINGFACE = HuggingFaceProvider()
_LOCAL = LocalOpenAIProvider()


def _make_dabba(endpoint: str) -> DabbaProvider:
    return DabbaProvider(endpoint=endpoint)


MODEL_CATALOG: List[ModelInfo] = (
    _ANTHROPIC.list_models()
    + _OPENAI.list_models()
    + _GOOGLE.list_models()
    + _NVIDIA.list_models()
    + _HUGGINGFACE.list_models()
    + _OLLAMA.list_models()
    + _LOCAL.list_models()
    + DabbaProvider().list_models()
)

_MODEL_MAP: Dict[str, ModelInfo] = {m.id: m for m in MODEL_CATALOG}


class ProviderRegistry:
    """Routes a model ID to its provider and executes chat."""

    def __init__(self, config: "CliConfig"):
        self.config = config
        self._dabba = _make_dabba(config.api_endpoint)
        self.gateway = ProviderGateway()

    def _get_provider(self, model: str) -> tuple[BaseProvider, str]:
        """Return (provider, api_key) for the given model id."""
        info = _MODEL_MAP.get(model)
        provider_name = info.provider if info else self._guess_provider(model)

        provider_map: Dict[str, BaseProvider] = {
            "anthropic": _ANTHROPIC,
            "openai": _OPENAI,
            "google": _GOOGLE,
            "ollama": _OLLAMA,
            "nvidia": _NVIDIA,
            "huggingface": _HUGGINGFACE,
            "local": _LOCAL,
            "dabba": self._dabba,
        }
        provider = provider_map.get(provider_name, self._dabba)
        api_key, _ = self.resolve_api_key(model)
        return provider, api_key

    def resolve_api_key(self, model: str) -> tuple[str, Optional[str]]:
        keys = self.config.api_keys
        provider = self.provider_name(model)
        for source in (model, model.lower(), provider):
            if source != "local" and keys.get(source):
                return keys[source], source
        if provider == "nvidia":
            key = os.environ.get("NVIDIA_API_KEY", "").strip()
            if key:
                return key, "NVIDIA_API_KEY"
        return "", None

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
        # If it starts with "davidau/" or "local/", route to local provider
        if model_l.startswith(("davidau/", "local/")):
            return "local"
        # NVIDIA NIM models use namespace/model format: meta/, mistralai/, nvidia/, deepseek-ai/, qwen/
        if "/" in model_l:
            return "nvidia"
        if ":" in model_l or model_l in (
            "llama",
            "mistral",
            "phi",
            "qwen",
            "deepseek",
            "gemma",
            "codellama",
        ):
            return "ollama"
        return "dabba"

    def chat(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        effort: Optional[str] = None,
        usage_out: Optional[Dict[str, int]] = None,
        **kwargs,
    ) -> str:
        """
        usage_out: pass a fresh dict to have it populated in place with real
        token counts ({"prompt_tokens", "completion_tokens", "total_tokens"})
        if the resolved provider captures them — see BaseProvider's docstring
        for why this is an explicit per-call param, not shared state.
        """
        model = model or self.config.default_model
        return self.gateway.run(
            model,
            lambda selected: self._chat_once(
                messages,
                selected,
                effort=effort,
                usage_out=usage_out,
                **kwargs,
            ),
            provider_for=self.provider_name,
        )

    def _chat_once(
        self,
        messages: List[Dict],
        model: str,
        effort: Optional[str] = None,
        usage_out: Optional[Dict[str, int]] = None,
        **kwargs,
    ) -> str:
        effort = effort or getattr(self.config, "effort", "medium")

        params = EFFORT_PARAMS.get(effort, EFFORT_PARAMS["medium"]).copy()
        params.update(kwargs)

        # Enable thinking for Claude on high+ effort
        info = _MODEL_MAP.get(model)
        if info:
            output_limit = info.max_output_tokens or max(1, info.context_window // 2)
            params["max_tokens"] = min(params["max_tokens"], output_limit)
            messages = self._fit_context(
                messages, info.context_window - params["max_tokens"]
            )
        if info and info.supports_thinking and effort in ("high", "xhigh", "max"):
            params["thinking"] = True

        provider, api_key = self._get_provider(model)
        return provider.chat(
            messages, model, api_key=api_key, usage_out=usage_out, **params
        )

    def stream_chat(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        effort: Optional[str] = None,
        usage_out: Optional[Dict[str, int]] = None,
        cancel_event: Optional[Event] = None,
        include_reasoning: bool = False,
        **kwargs,
    ) -> Iterator[str]:
        """See chat()'s docstring for usage_out."""
        model = model or self.config.default_model
        yield from self.gateway.stream(
            model,
            lambda selected: self._stream_chat_once(
                messages,
                selected,
                effort=effort,
                usage_out=usage_out,
                cancel_event=cancel_event,
                include_reasoning=include_reasoning,
                **kwargs,
            ),
            provider_for=self.provider_name,
        )

    def _stream_chat_once(
        self,
        messages: List[Dict],
        model: str,
        effort: Optional[str] = None,
        usage_out: Optional[Dict[str, int]] = None,
        cancel_event: Optional[Event] = None,
        include_reasoning: bool = False,
        **kwargs,
    ) -> Iterator[str]:
        effort = effort or getattr(self.config, "effort", "medium")

        params = EFFORT_PARAMS.get(effort, EFFORT_PARAMS["medium"]).copy()
        params.update(kwargs)

        # Keep streaming behavior consistent with chat(): reasoning-capable
        # providers should only enter their long thinking mode at high effort.
        info = _MODEL_MAP.get(model)
        if info:
            output_limit = info.max_output_tokens or max(1, info.context_window // 2)
            params["max_tokens"] = min(params["max_tokens"], output_limit)
            messages = self._fit_context(
                messages, info.context_window - params["max_tokens"]
            )
        if info and info.supports_thinking and effort in ("high", "xhigh", "max"):
            params["thinking"] = True

        provider, api_key = self._get_provider(model)
        if cancel_event is not None and cancel_event.is_set():
            return
        if provider is _NVIDIA:
            params["cancel_event"] = cancel_event
            params["include_reasoning"] = include_reasoning
        stream_chat = getattr(provider, "stream_chat", None)
        if stream_chat is None:
            yield provider.chat(
                messages, model, api_key=api_key, usage_out=usage_out, **params
            )
            return

        yield from stream_chat(
            messages, model, api_key=api_key, usage_out=usage_out, **params
        )

    @staticmethod
    def _fit_context(messages: List[Dict], budget: int) -> List[Dict]:
        def tokens(message: Dict) -> int:
            content = message.get("content", "")
            if isinstance(content, str):
                return 4 + (len(content) + 3) // 4
            return 4 + sum(
                (
                    1024
                    if part.get("type") == "image_url"
                    else (len(str(part.get("text") or "")) + 3) // 4
                )
                for part in (content or [])
                if isinstance(part, dict)
            )

        counts = [tokens(message) for message in messages]
        remaining = sum(counts)
        if remaining <= budget:
            return messages

        # Preserve leading instructions and remove complete turns. The latest
        # turn is retained even if sending it alone exceeds the budget.
        start = 0
        while start < len(messages) and messages[start].get("role") in {
            "system",
            "developer",
        }:
            start += 1
        for index in range(start + 1, len(messages)):
            remaining -= counts[index - 1]
            if messages[index].get("role") == "user" and remaining <= budget:
                return messages[:start] + messages[index:]

        latest_user = next(
            (
                index
                for index in range(len(messages) - 1, start, -1)
                if messages[index].get("role") == "user"
            ),
            start,
        )
        return messages[:start] + messages[latest_user:]

    def provider_name(self, model: str) -> str:
        info = _MODEL_MAP.get(model)
        return info.provider if info else self._guess_provider(model)

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
            + _LOCAL.list_models()
        )

    def catalog_fallbacks(self, model_id: str) -> list[str]:
        candidates = self.gateway.fallback_chain(model_id)
        if self.provider_name(model_id) == "nvidia":
            candidates.append(DEFAULT_CAPACITY_FALLBACK)
        return [
            candidate
            for candidate in dict.fromkeys(candidates)
            if candidate in _MODEL_MAP and candidate != model_id
        ]

    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        return _MODEL_MAP.get(model_id)
