"""
Single decoder block for the transformer language model.

Each decoder block consists of:
    1. Pre-normalization (RMSNorm)
    2. Self-attention (MHA/GQA/MQA)
    3. Residual connection
    4. Post-normalization (RMSNorm)
    5. Feed-forward network (SwiGLU/GELU)
    6. Residual connection

Supports both pre-norm (default) and post-norm architectures.
"""

from typing import Optional, Tuple

import torch
import torch.nn as nn

from dabba.model.normalizations import RMSNorm, LayerNorm
from dabba.model.attention import MultiHeadAttention, GroupedQueryAttention
from dabba.model.feed_forward import FeedForward
from dabba.model.kv_cache import KVCache


class DecoderBlock(nn.Module):
    """
    Transformer decoder block with pre/post-normalization.

    Architecture (pre-norm, default):
        x = x + attention(norm(x))
        x = x + ffn(norm(x))

    Architecture (post-norm):
        x = norm(x + attention(x))
        x = norm(x + ffn(x))

    Args:
        hidden_size: Dimensionality of the model.
        num_attention_heads: Number of attention heads.
        num_key_value_heads: Number of key/value heads (GQA).
        head_dim: Dimensionality of each attention head.
        intermediate_size: Hidden dimensionality of the FFN.
        hidden_act: Activation function ("silu" or "gelu").
        rms_norm_eps: Epsilon for RMS normalization.
        use_rms_norm: Use RMSNorm if True, LayerNorm if False.
        pre_norm: Use pre-normalization if True.
        max_position_embeddings: Maximum sequence length.
        rope_theta: RoPE frequency base.
        rope_scaling: RoPE scaling configuration.
        partial_rotary_factor: Fraction of head dims to rotate.
        attention_dropout: Dropout for attention weights.
        embedding_dropout: Dropout for embeddings.
        ffn_dropout: Dropout for the feed-forward network.
        use_flash_attention: Use Flash Attention if available.
        sliding_window: Sliding window attention size.
        bias: Use bias in linear projections.
        layer_idx: Index of this layer in the model.
    """

    def __init__(
        self,
        hidden_size: int,
        num_attention_heads: int,
        num_key_value_heads: Optional[int] = None,
        head_dim: Optional[int] = None,
        intermediate_size: Optional[int] = None,
        hidden_act: str = "silu",
        rms_norm_eps: float = 1e-6,
        use_rms_norm: bool = True,
        pre_norm: bool = True,
        max_position_embeddings: int = 2048,
        rope_theta: float = 10000.0,
        rope_scaling: Optional[dict] = None,
        partial_rotary_factor: float = 1.0,
        attention_dropout: float = 0.0,
        ffn_dropout: float = 0.0,
        use_flash_attention: bool = False,
        sliding_window: Optional[int] = None,
        bias: bool = False,
        layer_idx: Optional[int] = None,
    ):
        super().__init__()
        self.layer_idx = layer_idx
        self.pre_norm = pre_norm

        NormClass = RMSNorm if use_rms_norm else LayerNorm
        self.input_layernorm = NormClass(hidden_size, eps=rms_norm_eps)
        self.post_attention_layernorm = NormClass(hidden_size, eps=rms_norm_eps)

        self.self_attn = self._build_attention(
            hidden_size=hidden_size,
            num_heads=num_attention_heads,
            num_key_value_heads=num_key_value_heads or num_attention_heads,
            head_dim=head_dim,
            dropout=attention_dropout,
            max_position_embeddings=max_position_embeddings,
            rope_theta=rope_theta,
            rope_scaling=rope_scaling,
            partial_rotary_factor=partial_rotary_factor,
            use_flash_attention=use_flash_attention,
            sliding_window=sliding_window,
            bias=bias,
        )

        self.feed_forward = FeedForward(
            hidden_size=hidden_size,
            intermediate_size=intermediate_size or int(hidden_size * 8 / 3),
            activation=hidden_act,
            dropout=ffn_dropout,
        )

    def _build_attention(self, **kwargs) -> nn.Module:
        """
        Build the appropriate attention module based on configuration.

        Uses GQA when num_key_value_heads differs from num_heads,
        otherwise uses standard MHA.

        Args:
            **kwargs: Attention module parameters.

        Returns:
            Attention module instance.
        """
        num_heads = kwargs.pop("num_heads")
        num_kv_heads = kwargs.pop("num_key_value_heads")

        if num_kv_heads != num_heads:
            return GroupedQueryAttention(
                num_heads=num_heads,
                num_key_value_heads=num_kv_heads,
                **kwargs,
            )
        else:
            return MultiHeadAttention(
                num_heads=num_heads,
                num_key_value_heads=num_kv_heads,
                **kwargs,
            )

    def forward(
        self,
        hidden_states: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.Tensor] = None,
        past_key_value: Optional[KVCache] = None,
        use_cache: bool = False,
        output_attentions: bool = False,
    ) -> Tuple[torch.Tensor, Optional[KVCache]]:
        """
        Forward pass for the decoder block.

        Args:
            hidden_states: Input of shape (batch_size, seq_length, hidden_size).
            attention_mask: Optional attention mask.
            position_ids: Position IDs for RoPE.
            past_key_value: Optional KV cache.
            use_cache: If True, return updated KV cache.
            output_attentions: If True, return attention weights.

        Returns:
            Tuple of (output_hidden_states, kv_cache).
        """
        residual = hidden_states

        if self.pre_norm:
            hidden_states = self.input_layernorm(hidden_states)

        attn_output, attn_weights, kv_cache = self.self_attn(
            hidden_states=hidden_states,
            attention_mask=attention_mask,
            position_ids=position_ids,
            past_key_value=past_key_value,
            use_cache=use_cache,
            output_attentions=output_attentions,
        )

        hidden_states = residual + attn_output

        residual = hidden_states

        if self.pre_norm:
            hidden_states = self.post_attention_layernorm(hidden_states)

        ffn_output = self.feed_forward(hidden_states)
        hidden_states = residual + ffn_output

        if not self.pre_norm:
            hidden_states = self.input_layernorm(hidden_states)

        return hidden_states, kv_cache
