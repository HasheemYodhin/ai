"""
Optimization module for the dabba framework.

Provides memory and compute optimization techniques for transformer
models, including gradient checkpointing, activation recomputation,
KV cache optimization, and model quantization.

Components:
    GradientCheckpointing     : Selective layer checkpointing for
                                memory-efficient training.
    ActivationRecomputation   : Recompute activations during backward
                                with configurable policies.
    KVCacheOptimizer          : PagedAttention-style block management
                                with eviction policies and quantization.
    Quantizer                 : Weight quantization (INT4/INT8/FP4) with
                                evaluation and speed measurement.
"""

from dabba.optimization.gradient_checkpointing import GradientCheckpointing
from dabba.optimization.activation_recomputation import ActivationRecomputation
from dabba.optimization.kv_cache_opt import KVCacheOptimizer
from dabba.optimization.quantization import Quantizer

__all__ = [
    "GradientCheckpointing",
    "ActivationRecomputation",
    "KVCacheOptimizer",
    "Quantizer",
]
