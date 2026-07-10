"""
Token sampling strategies for text generation.

Provides temperature scaling, top-K filtering, and top-P (nucleus)
sampling to control the quality and diversity of generated text.
"""

from typing import Optional

import torch
import torch.nn.functional as F


class Sampler:
    """
    Base sampler class. Provides the core API for applying sampling
    strategies to logits.
    """

    def sample(self, logits: torch.Tensor) -> torch.Tensor:
        """
        Sample a token from the logits distribution.

        Subclasses should override this method.

        Args:
            logits: Shape (batch_size, vocab_size).

        Returns:
            Sampled token IDs of shape (batch_size, 1).
        """
        return logits.argmax(dim=-1, keepdim=True)


class TemperatureSampler(Sampler):
    """
    Temperature-based sampling.

    Scales logits by temperature before applying softmax. Higher
    temperatures (>1.0) make the distribution more uniform (more
    random), while lower temperatures (<1.0) make it more peaked
    (more deterministic).

    Args:
        temperature: Temperature value (> 0). 1.0 = no change.
        do_sample: If False, use greedy decoding.
    """

    def __init__(self, temperature: float = 1.0, do_sample: bool = True):
        super().__init__()
        self.temperature = temperature
        self.do_sample = do_sample

    def sample(self, logits: torch.Tensor) -> torch.Tensor:
        """
        Apply temperature sampling.

        Args:
            logits: Shape (batch_size, vocab_size).

        Returns:
            Sampled token IDs of shape (batch_size,).
        """
        if not self.do_sample or self.temperature == 0.0:
            return logits.argmax(dim=-1)

        scaled_logits = logits / max(self.temperature, 1e-8)
        probs = F.softmax(scaled_logits, dim=-1)
        return torch.multinomial(probs, num_samples=1).squeeze(-1)


class TopKSampler(TemperatureSampler):
    """
    Top-K sampling with temperature.

    Filters the logits to only the top-K most probable tokens before
    sampling. The probabilities of the remaining tokens are set to
    -inf, ensuring they are not selected.

    Args:
        k: Number of top tokens to keep.
        temperature: Temperature value.
        do_sample: If False, use greedy decoding.
    """

    def __init__(self, k: int = 50, temperature: float = 1.0, do_sample: bool = True):
        super().__init__(temperature=temperature, do_sample=do_sample)
        self.k = k

    def sample(self, logits: torch.Tensor) -> torch.Tensor:
        """
        Apply top-K filtering followed by temperature sampling.

        Args:
            logits: Shape (batch_size, vocab_size).

        Returns:
            Sampled token IDs.
        """
        if not self.do_sample:
            return logits.argmax(dim=-1)

        top_k_values, top_k_indices = torch.topk(logits, min(self.k, logits.shape[-1]), dim=-1)
        filtered_logits = torch.full_like(logits, float("-inf"))
        filtered_logits.scatter_(-1, top_k_indices, top_k_values)

        return super().sample(filtered_logits)


class TopPSampler(TemperatureSampler):
    """
    Top-P (nucleus) sampling with temperature.

    Filters the logits to the smallest set of tokens whose cumulative
    probability exceeds the threshold P. This dynamically adjusts the
    number of candidate tokens based on the distribution shape.

    Args:
        p: Cumulative probability threshold (0.0 to 1.0).
        temperature: Temperature value.
        do_sample: If False, use greedy decoding.
        min_tokens_to_keep: Minimum number of tokens to keep.
    """

    def __init__(
        self,
        p: float = 0.9,
        temperature: float = 1.0,
        do_sample: bool = True,
        min_tokens_to_keep: int = 1,
    ):
        super().__init__(temperature=temperature, do_sample=do_sample)
        self.p = p
        self.min_tokens_to_keep = min_tokens_to_keep

    def sample(self, logits: torch.Tensor) -> torch.Tensor:
        """
        Apply top-P (nucleus) filtering followed by sampling.

        Args:
            logits: Shape (batch_size, vocab_size).

        Returns:
            Sampled token IDs.
        """
        if not self.do_sample:
            return logits.argmax(dim=-1)

        scaled_logits = logits / max(self.temperature, 1e-8)
        sorted_logits, sorted_indices = torch.sort(scaled_logits, descending=True, dim=-1)
        cumulative_probs = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)

        sorted_indices_to_remove = cumulative_probs - F.softmax(sorted_logits, dim=-1) > self.p
        if self.min_tokens_to_keep > 1:
            sorted_indices_to_remove[..., :self.min_tokens_to_keep] = False

        indices_to_remove = sorted_indices_to_remove.scatter(-1, sorted_indices, sorted_indices_to_remove)
        filtered_logits = scaled_logits.masked_fill(indices_to_remove, float("-inf"))

        probs = F.softmax(filtered_logits, dim=-1)
        return torch.multinomial(probs, num_samples=1).squeeze(-1)


SamplerBase = Sampler


class GreedySampler(Sampler):
    """Always selects the highest-probability token."""

    def sample(self, logits: torch.Tensor) -> torch.Tensor:
        return logits.argmax(dim=-1)


class BeamSampler(Sampler):
    """Beam search sampler stub — wraps greedy for compatibility."""

    def __init__(self, num_beams: int = 4, **kwargs):
        super().__init__()
        self.num_beams = num_beams

    def sample(self, logits: torch.Tensor) -> torch.Tensor:
        return logits.argmax(dim=-1)
