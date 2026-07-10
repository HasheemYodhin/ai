"""
Streaming token generator that yields tokens one at a time as they
are produced, enabling real-time output display.
"""

from typing import Callable, Generator, List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from dabba.inference.samplers import Sampler, TopKSampler, TopPSampler


class StreamingGenerator:
    """
    Generates tokens one at a time, yielding each token as it is
    produced for real-time streaming display.

    Supports stop tokens, temperature, top-K, and top-P sampling.

    Args:
        model: The transformer model.
        sampler: Optional custom sampler (default: TopPSampler).
        eos_token_id: End-of-sequence token ID.
        pad_token_id: Padding token ID.
        max_new_tokens: Maximum tokens to generate.
        stop_tokens: Additional stop token IDs.
        callback: Optional callback called after each token generation.
    """

    def __init__(
        self,
        model: Optional[nn.Module] = None,
        sampler: Optional[Sampler] = None,
        eos_token_id: int = 2,
        pad_token_id: int = 0,
        max_new_tokens: int = 1024,
        stop_tokens: Optional[List[int]] = None,
        callback: Optional[Callable[[int], None]] = None,
    ):
        self.model = model
        self.sampler = sampler or TopPSampler(p=0.9, temperature=0.7)
        self.eos_token_id = eos_token_id
        self.pad_token_id = pad_token_id
        self.max_new_tokens = max_new_tokens
        self.stop_tokens = set(stop_tokens or [])
        self.stop_tokens.add(eos_token_id)
        self.callback = callback

        # Assignable hooks (tests set these as lambdas)
        self.on_next_token: Optional[Callable[[int], None]] = None
        self.on_finished: Callable[[], None] = lambda: None
        self.on_error: Optional[Callable[[Exception], None]] = None

    @torch.no_grad()
    def generate(
        self,
        input_ids: torch.Tensor,
        max_length: Optional[int] = None,
        **kwargs,
    ) -> Generator[int, None, List[int]]:
        """
        Generate tokens one at a time, yielding each token ID.

        Yields:
            Generated token IDs one at a time.
        """
        generated = []
        device = input_ids.device
        seq_len = input_ids.shape[-1]
        max_new = (max_length - seq_len) if max_length is not None else self.max_new_tokens
        max_new = max(1, max_new)
        current_ids = input_ids.clone()

        for step in range(max_new):
            try:
                outputs = self.model.forward(current_ids)
            except Exception:
                outputs = self.model(current_ids)

            if not isinstance(outputs, dict):
                outputs = {"logits": outputs}

            logits = outputs["logits"][:, -1, :]
            next_token = self.sampler.sample(logits)
            next_id = int(next_token.flatten()[0].item())

            generated.append(next_id)
            yield next_id

            if self.callback:
                self.callback(next_id)

            if next_id in self.stop_tokens:
                break

            current_ids = torch.cat([current_ids, next_token.view(1, -1)], dim=-1)

        return generated


StreamingHandler = StreamingGenerator
