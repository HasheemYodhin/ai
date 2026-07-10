"""
GGUF inference backend — runs a llama.cpp-format model (e.g. your
Colab-trained Dabba 8B) directly inside the Dabba server. No Ollama needed.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dabba.inference.gguf")


class GGUFEngine:
    """
    Wraps llama-cpp-python to serve a .gguf model with the same
    interface ModelEngine expects (generate / chat).

    Args:
        model_path: Path to a .gguf file.
        n_ctx: Context window size (tokens).
        n_threads: CPU threads to use (None = auto-detect).
        n_gpu_layers: Layers to offload to GPU (0 = CPU only).
    """

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_threads: Optional[int] = None,
        n_gpu_layers: int = 0,
        system_prompt: str = (
            "You are Dabba, a highly capable personal AI assistant. "
            "You are direct, concise, and technically excellent."
        ),
    ):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.n_gpu_layers = n_gpu_layers
        self.system_prompt = system_prompt
        self._llm = None

    def load(self) -> None:
        """Load the GGUF model into memory."""
        from llama_cpp import Llama

        path = Path(self.model_path)
        if not path.exists():
            raise FileNotFoundError(f"GGUF model not found: {path}")

        logger.info(f"Loading GGUF model from {path} (n_ctx={self.n_ctx})...")
        self._llm = Llama(
            model_path=str(path),
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            n_gpu_layers=self.n_gpu_layers,
            verbose=False,
        )
        logger.info("✓ GGUF model loaded — running natively in Dabba, no Ollama needed")

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.95,
        **kwargs: Any,
    ) -> str:
        """Run chat completion using llama.cpp's chat template handling."""
        if self._llm is None:
            raise RuntimeError("GGUF model not loaded — call .load() first")

        msgs = list(messages)
        if not msgs or msgs[0].get("role") != "system":
            msgs = [{"role": "system", "content": self.system_prompt}] + msgs

        result = self._llm.create_chat_completion(
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        return result["choices"][0]["message"]["content"].strip()

    def generate(self, prompt: str, max_tokens: int = 512, **kwargs: Any) -> str:
        """Plain completion — used by ModelEngine's simpler generate() path."""
        return self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=kwargs.get("temperature", 0.7),
            top_p=kwargs.get("top_p", 0.95),
        )
