from __future__ import annotations
from typing import Dict, List
from dabba.providers.base import BaseProvider, ModelInfo


# Well-known Ollama models — shown even if Ollama isn't running
DEFAULT_OLLAMA_MODELS = [
    ModelInfo("llama3.3",        "Llama 3.3 70B",      "ollama", "high",   "Meta's best open model",         128000, 0, 0, False, False),
    ModelInfo("llama3.2",        "Llama 3.2 3B",       "ollama", "low",    "Small, fast local model",        128000, 0, 0, False, False),
    ModelInfo("mistral",         "Mistral 7B",         "ollama", "medium", "Fast European open model",        32000, 0, 0, False, False),
    ModelInfo("phi4",            "Phi-4",              "ollama", "medium", "Microsoft small model",           16000, 0, 0, False, False),
    ModelInfo("qwen2.5",         "Qwen 2.5 7B",        "ollama", "medium", "Alibaba multilingual model",     128000, 0, 0, False, False),
    ModelInfo("qwen2.5-coder",   "Qwen 2.5 Coder",     "ollama", "high",   "Best open coding model",         128000, 0, 0, False, False),
    ModelInfo("deepseek-r1",     "DeepSeek R1",        "ollama", "xhigh",  "Open reasoning model",           128000, 0, 0, True,  False),
    ModelInfo("gemma3",          "Gemma 3 9B",         "ollama", "medium", "Google open model",               8192,  0, 0, False, False),
    ModelInfo("codellama",       "Code Llama",         "ollama", "medium", "Meta code-focused model",         16000, 0, 0, False, False),
    ModelInfo("llava",           "LLaVA",              "ollama", "medium", "Vision + text model",             4096,  0, 0, False, False),
]

OLLAMA_BASE = "http://localhost:11434"


class OllamaProvider(BaseProvider):
    name = "ollama"

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> str:
        import httpx, json
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        try:
            resp = httpx.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=120.0)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except httpx.ConnectError:
            raise RuntimeError("Ollama not running. Start with: ollama serve")

    def list_models(self) -> List[ModelInfo]:
        """Return running models from Ollama + defaults."""
        import httpx
        running = []
        try:
            resp = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=3.0)
            for m in resp.json().get("models", []):
                name = m["name"].split(":")[0]
                running.append(ModelInfo(
                    id=m["name"], name=m["name"], provider="ollama",
                    tier="medium", description="Local Ollama model",
                    requires_key=False,
                ))
        except Exception:
            pass
        return running if running else DEFAULT_OLLAMA_MODELS

    @property
    def is_available(self) -> bool:
        import httpx
        try:
            httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=2.0)
            return True
        except Exception:
            return False
