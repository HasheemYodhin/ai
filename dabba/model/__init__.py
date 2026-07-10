"""
Decoder-only transformer model implementation from scratch.

Contains all building blocks: embeddings, normalizations, attention
mechanisms (MHA, GQA, MQA), feed-forward networks (SwiGLU, GELU),
decoder blocks, the full transformer stack, KV cache, and output head.
"""

from dabba.model.embedding import TokenEmbedding, RotaryEmbedding, apply_rotary_pos_emb
from dabba.model.normalizations import RMSNorm, LayerNorm
from dabba.model.attention import (
    MultiHeadAttention, GroupedQueryAttention, MultiQueryAttention,
    FlashAttention, SparseAttention, SlidingWindowAttention, AlibiAttention,
)
from dabba.model.feed_forward import FeedForward, SwiGLU, GELU
from dabba.model.decoder_block import DecoderBlock
from dabba.model.transformer import Transformer
from dabba.model.kv_cache import KVCache
from dabba.model.output_head import OutputHead

__all__ = [
    "TokenEmbedding",
    "RotaryEmbedding",
    "apply_rotary_pos_emb",
    "RMSNorm",
    "LayerNorm",
    "MultiHeadAttention",
    "GroupedQueryAttention",
    "MultiQueryAttention",
    "FlashAttention",
    "SparseAttention",
    "SlidingWindowAttention",
    "AlibiAttention",
    "FeedForward",
    "SwiGLU",
    "GELU",
    "DecoderBlock",
    "Transformer",
    "KVCache",
    "OutputHead",
]
