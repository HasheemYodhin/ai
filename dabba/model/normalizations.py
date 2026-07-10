"""
Normalization layers: RMSNorm and LayerNorm implementations.

RMSNorm (Root Mean Square Normalization) is preferred for transformer
models as it is computationally lighter than LayerNorm while providing
comparable performance.

Reference:
    "Root Mean Square Layer Normalization" (Zhang & Sennrich, 2019)
    https://arxiv.org/abs/1910.07467
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class RMSNorm(nn.Module):
    """
    Root Mean Square Layer Normalization (RMSNorm).

    Normalizes the input by the root mean square of the activations
    and applies a learnable scale parameter. Computationally cheaper
    than LayerNorm as it does not compute mean and variance.

    Math:
        RMSNorm(x) = x / RMS(x) * weight
        RMS(x) = sqrt(mean(x^2) + eps)

    Args:
        hidden_size: Dimensionality of the input.
        eps: Small constant for numerical stability.
        elementwise_affine: If True, learnable affine transform.
        bias: If True, include a bias parameter.
    """

    def __init__(
        self,
        hidden_size: int,
        eps: float = 1e-6,
        elementwise_affine: bool = True,
        bias: bool = False,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.eps = eps
        self.elementwise_affine = elementwise_affine

        if elementwise_affine:
            self.weight = nn.Parameter(torch.ones(hidden_size))
            self.bias = nn.Parameter(torch.zeros(hidden_size)) if bias else None
        else:
            self.register_parameter("weight", None)
            self.register_parameter("bias", None)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Apply RMS normalization.

        Args:
            x: Input tensor of shape (..., hidden_size).

        Returns:
            Normalized tensor of the same shape.
        """
        input_dtype = x.dtype
        x = x.to(torch.float32)
        variance = x.pow(2).mean(-1, keepdim=True)
        x = x * torch.rsqrt(variance + self.eps)

        if self.weight is not None:
            x = x * self.weight.to(torch.float32)

        if self.bias is not None:
            x = x + self.bias.to(torch.float32)

        return x.to(input_dtype)

    def extra_repr(self) -> str:
        return f"hidden_size={self.hidden_size}, eps={self.eps}"


class LayerNorm(nn.Module):
    """
    Standard Layer Normalization.

    Normalizes input by mean and variance, then applies learnable
    affine transform.

    Reference:
        "Layer Normalization" (Ba et al., 2016)
        https://arxiv.org/abs/1607.06450

    Args:
        hidden_size: Dimensionality of the input.
        eps: Small constant for numerical stability.
        elementwise_affine: If True, learnable affine transform.
        bias: If True, include a bias parameter.
    """

    def __init__(
        self,
        hidden_size: int,
        eps: float = 1e-6,
        elementwise_affine: bool = True,
        bias: bool = True,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.eps = eps
        self.elementwise_affine = elementwise_affine

        if elementwise_affine:
            self.weight = nn.Parameter(torch.ones(hidden_size))
            self.bias = nn.Parameter(torch.zeros(hidden_size)) if bias else None
        else:
            self.register_parameter("weight", None)
            self.register_parameter("bias", None)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Apply layer normalization.

        Args:
            x: Input tensor of shape (..., hidden_size).

        Returns:
            Normalized tensor of the same shape.
        """
        input_dtype = x.dtype
        x = x.to(torch.float32)
        mean = x.mean(-1, keepdim=True)
        variance = x.var(-1, keepdim=True, unbiased=False)
        x = (x - mean) * torch.rsqrt(variance + self.eps)

        if self.weight is not None:
            x = x * self.weight.to(torch.float32)
        if self.bias is not None:
            x = x + self.bias.to(torch.float32)

        return x.to(input_dtype)

    def extra_repr(self) -> str:
        return f"hidden_size={self.hidden_size}, eps={self.eps}"
