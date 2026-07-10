from __future__ import annotations
from typing import Dict, List
from dabba.providers.base import BaseProvider, ModelInfo


MODELS = [
    ModelInfo("dabba", "Dabba (own)", "dabba", "medium",
              "Your personally trained model", 256, 0, 0, False, False),
]


class DabbaProvider(BaseProvider):
    name = "dabba"

    def __init__(self, endpoint: str = "http://localhost:8080"):
        self.endpoint = endpoint

    def chat(self, messages, model="dabba", max_tokens=512, temperature=0.7, **kwargs) -> str:
        import httpx
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            resp = httpx.post(
                f"{self.endpoint}/v1/chat/completions",
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.ConnectError:
            raise RuntimeError(f"Dabba server not running at {self.endpoint}. Start with: python3 -m dabba.api.server")

    def list_models(self) -> List[ModelInfo]:
        return MODELS

    @property
    def is_available(self) -> bool:
        import httpx
        try:
            httpx.get(f"{self.endpoint}/health", timeout=2.0)
            return True
        except Exception:
            return False
