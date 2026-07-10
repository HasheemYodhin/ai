"""
Main text generator for trained transformer models.

Provides a unified interface for text generation with configurable
sampling strategies, batch generation, and conversation support.

"""

from dataclasses import dataclass, field
from typing import List, Optional, Union

import torch
import torch.nn as nn

from dabba.inference.samplers import (
    Sampler,
    TemperatureSampler,
    TopKSampler,
    TopPSampler,
)
from dabba.inference.beam_search import BeamSearch
from dabba.inference.streaming import StreamingGenerator


@dataclass
class GenerationConfig:
    max_length: int = 100
    temperature: float = 1.0
    top_k: int = 50
    top_p: float = 0.9
    do_sample: bool = True
    repetition_penalty: float = 1.0
    eos_token_id: Optional[int] = None
    pad_token_id: Optional[int] = None


class Generator:
    """
    High-level text generator for trained transformer models.

    Supports:
        - Single and batch generation
        - Temperature, top-K, top-P sampling
        - Beam search
        - Greedy decoding
        - Streaming generation
        - Conversation memory (maintains context across turns)

    Args:
        model: The trained transformer model.
        tokenizer: Optional tokenizer (needed for conversation mode).
        eos_token_id: End-of-sequence token ID.
        pad_token_id: Padding token ID.
    """

    def __init__(
        self,
        model: nn.Module,
        tokenizer: Optional[object] = None,
        eos_token_id: int = 2,
        pad_token_id: int = 0,
    ):
        self.model = model
        self.tokenizer = tokenizer
        self.eos_token_id = eos_token_id
        self.pad_token_id = pad_token_id
        self._conversation_history: List[int] = []

    def _build_sampler(
        self,
        temperature: float = 1.0,
        top_k: Optional[int] = None,
        top_p: Optional[float] = None,
        do_sample: bool = True,
    ) -> Sampler:
        """
        Build the appropriate sampler based on parameters.

        Priority: top_k > top_p > temperature > greedy.

        Args:
            temperature: Sampling temperature.
            top_k: Top-K filtering.
            top_p: Top-P (nucleus) filtering.
            do_sample: If True, sample from distribution.

        Returns:
            Configured Sampler instance.
        """
        if top_k is not None:
            return TopKSampler(k=top_k, temperature=temperature, do_sample=do_sample)
        elif top_p is not None:
            return TopPSampler(p=top_p, temperature=temperature, do_sample=do_sample)
        else:
            return TemperatureSampler(temperature=temperature, do_sample=do_sample)

    @torch.no_grad()
    def generate(
        self,
        input_ids: torch.Tensor,
        max_tokens: int = 100,
        max_length: Optional[int] = None,
        temperature: float = 1.0,
        top_k: Optional[int] = None,
        top_p: Optional[float] = None,
        do_sample: bool = True,
        eos_token_id: Optional[int] = None,
        pad_token_id: Optional[int] = None,
        use_cache: bool = True,
        repetition_penalty: float = 1.0,
        no_repeat_ngram_size: int = 0,
        min_length: int = 0,
    ) -> torch.Tensor:
        """
        Generate text from a prompt.

        Returns:
            Generated token IDs including the prompt.
        """
        if max_length is not None:
            max_tokens = max_length
        eos_id = eos_token_id if eos_token_id is not None else self.eos_token_id
        sampler = self._build_sampler(temperature, top_k, top_p, do_sample)

        seq_len = input_ids.shape[1]
        generated = input_ids.clone()
        steps = max_tokens - seq_len if max_length is not None else max_tokens

        for step in range(max(steps, 1)):
            try:
                outputs = self.model.forward(generated)
            except Exception:
                outputs = self.model(generated)

            if not isinstance(outputs, dict):
                outputs = {"logits": outputs}

            logits = outputs["logits"][:, -1, :]

            next_tokens = sampler.sample(logits).unsqueeze(-1)  # (batch, 1)
            generated = torch.cat([generated, next_tokens], dim=-1)

            if generated.shape[-1] >= max_tokens:
                break
            if eos_id is not None and (next_tokens.squeeze(-1) == eos_id).all():
                if generated.shape[-1] >= min_length:
                    break

        return generated

    def generate_batch(
        self,
        prompts: List[torch.Tensor],
        **kwargs,
    ) -> List[torch.Tensor]:
        """
        Generate text for multiple prompts.

        Args:
            prompts: List of prompt tensors.
            **kwargs: Generation parameters passed to generate().

        Returns:
            List of generated token sequences.
        """
        return [self.generate(p.unsqueeze(0), **kwargs)[0] for p in prompts]

    def stream(
        self,
        input_ids: torch.Tensor,
        **kwargs,
    ):
        """
        Stream generated tokens one at a time.

        Args:
            input_ids: Prompt token IDs.
            **kwargs: Additional parameters.

        Yields:
            Generated token IDs one at a time.
        """
        streamer = StreamingGenerator(
            model=self.model,
            sampler=self._build_sampler(
                temperature=kwargs.get("temperature", 1.0),
                top_k=kwargs.get("top_k"),
                top_p=kwargs.get("top_p"),
                do_sample=kwargs.get("do_sample", True),
            ),
            eos_token_id=kwargs.get("eos_token_id", self.eos_token_id),
            pad_token_id=kwargs.get("pad_token_id", self.pad_token_id),
            max_new_tokens=kwargs.get("max_new_tokens", 1024),
            stop_tokens=kwargs.get("stop_tokens"),
        )
        return streamer.generate(input_ids)

    def beam_search(
        self,
        input_ids: torch.Tensor,
        beam_size: int = 5,
        max_length: int = 100,
        **kwargs,
    ) -> torch.Tensor:
        """
        Generate text using beam search.

        Args:
            input_ids: Prompt token IDs.
            beam_size: Number of parallel beams.
            max_length: Maximum generation length.
            **kwargs: Additional beam search parameters.

        Returns:
            Best generated sequence including the prompt.
        """
        beam = BeamSearch(
            model=self.model,
            beam_size=beam_size,
            max_length=max_length,
            eos_token_id=kwargs.get("eos_token_id", self.eos_token_id),
            pad_token_id=kwargs.get("pad_token_id", self.pad_token_id),
            length_penalty=kwargs.get("length_penalty", 1.0),
            early_stopping=kwargs.get("early_stopping", True),
        )
        return beam.generate(input_ids)

    def chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        """
        Generate a response in conversation mode.

        Maintains conversation history across calls for multi-turn
        interactions.

        Args:
            message: User message.
            system_prompt: Optional system prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            **kwargs: Additional generation parameters.

        Returns:
            Generated response string.
        """
        if self.tokenizer is None:
            raise ValueError("Tokenizer required for chat mode")

        tokens = self.tokenizer.encode(message)
        self._conversation_history.extend(tokens)

        input_tensor = torch.tensor(
            [self._conversation_history[-2048:]], dtype=torch.long
        )

        generated = self.generate(
            input_tensor,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

        new_tokens = generated[0].tolist()
        response_tokens = new_tokens[len(self._conversation_history[-2048:]):]
        self._conversation_history.extend(response_tokens)

        response = self.tokenizer.decode(response_tokens)
        return response

    def reset_conversation(self) -> None:
        """Clear conversation history."""
        self._conversation_history.clear()

    def generate_stream(self, input_ids: torch.Tensor, **kwargs):
        """Yield tokens one at a time."""
        from dabba.inference.streaming import StreamingGenerator
        sg = StreamingGenerator(model=self.model)
        yield from sg.generate(input_ids, **kwargs)
