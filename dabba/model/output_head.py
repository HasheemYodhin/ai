"""
Output projection head for the transformer language model.

Maps the final hidden states to vocabulary logits and optionally
ties weights with the token embedding layer.
"""

import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


class OutputHead(nn.Module):
    """
    Language model output head that projects hidden states to
    vocabulary logits.

    Supports weight tying with the token embedding layer, which
    shares the embedding matrix between the input and output
    projections, significantly reducing parameter count at large
    vocabulary sizes.

    Args:
        hidden_size: Dimensionality of the transformer output.
        vocab_size: Size of the vocabulary.
        weight: Optional shared weight from TokenEmbedding layer.
        bias: If True, include a bias parameter.
        dtype: Data type for the weights.
    """

    def __init__(
        self,
        hidden_size: int,
        vocab_size: int,
        weight: Optional[torch.Tensor] = None,
        bias: bool = False,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.vocab_size = vocab_size

        if weight is not None:
            self.weight = weight
            self._tied = True
        else:
            self.weight = nn.Parameter(torch.empty(vocab_size, hidden_size))
            nn.init.normal_(self.weight, mean=0.0, std=hidden_size ** -0.5)
            self._tied = False

        if bias:
            self.bias = nn.Parameter(torch.zeros(vocab_size))
        else:
            self.register_parameter("bias", None)

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """
        Project hidden states to vocabulary logits.

        Args:
            hidden_states: Transformer output of shape
                (batch_size, seq_length, hidden_size).

        Returns:
            Logits tensor of shape (batch_size, seq_length, vocab_size).
        """
        logits = F.linear(hidden_states, self.weight, self.bias)
        return logits

    @property
    def is_tied(self) -> bool:
        """Check if weights are tied with the embedding layer."""
        return self._tied

    def extra_repr(self) -> str:
        return (
            f"hidden_size={self.hidden_size}, vocab_size={self.vocab_size}, "
            f"tied={self._tied}"
        )
