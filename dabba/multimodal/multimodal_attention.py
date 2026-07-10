"""
Cross-attention module for fusing vision features with text features.

Implements decoder-style cross-attention where queries come from the
text modality and key/value pairs come from the vision modality,
enabling the language model to attend to visual information during
generation.
"""

import logging
import math
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class MultimodalCrossAttention(nn.Module):
    """
    Cross-attends text features (queries) with vision features (keys/values).

    This module implements a standard cross-attention block commonly
    inserted between self-attention and feed-forward in multimodal
    decoder layers. The query projection operates on text hidden
    states while the key and value projections operate on vision
    encoder outputs (or projected vision tokens).

    Supports:
      - Multiple vision tokens per image
      - Configurable number of attention heads
      - Dropout on attention weights
      - Optional pre-normalisation (LayerNorm before projections)
      - Residual connection and post-norm

    Args:
        hidden_size: Text/LLM hidden dimension (also output dimension).
        vision_size: Vision feature dimension (may differ from hidden_size
                     if no projection is applied). Default same as hidden_size.
        num_heads: Number of attention heads. Default 8.
        head_dim: Dimension per head. If None, computed as hidden_size // num_heads.
        dropout: Dropout probability for attention weights. Default 0.1.
        bias: Include bias in Q/K/V/O projections. Default False.
        pre_norm: Apply LayerNorm before projections. Default True.
        post_norm: Apply LayerNorm after residual addition. Default False.
    """

    def __init__(
        self,
        hidden_size: int = 768,
        vision_size: Optional[int] = None,
        num_heads: int = 8,
        head_dim: Optional[int] = None,
        dropout: float = 0.1,
        bias: bool = False,
        pre_norm: bool = True,
        post_norm: bool = False,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.vision_size = vision_size if vision_size is not None else hidden_size
        self.num_heads = num_heads
        self.head_dim = head_dim if head_dim is not None else hidden_size // num_heads
        self.dropout = dropout
        self.pre_norm = pre_norm
        self.post_norm = post_norm

        assert self.hidden_size % self.num_heads == 0, (
            f"hidden_size ({hidden_size}) must be divisible by "
            f"num_heads ({num_heads})"
        )

        self.q_proj = nn.Linear(hidden_size, num_heads * self.head_dim, bias=bias)
        self.k_proj = nn.Linear(self.vision_size, num_heads * self.head_dim, bias=bias)
        self.v_proj = nn.Linear(self.vision_size, num_heads * self.head_dim, bias=bias)
        self.o_proj = nn.Linear(num_heads * self.head_dim, hidden_size, bias=bias)

        self.attn_dropout = nn.Dropout(dropout)

        if pre_norm:
            self.q_norm = nn.LayerNorm(hidden_size)
            self.kv_norm = nn.LayerNorm(self.vision_size)
        else:
            self.q_norm = nn.Identity()
            self.kv_norm = nn.Identity()

        if post_norm:
            self.out_norm = nn.LayerNorm(hidden_size)
        else:
            self.out_norm = nn.Identity()

        self._init_weights()

    def _init_weights(self):
        """Initialise linear projections."""
        for proj in (self.q_proj, self.k_proj, self.v_proj, self.o_proj):
            nn.init.normal_(proj.weight, mean=0.0, std=0.02)
            if proj.bias is not None:
                nn.init.zeros_(proj.bias)

    def forward(
        self,
        hidden_states: torch.Tensor,
        vision_tokens: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        output_attentions: bool = False,
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Cross-attend text hidden states with vision tokens.

        Args:
            hidden_states: Text hidden states, shape (batch_size, text_len, hidden_size).
                          These provide the Q projection.
            vision_tokens: Vision token embeddings, shape
                          (batch_size, num_vision_tokens, vision_size).
                          These provide the K and V projections.
            attention_mask: Optional attention mask of shape
                           (batch_size, 1, text_len, num_vision_tokens).
                           Typically a padding mask for variable-length
                           vision token sequences.
            output_attentions: If True, return attention weights.

        Returns:
            Tuple of (output_hidden_states, attention_weights).
            Output shape: (batch_size, text_len, hidden_size).
        """
        batch_size, text_len, _ = hidden_states.shape
        _, num_vision_tokens, _ = vision_tokens.shape

        q = self.q_norm(hidden_states)
        kv = self.kv_norm(vision_tokens)

        q = self.q_proj(q)
        k = self.k_proj(kv)
        v = self.v_proj(kv)

        q = q.view(batch_size, text_len, self.num_heads, self.head_dim).transpose(1, 2)
        k = k.view(batch_size, num_vision_tokens, self.num_heads, self.head_dim).transpose(1, 2)
        v = v.view(batch_size, num_vision_tokens, self.num_heads, self.head_dim).transpose(1, 2)

        attn_weights = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)

        if attention_mask is not None:
            attn_weights = attn_weights + attention_mask

        attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(q.dtype)
        attn_weights = self.attn_dropout(attn_weights)

        attn_output = torch.matmul(attn_weights, v)
        attn_output = attn_output.transpose(1, 2).contiguous()
        attn_output = attn_output.reshape(batch_size, text_len, self.num_heads * self.head_dim)
        attn_output = self.o_proj(attn_output)

        output = self.out_norm(hidden_states + attn_output)

        if output_attentions:
            return output, attn_weights
        return output, None

    def extra_repr(self) -> str:
        return (
            f"hidden_size={self.hidden_size}, "
            f"vision_size={self.vision_size}, "
            f"num_heads={self.num_heads}, "
            f"head_dim={self.head_dim}, "
            f"dropout={self.dropout}"
        )
