"""
Vision-to-LLM embedding projection module.

Projects the output of a vision encoder (patch embeddings) into the
embedding space of a language model so that visual information can
be consumed as prefix tokens during autoregressive generation.
"""

import logging
from typing import Optional, Union

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


class MultimodalProjection(nn.Module):
    """
    Projects vision encoder outputs into the LLM embedding space.

    Uses a two-layer MLP with a GELU activation between layers, which
    is the standard projector architecture used by LLaVA, LLaMA-3.2-Vision,
    and similar multimodal models.

    Architecture:
        Linear(input_dim, hidden_dim) → GELU → Linear(hidden_dim, output_dim)

    The projector is differentiable and its parameters are learnable,
    allowing fine-tuning to align vision and language representations.

    Args:
        input_dim: Vision encoder hidden size (e.g., 768 for SigLIP-Base).
        output_dim: LLM hidden size (e.g., 4096 for LLaMA-7B).
        hidden_dim: Projector bottleneck dimension. Default 2048.
        dropout: Dropout probability after activation. Default 0.0.
        layer_norm: Whether to apply LayerNorm before the MLP. Default True.
    """

    def __init__(
        self,
        input_dim: int = 768,
        output_dim: int = 768,
        hidden_dim: int = 2048,
        dropout: float = 0.0,
        layer_norm: bool = True,
    ):
        super().__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.hidden_dim = hidden_dim

        layers = []

        if layer_norm:
            layers.append(nn.LayerNorm(input_dim))

        layers.extend([
            nn.Linear(input_dim, hidden_dim, bias=True),
            nn.GELU(approximate="tanh"),
            nn.Dropout(dropout) if dropout > 0 else nn.Identity(),
            nn.Linear(hidden_dim, output_dim, bias=True),
        ])

        self.projector = nn.Sequential(*layers)
        self._init_weights()

    def _init_weights(self):
        """Initialise linear projections with a truncated normal."""
        for module in self.projector.modules():
            if isinstance(module, nn.Linear):
                nn.init.trunc_normal_(
                    module.weight, mean=0.0, std=0.02, a=-2.0, b=2.0
                )
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def project(
        self,
        vision_embeddings: torch.Tensor,
    ) -> torch.Tensor:
        """Alias for forward(); project vision embeddings into LLM space."""
        return self.projector(vision_embeddings)

    def forward(
        self,
        vision_embeddings: torch.Tensor,
    ) -> torch.Tensor:
        """
        Project vision embeddings into the LLM embedding space.

        Args:
            vision_embeddings: Tensor of shape (batch_size, num_patches, input_dim)
                               from the vision encoder.

        Returns:
            Projected tensor of shape (batch_size, num_patches, output_dim)
            matching the LLM's hidden size.
        """
        return self.projector(vision_embeddings)

    def forward_pooled(
        self,
        vision_embeddings: torch.Tensor,
    ) -> torch.Tensor:
        """
        Mean-pool patch embeddings before projection.

        Useful when only a single visual token is desired (e.g., for
        classification or contrastive learning).

        Args:
            vision_embeddings: Tensor of shape (batch_size, num_patches, input_dim).

        Returns:
            Projected tensor of shape (batch_size, 1, output_dim).
        """
        pooled = vision_embeddings.mean(dim=1, keepdim=True)
        return self.projector(pooled)

    def extra_repr(self) -> str:
        return (
            f"input_dim={self.input_dim}, "
            f"output_dim={self.output_dim}, "
            f"hidden_dim={self.hidden_dim}"
        )
