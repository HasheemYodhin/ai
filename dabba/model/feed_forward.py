"""
Feed-forward network implementations for transformer blocks.

Includes:
    - SwiGLU: Swish-Gated Linear Unit (used in Llama, PaLM, etc.)
    - GELU: Gaussian Error Linear Unit
    - FeedForward: Standard FFN with configurable activation

Reference:
    "GLU Variants Improve Transformer" (Shazeer, 2020)
    https://arxiv.org/abs/2002.05202
"""

import math
from typing import Optional, Type

import torch
import torch.nn as nn
import torch.nn.functional as F


class SwiGLU(nn.Module):
    """
    Swish-Gated Linear Unit activation function.

    SwiGLU(x) = silu(x @ W_gate) * (x @ W_up)

    Unlike standard activations, SwiGLU uses a gating mechanism where
    the input is projected through two separate weight matrices (gate
    and up), and the element-wise product of their activations forms
    the output.

    Reference:
        "GLU Variants Improve Transformer" (Shazeer, 2020)

    Args:
        hidden_size: Input dimensionality.
        intermediate_size: Hidden dimensionality of the FFN.
        dropout: Dropout probability.
    """

    def __init__(
        self,
        hidden_size: int,
        intermediate_size: int,
        dropout: float = 0.0,
    ):
        super().__init__()
        self.gate_proj = nn.Linear(hidden_size, intermediate_size, bias=False)
        self.up_proj = nn.Linear(hidden_size, intermediate_size, bias=False)
        self.down_proj = nn.Linear(intermediate_size, hidden_size, bias=False)
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

        self._init_weights()

    def _init_weights(self):
        """Initialize weights using normal distribution."""
        nn.init.normal_(self.gate_proj.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.up_proj.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.down_proj.weight, mean=0.0, std=0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass for SwiGLU.

        Args:
            x: Input tensor of shape (batch_size, seq_length, hidden_size).

        Returns:
            Output tensor of the same shape.
        """
        gate = F.silu(self.gate_proj(x))
        up = self.up_proj(x)
        x = gate * up
        x = self.down_proj(x)
        x = self.dropout(x)
        return x


class GELU(nn.Module):
    """
    Gaussian Error Linear Unit activation function.

    Uses the tanh approximation for efficiency:
        GELU(x) = 0.5 * x * (1 + tanh(sqrt(2/pi) * (x + 0.044715 * x^3)))

    Reference:
        "Gaussian Error Linear Units (GELUs)" (Hendrycks & Gimpel, 2016)
        https://arxiv.org/abs/1606.08415
    """

    def __init__(self):
        super().__init__()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Apply GELU activation.

        Args:
            x: Input tensor.

        Returns:
            Activated tensor of the same shape.
        """
        return F.gelu(x)


class FeedForward(nn.Module):
    """
    Standard feed-forward network with configurable activation.

    Supports:
        - GELU: Standard FFN with GELU activation
        - SwiGLU: Gated FFN with SwiGLU activation

    Architecture:
        FFN_GELU(x) = down(GELU(up(x)))
        FFN_SwiGLU(x) = down(silu(gate(x)) * up(x))

    Args:
        hidden_size: Input/output dimensionality.
        intermediate_size: Hidden dimensionality.
        activation: Activation function ("silu" or "gelu").
        dropout: Dropout probability.
    """

    def __init__(
        self,
        hidden_size: int,
        intermediate_size: int,
        activation: str = "silu",
        dropout: float = 0.0,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.intermediate_size = intermediate_size
        self.activation = activation

        if activation == "silu":
            self.net = SwiGLU(hidden_size, intermediate_size, dropout=dropout)
        elif activation == "gelu":
            self.up_proj = nn.Linear(hidden_size, intermediate_size, bias=False)
            self.down_proj = nn.Linear(intermediate_size, hidden_size, bias=False)
            self.act = GELU()
            self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

            nn.init.normal_(self.up_proj.weight, mean=0.0, std=0.02)
            nn.init.normal_(self.down_proj.weight, mean=0.0, std=0.02)
        else:
            raise ValueError(f"Unsupported activation: {activation}")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass for the feed-forward network.

        Args:
            x: Input tensor of shape (batch_size, seq_length, hidden_size).

        Returns:
            Output tensor of the same shape.
        """
        if self.activation == "silu":
            return self.net(x)
        else:
            x = self.up_proj(x)
            x = self.act(x)
            x = self.down_proj(x)
            x = self.dropout(x)
            return x
