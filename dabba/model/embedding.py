"""
Token and positional embedding implementations.

Includes:
    - TokenEmbedding: Standard token embedding lookup table
    - RotaryEmbedding: Rotary Positional Embeddings (RoPE) from
      "RoFormer: Enhanced Transformer with Rotary Position Embedding"
    - apply_rotary_pos_emb: Function to apply rotary embeddings to
      query and key tensors
"""

import math
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class TokenEmbedding(nn.Module):
    """
    Token embedding layer that maps token IDs to dense vectors.

    Supports weight tying with the output projection layer for
    parameter efficiency.

    Args:
        vocab_size: Size of the vocabulary.
        hidden_size: Dimensionality of the embedding space.
        padding_idx: Index of the padding token (embeddings at this
            index are not updated during training).
        dropout: Dropout probability applied to embeddings.
    """

    def __init__(
        self,
        vocab_size: int,
        hidden_size: int,
        padding_idx: int = 0,
        dropout: float = 0.0,
    ):
        super().__init__()
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.padding_idx = padding_idx

        self.weight = nn.Parameter(
            torch.empty(vocab_size, hidden_size)
        )
        nn.init.normal_(self.weight, mean=0.0, std=hidden_size ** -0.5)

        if padding_idx is not None:
            self.weight.data[padding_idx].zero_()

        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        """
        Convert token IDs to embeddings.

        Args:
            input_ids: Token IDs of shape (batch_size, seq_length).

        Returns:
            Embedding tensor of shape (batch_size, seq_length, hidden_size).
        """
        embeds = F.embedding(input_ids, self.weight, padding_idx=self.padding_idx)
        embeds = embeds * math.sqrt(self.hidden_size)
        embeds = self.dropout(embeds)
        return embeds


class RotaryEmbedding(nn.Module):
    """
    Rotary Positional Embedding (RoPE) implementation.

    Applies rotation to query and key vectors based on their position
    in the sequence, enabling relative position encoding without
    explicit position embeddings.

    Reference:
        "RoFormer: Enhanced Transformer with Rotary Position Embedding"
        (Su et al., 2021) - https://arxiv.org/abs/2104.09864

    Args:
        dim: Dimensionality of the rotation (head_dim).
        max_position_embeddings: Maximum sequence length supported.
        base: Base for the frequency computation (theta).
        scaling_factor: Scaling factor for extended context (NTK-aware).
        partial_rotary_factor: Fraction of dimensions to rotate.
    """

    def __init__(
        self,
        dim: int,
        max_position_embeddings: int = 2048,
        base: float = 10000.0,
        scaling_factor: float = 1.0,
        partial_rotary_factor: float = 1.0,
    ):
        super().__init__()
        self.dim = dim
        self.max_position_embeddings = max_position_embeddings
        self.base = base
        self.scaling_factor = scaling_factor
        self.partial_rotary_factor = partial_rotary_factor

        rotary_dim = int(dim * partial_rotary_factor)
        self.rotary_dim = rotary_dim

        # Use all rotary_dim frequencies so emb = cat([freqs, freqs]) gives (seq, 2*rotary_dim)
        inv_freq = 1.0 / (
            base ** (torch.arange(0, rotary_dim, dtype=torch.float32) / rotary_dim)
        )
        self.register_buffer("inv_freq", inv_freq, persistent=False)

        self._set_cos_sin_cache(max_position_embeddings)

    def _set_cos_sin_cache(self, seq_len: int) -> None:
        """
        Precompute cosine and sine values for all positions up to
        seq_len.

        Args:
            seq_len: Maximum sequence length to cache.
        """
        t = torch.arange(seq_len, dtype=torch.float32) / self.scaling_factor
        freqs = torch.outer(t, self.inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)

        self.register_buffer("cos_cached", emb.cos().unsqueeze(0).unsqueeze(0),
                             persistent=False)
        self.register_buffer("sin_cached", emb.sin().unsqueeze(0).unsqueeze(0),
                             persistent=False)

    def forward(
        self,
        x: torch.Tensor,
        position_ids: torch.Tensor,
        seq_len: Optional[int] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Get cosine and sine values for the given positions.

        Args:
            x: Input tensor (used to determine device/dtype).
            position_ids: Position IDs of shape (batch_size, seq_length).
            seq_len: Optional sequence length for cache check.

        Returns:
            Tuple of (cos, sin) tensors for rotary embedding.
            Each has shape (batch_size, 1, seq_length, rotary_dim).
        """
        max_seq_len = position_ids.max().item() + 1
        if max_seq_len > self.cos_cached.shape[2]:
            self._set_cos_sin_cache(max_seq_len * 2)

        cos = self.cos_cached[:, :, position_ids]  # (1, 1, batch, seq_len, rotary_dim)
        sin = self.sin_cached[:, :, position_ids]  # (1, 1, batch, seq_len, rotary_dim)
        cos = cos.squeeze(0).squeeze(0)  # (batch, seq_len, rotary_dim)
        sin = sin.squeeze(0).squeeze(0)  # (batch, seq_len, rotary_dim)
        cos = cos.unsqueeze(1)  # (batch, 1, seq_len, rotary_dim)
        sin = sin.unsqueeze(1)  # (batch, 1, seq_len, rotary_dim)

        return cos, sin


def apply_rotary_pos_emb(
    q: torch.Tensor,
    k: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor,
) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Apply rotary position embeddings to query and key tensors.

    The rotation is computed as:
        q_rotated = q * cos + rotate_half(q) * sin

    Args:
        q: Query tensor of shape (batch_size, num_heads, seq_len, head_dim).
        k: Key tensor of shape (batch_size, num_kv_heads, seq_len, head_dim).
        cos: Cosine values of shape (batch_size, 1, seq_len, head_dim).
        sin: Sine values of shape (batch_size, 1, seq_len, head_dim).

    Returns:
        Tuple of (rotated_q, rotated_k).
    """
    # Slice cos/sin to match q/k head_dim (cos may be 2*head_dim)
    head_dim = q.shape[-1]
    cos = cos[..., :head_dim]
    sin = sin[..., :head_dim]
    q_embed = (q * cos) + (rotate_half(q) * sin)
    k_embed = (k * cos) + (rotate_half(k) * sin)

    return q_embed, k_embed


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    """
    Rotate the second half of the last dimension by negating it.

    This implements the rotation operation for RoPE:
        rotate_half([x1, x2]) = [-x2, x1]

    Args:
        x: Input tensor.

    Returns:
        Rotated tensor.
    """
    x1 = x[..., :x.shape[-1] // 2]
    x2 = x[..., x.shape[-1] // 2:]
    return torch.cat((-x2, x1), dim=-1)
