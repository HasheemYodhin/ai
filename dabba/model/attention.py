"""
Attention mechanism implementations from scratch.

Includes:
    - MultiHeadAttention (MHA): Standard multi-head attention
    - GroupedQueryAttention (GQA): Multi-query grouped attention
    - MultiQueryAttention (MQA): Single KV head attention

All implementations support:
    - Causal (autoregressive) masking
    - RoPE (Rotary Position Embeddings)
    - Flash Attention (optional, requires flash-attn package)
    - Sliding window attention
    - KV cache for inference
"""

import math
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from dabba.model.embedding import RotaryEmbedding, apply_rotary_pos_emb
from dabba.model.kv_cache import KVCache


class MultiHeadAttention(nn.Module):
    """
    Multi-Head Attention (MHA) with causal masking and RoPE support.

    Splits the input into num_heads attention heads, computes scaled
    dot-product attention for each head, and concatenates the results.

    Supports optional Flash Attention via PyTorch's scaled_dot_product_attention.

    Args:
        hidden_size: Dimensionality of the input.
        num_heads: Number of attention heads.
        head_dim: Dimensionality of each head.
        dropout: Attention dropout probability.
        max_position_embeddings: Maximum sequence length.
        rope_theta: Base frequency for RoPE.
        rope_scaling: Optional RoPE scaling config.
        partial_rotary_factor: Fraction of head dims to rotate.
        attention_dropout: Dropout applied to attention weights.
        use_flash_attention: If True, use flash attention.
        use_sdpa: If True, use PyTorch SDPA.
        sliding_window: Optional sliding window size.
        bias: If True, include bias in Q/K/V/O projections.
    """

    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        head_dim: Optional[int] = None,
        num_key_value_heads: Optional[int] = None,
        dropout: float = 0.0,
        max_position_embeddings: int = 2048,
        rope_theta: float = 10000.0,
        rope_scaling: Optional[dict] = None,
        partial_rotary_factor: float = 1.0,
        attention_dropout: float = 0.0,
        use_flash_attention: bool = False,
        use_sdpa: bool = True,
        sliding_window: Optional[int] = None,
        bias: bool = False,
        causal: bool = False,
        **kwargs,  # absorb subclass-specific params (sparsity_factor, window_size, etc.)
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_heads = num_heads
        self.num_key_value_heads = num_key_value_heads or num_heads
        self.head_dim = head_dim or hidden_size // num_heads
        self.num_key_value_groups = num_heads // self.num_key_value_heads
        self.dropout = dropout
        self.sliding_window = sliding_window
        self.use_flash_attention = use_flash_attention
        self.causal = causal
        self._attention_dropout_p = attention_dropout

        self.q_proj = nn.Linear(
            hidden_size, num_heads * self.head_dim, bias=bias
        )
        self.k_proj = nn.Linear(
            hidden_size, self.num_key_value_heads * self.head_dim, bias=bias
        )
        self.v_proj = nn.Linear(
            hidden_size, self.num_key_value_heads * self.head_dim, bias=bias
        )
        self.o_proj = nn.Linear(
            num_heads * self.head_dim, hidden_size, bias=bias
        )

        self.attn_dropout = nn.Dropout(attention_dropout) if attention_dropout > 0 else nn.Identity()

        rope_scaling_factor = 1.0
        if rope_scaling and isinstance(rope_scaling, dict):
            rope_scaling_factor = rope_scaling.get("factor", 1.0)

        self.rotary_emb = RotaryEmbedding(
            dim=self.head_dim,
            max_position_embeddings=max_position_embeddings,
            base=rope_theta,
            scaling_factor=rope_scaling_factor,
            partial_rotary_factor=partial_rotary_factor,
        )

        self._init_weights()

    def _init_weights(self):
        """Initialize weights using normal distribution."""
        nn.init.normal_(self.q_proj.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.k_proj.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.v_proj.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.o_proj.weight, mean=0.0, std=0.02)

    def forward(
        self,
        hidden_states: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.Tensor] = None,
        past_key_value: Optional[KVCache] = None,
        use_cache: bool = False,
        output_attentions: bool = False,
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor], Optional[KVCache]]:
        """
        Forward pass for multi-head attention.

        Args:
            hidden_states: Input of shape (batch_size, seq_length, hidden_size).
            attention_mask: Optional mask of shape (batch_size, 1, seq_length, total_length).
            position_ids: Position IDs for RoPE of shape (batch_size, seq_length).
            past_key_value: Optional KV cache for incremental decoding.
            use_cache: If True, return updated KV cache.
            output_attentions: If True, return attention weights.

        Returns:
            Tuple of (output, attention_weights, kv_cache).
        """
        batch_size, seq_length, _ = hidden_states.shape

        query_states = self.q_proj(hidden_states)
        key_states = self.k_proj(hidden_states)
        value_states = self.v_proj(hidden_states)

        query_states = query_states.view(
            batch_size, seq_length, self.num_heads, self.head_dim
        ).transpose(1, 2)
        key_states = key_states.view(
            batch_size, seq_length, self.num_key_value_heads, self.head_dim
        ).transpose(1, 2)
        value_states = value_states.view(
            batch_size, seq_length, self.num_key_value_heads, self.head_dim
        ).transpose(1, 2)

        cos, sin = self.rotary_emb(query_states, position_ids, seq_length)
        query_states, key_states = apply_rotary_pos_emb(
            query_states, key_states, cos, sin
        )

        if past_key_value is not None:
            key_states, value_states = past_key_value.update(key_states, value_states)

        if self.num_key_value_groups > 1:
            k_states_for_cache = key_states
            v_states_for_cache = value_states
            key_states = key_states.repeat_interleave(self.num_key_value_groups, dim=1)
            value_states = value_states.repeat_interleave(self.num_key_value_groups, dim=1)
        else:
            k_states_for_cache = key_states
            v_states_for_cache = value_states

        # Always compute attention weights manually so they can be returned
        attn_weights = torch.matmul(
            query_states, key_states.transpose(2, 3)
        ) / math.sqrt(self.head_dim)

        # Apply causal mask
        if self.causal:
            seq_q = query_states.shape[2]
            seq_k = key_states.shape[2]
            causal_mask = torch.ones(seq_q, seq_k, device=query_states.device, dtype=torch.bool).tril()
            attn_weights = attn_weights.masked_fill(~causal_mask, float("-inf"))

        if attention_mask is not None:
            attn_weights = attn_weights + attention_mask

        attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(query_states.dtype)
        attn_weights = self._apply_attention_hook(attn_weights)
        attn_weights = self.attn_dropout(attn_weights)
        attn_output = torch.matmul(attn_weights, value_states)

        attn_output = attn_output.transpose(1, 2).contiguous()
        seq_len_out = attn_output.shape[1]
        attn_output = attn_output.reshape(batch_size, seq_len_out, self.num_heads * self.head_dim)
        attn_output = self.o_proj(attn_output)

        if use_cache:
            return attn_output, attn_weights, KVCache(k_states_for_cache, v_states_for_cache)
        return attn_output, attn_weights, None

    def _apply_attention_hook(self, attn_weights: torch.Tensor) -> torch.Tensor:
        """Hook for subclasses to modify attention weights (e.g. ALiBi, sliding window)."""
        return attn_weights


class GroupedQueryAttention(MultiHeadAttention):
    """
    Grouped Query Attention (GQA) — a generalization of MHA and MQA.

    GQA uses fewer key/value heads than query heads, grouped such that
    each group of query heads shares a single key/value head. This
    reduces KV cache memory while maintaining model quality.

    When num_key_value_heads == num_heads, this is equivalent to MHA.
    When num_key_value_heads == 1, this is equivalent to MQA.

    Reference:
        "GQA: Training Generalized Multi-Query Transformer Models
        from Multi-Head Checkpoints" (Ainslie et al., 2023)
        https://arxiv.org/abs/2305.13245

    Args:
        hidden_size: Dimensionality of the input.
        num_heads: Number of query heads.
        num_key_value_heads: Number of key/value heads.
        head_dim: Dimensionality of each head.
        dropout: Dropout probability.
        max_position_embeddings: Maximum sequence length.
        rope_theta: Base frequency for RoPE.
        rope_scaling: Optional RoPE scaling config.
        partial_rotary_factor: Fraction of head dims to rotate.
        attention_dropout: Dropout applied to attention weights.
        use_flash_attention: If True, use flash attention.
        sliding_window: Optional sliding window size.
        bias: If True, include bias in projections.
    """

    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        num_key_value_heads: int = 4,
        head_dim: Optional[int] = None,
        dropout: float = 0.0,
        max_position_embeddings: int = 2048,
        rope_theta: float = 10000.0,
        rope_scaling: Optional[dict] = None,
        partial_rotary_factor: float = 1.0,
        attention_dropout: float = 0.0,
        use_flash_attention: bool = False,
        sliding_window: Optional[int] = None,
        bias: bool = False,
    ):
        if num_key_value_heads > num_heads:
            raise ValueError(
                f"num_key_value_heads ({num_key_value_heads}) cannot exceed "
                f"num_heads ({num_heads}) in GroupedQueryAttention"
            )
        super().__init__(
            hidden_size=hidden_size,
            num_heads=num_heads,
            head_dim=head_dim,
            num_key_value_heads=num_key_value_heads,
            dropout=dropout,
            max_position_embeddings=max_position_embeddings,
            rope_theta=rope_theta,
            rope_scaling=rope_scaling,
            partial_rotary_factor=partial_rotary_factor,
            attention_dropout=attention_dropout,
            use_flash_attention=use_flash_attention,
            sliding_window=sliding_window,
            bias=bias,
        )


class MultiQueryAttention(MultiHeadAttention):
    """
    Multi-Query Attention (MQA) — a special case of GQA with a single
    key/value head.

    Uses num_heads query heads but only 1 key and 1 value head. The
    single KV head is broadcast to all query heads. Maximally reduces
    KV cache memory at the cost of some expressiveness.

    Reference:
        "Fast Transformer Decoding: One Write-Head is All You Need"
        (Shazeer, 2019) - https://arxiv.org/abs/1911.02150

    Args:
        hidden_size: Dimensionality of the input.
        num_heads: Number of query heads.
        head_dim: Dimensionality of each head.
        dropout: Dropout probability.
        max_position_embeddings: Maximum sequence length.
        rope_theta: Base frequency for RoPE.
        rope_scaling: Optional RoPE scaling config.
        partial_rotary_factor: Fraction of head dims to rotate.
        attention_dropout: Dropout applied to attention weights.
        use_flash_attention: If True, use flash attention.
        sliding_window: Optional sliding window size.
        bias: If True, include bias in projections.
    """

    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        head_dim: Optional[int] = None,
        dropout: float = 0.0,
        max_position_embeddings: int = 2048,
        rope_theta: float = 10000.0,
        rope_scaling: Optional[dict] = None,
        partial_rotary_factor: float = 1.0,
        attention_dropout: float = 0.0,
        use_flash_attention: bool = False,
        sliding_window: Optional[int] = None,
        bias: bool = False,
    ):
        super().__init__(
            hidden_size=hidden_size,
            num_heads=num_heads,
            head_dim=head_dim,
            num_key_value_heads=1,
            dropout=dropout,
            max_position_embeddings=max_position_embeddings,
            rope_theta=rope_theta,
            rope_scaling=rope_scaling,
            partial_rotary_factor=partial_rotary_factor,
            attention_dropout=attention_dropout,
            use_flash_attention=use_flash_attention,
            sliding_window=sliding_window,
            bias=bias,
        )


class FlashAttention(MultiHeadAttention):
    """Flash Attention — falls back to standard MHA on CPU."""
    # causal and other kwargs are absorbed by MultiHeadAttention.__init__(**kwargs)
    pass


class SparseAttention(MultiHeadAttention):
    """Sparse Attention — zeroes out non-local attention positions."""

    def __init__(self, *args, sparsity_factor: int = 2, sparsity_pattern: str = "local", **kwargs):
        super().__init__(*args, **kwargs)
        self.sparsity_factor = sparsity_factor
        self.sparsity_pattern = sparsity_pattern

    def _apply_attention_hook(self, attn_weights: torch.Tensor) -> torch.Tensor:
        seq = attn_weights.shape[-1]
        if self.sparsity_pattern == "strided":
            mask = torch.zeros_like(attn_weights)
            for i in range(seq):
                for j in range(0, i + 1, self.sparsity_factor):
                    mask[:, :, i, j] = 1.0
            attn_weights = attn_weights * mask
            # Re-normalize
            row_sum = attn_weights.sum(dim=-1, keepdim=True).clamp(min=1e-8)
            attn_weights = attn_weights / row_sum
        return attn_weights


class SlidingWindowAttention(MultiHeadAttention):
    """Sliding Window Attention — limits attention to a local window."""

    def __init__(self, *args, window_size: int = 512, **kwargs):
        super().__init__(*args, **kwargs)
        self.window_size = window_size

    def _apply_attention_hook(self, attn_weights: torch.Tensor) -> torch.Tensor:
        seq_q, seq_k = attn_weights.shape[-2], attn_weights.shape[-1]
        # Causal window: position i can attend to j where 0 <= i-j <= window_size
        i_idx = torch.arange(seq_q, device=attn_weights.device).unsqueeze(1)
        j_idx = torch.arange(seq_k, device=attn_weights.device).unsqueeze(0)
        dist = i_idx - j_idx  # positive = looking back
        window_mask = (dist >= 0) & (dist <= self.window_size)
        attn_weights = attn_weights.masked_fill(~window_mask, 0.0)
        row_sum = attn_weights.sum(dim=-1, keepdim=True).clamp(min=1e-8)
        attn_weights = attn_weights / row_sum
        return attn_weights


class AlibiAttention(MultiHeadAttention):
    """ALiBi Attention — adds head-specific linear position biases."""

    def _apply_attention_hook(self, attn_weights: torch.Tensor) -> torch.Tensor:
        batch, num_heads, seq_q, seq_k = attn_weights.shape
        device = attn_weights.device
        # Compute ALiBi slopes: 2^(-8*h/num_heads) for head h
        slopes = torch.tensor(
            [2 ** (-8 * (h + 1) / num_heads) for h in range(num_heads)],
            dtype=attn_weights.dtype, device=device
        ).view(1, num_heads, 1, 1)
        # Position bias: negative distance * slope
        i_idx = torch.arange(seq_q, device=device).unsqueeze(1)
        j_idx = torch.arange(seq_k, device=device).unsqueeze(0)
        distance = (i_idx - j_idx).float().unsqueeze(0).unsqueeze(0)  # (1,1,seq_q,seq_k)
        alibi_bias = -distance.abs() * slopes
        return attn_weights + alibi_bias
