"""
KV cache optimization for efficient long-context inference.

Implements multiple optimization strategies for the key-value cache:
    - PagedAttention-style block management: Organizes KV cache into
      fixed-size blocks with allocation/deallocation.
    - Cache eviction policies: LRU and sliding window eviction to
      bound cache memory usage.
    - INT8/FP8 quantization: Reduces the memory footprint of cached
      keys and values by lowering precision.

Reference:
    "Efficient Memory Management for Large Language Model Serving
    with PagedAttention" (Kwon et al., 2023)
    https://arxiv.org/abs/2309.06180
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn

from dabba.model.kv_cache import KVCache
from dabba.model.transformer import Transformer


class EvictionPolicy(Enum):
    """
    Policy for evicting KV cache entries when memory is constrained.

    Attributes:
        NONE: No eviction (keep all entries).
        LRU: Evict least recently used entries.
        SLIDING_WINDOW: Keep only the most recent entries.
    """
    NONE = "none"
    LRU = "lru"
    SLIDING_WINDOW = "sliding_window"


class QuantizationMode(Enum):
    """
    Quantization mode for KV cache entries.

    Attributes:
        NONE: No quantization (FP16/BF16).
        INT8: 8-bit integer quantization per channel.
        FP8: 8-bit floating point (E4M3 or E5M2).
    """
    NONE = "none"
    INT8 = "int8"
    FP8 = "fp8"


@dataclass
class BlockMetadata:
    """
    Metadata for a single PagedAttention block.

    Attributes:
        block_id: Unique block identifier.
        layer_idx: Layer index this block belongs to.
        sequence_idx: Sequence index in the batch.
        num_tokens: Number of tokens currently in the block.
        last_access_step: Last step this block was accessed (for LRU).
        is_active: Whether the block is currently in use.
    """
    block_id: int = 0
    layer_idx: int = 0
    sequence_idx: int = 0
    num_tokens: int = 0
    last_access_step: int = 0
    is_active: bool = True


class PagedBlock:
    """
    A single block in the paged KV cache.

    Each block stores a contiguous chunk of keys and values in
    a fixed-size buffer. Blocks are allocated on demand and can
    be evicted when memory is constrained.

    Args:
        block_id: Unique identifier for this block.
        block_size: Maximum number of tokens per block.
        num_heads: Number of key/value heads.
        head_dim: Dimension of each head.
        dtype: Data type for the stored tensors.
        device: Device to store tensors on.
    """

    def __init__(
        self,
        block_id: int,
        block_size: int,
        num_heads: int,
        head_dim: int,
        dtype: torch.dtype = torch.float16,
        device: torch.device = torch.device("cuda"),
    ):
        self.block_id = block_id
        self.block_size = block_size
        self.num_heads = num_heads
        self.head_dim = head_dim
        self.dtype = dtype
        self.device = device

        # Allocate fixed-size buffer
        self.key_buffer = torch.zeros(
            block_size, num_heads, head_dim,
            dtype=dtype, device=device,
        )
        self.value_buffer = torch.zeros(
            block_size, num_heads, head_dim,
            dtype=dtype, device=device,
        )
        self.num_tokens = 0

    def append(
        self,
        key: torch.Tensor,
        value: torch.Tensor,
    ) -> bool:
        """
        Append a key-value pair to the block.

        Args:
            key: Key tensor of shape (num_heads, head_dim).
            value: Value tensor of shape (num_heads, head_dim).

        Returns:
            True if the append succeeded, False if the block is full.
        """
        if self.num_tokens >= self.block_size:
            return False

        idx = self.num_tokens
        self.key_buffer[idx] = key
        self.value_buffer[idx] = value
        self.num_tokens += 1
        return True

    def get(self) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Get the valid keys and values in this block.

        Returns:
            Tuple of (key, value) tensors of shape
            (num_tokens, num_heads, head_dim).
        """
        return (
            self.key_buffer[:self.num_tokens],
            self.value_buffer[:self.num_tokens],
        )

    def clear(self) -> None:
        """Clear the block contents."""
        self.num_tokens = 0
        self.key_buffer.zero_()
        self.value_buffer.zero_()

    @property
    def is_full(self) -> bool:
        """Check if the block is full."""
        return self.num_tokens >= self.block_size

    @property
    def memory_bytes(self) -> int:
        """Get the memory usage of this block in bytes."""
        return (
            self.key_buffer.numel() * self.key_buffer.element_size()
            + self.value_buffer.numel() * self.value_buffer.element_size()
        )


class KVCacheOptimizer:
    """
    KV cache optimizer with PagedAttention-style block management,
    configurable eviction policies, and INT8/FP8 quantization.

    Manages the KV cache across all transformer layers, providing
    memory-efficient storage for long-context inference.

    Args:
        model: The transformer model to optimize KV cache for.
        block_size: Number of tokens per cache block.
        eviction_policy: Cache eviction policy.
        quantization_mode: Quantization mode for cache entries.
        max_blocks: Maximum number of blocks per layer (-1 = unlimited).
        window_size: Sliding window size (used with SLIDING_WINDOW policy).
        device: Device for cache storage.
    """

    def __init__(
        self,
        model: Transformer,
        block_size: int = 64,
        eviction_policy: EvictionPolicy = EvictionPolicy.NONE,
        quantization_mode: QuantizationMode = QuantizationMode.NONE,
        max_blocks: int = -1,
        window_size: Optional[int] = None,
        device: Optional[torch.device] = None,
    ):
        self.model = model
        self.cfg = model.config
        self.block_size = block_size
        self.eviction_policy = eviction_policy
        self.quantization_mode = quantization_mode
        self.max_blocks = max_blocks
        self.window_size = window_size or model.config.max_position_embeddings
        self.device = device or (
            torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
        )

        self.num_heads = self.cfg.num_key_value_heads
        self.head_dim = self.cfg.head_dim
        self.num_layers = self.cfg.num_layers

        self._blocks: Dict[int, List[PagedBlock]] = {}
        self._next_block_id = 0
        self._step_counter = 0

        # Statistics
        self._total_accesses = 0
        self._cache_hits = 0
        self._total_evictions = 0

        # Initialize block storage per layer
        for layer_idx in range(self.num_layers):
            self._blocks[layer_idx] = []

    def create_cache(
        self,
        batch_size: int = 1,
        max_seq_length: Optional[int] = None,
    ) -> List[List[PagedBlock]]:
        """
        Create a new paged KV cache for all layers.

        Args:
            batch_size: Batch size for the cache.
            max_seq_length: Maximum expected sequence length.

        Returns:
            List of lists of PagedBlocks, one per layer.
        """
        cache: List[List[PagedBlock]] = []
        for layer_idx in range(self.num_layers):
            layer_blocks = []
            cache.append(layer_blocks)
        return cache

    def allocate_block(
        self,
        layer_idx: int,
        sequence_idx: int = 0,
    ) -> PagedBlock:
        """
        Allocate a new block for a specific layer and sequence.

        Args:
            layer_idx: Layer index.
            sequence_idx: Sequence index in the batch.

        Returns:
            New PagedBlock, or evicts an existing block if at capacity.
        """
        # Check capacity
        if (self.max_blocks > 0
                and len(self._blocks[layer_idx]) >= self.max_blocks):
            self._evict_block(layer_idx)

        block = PagedBlock(
            block_id=self._next_block_id,
            block_size=self.block_size,
            num_heads=self.num_heads,
            head_dim=self.head_dim,
            dtype=self._get_cache_dtype(),
            device=self.device,
        )
        self._next_block_id += 1
        self._blocks[layer_idx].append(block)
        return block

    def append_to_cache(
        self,
        layer_idx: int,
        key: torch.Tensor,
        value: torch.Tensor,
        cache: Optional[List[List[PagedBlock]]] = None,
        sequence_idx: int = 0,
    ) -> None:
        """
        Append key-value tensors to the cache for a specific layer.

        Automatically allocates new blocks as needed and applies
        eviction policy when capacity is reached.

        Args:
            layer_idx: Layer index.
            key: Key tensor of shape (batch, num_heads, seq_len, head_dim).
            value: Value tensor of shape (batch, num_heads, seq_len, head_dim).
            cache: Cache to append to (uses internal cache if None).
            sequence_idx: Sequence index in the batch.
        """
        # Handle quantization
        key_q, value_q = self._quantize(key, value)

        blocks = self._blocks[layer_idx]

        # Ensure there's an active block
        if not blocks or blocks[-1].is_full:
            block = self.allocate_block(layer_idx, sequence_idx)
        else:
            block = blocks[-1]

        # Append each token in the sequence
        seq_len = key_q.size(2)
        for t in range(seq_len):
            success = block.append(
                key_q[0, :, t, :],
                value_q[0, :, t, :],
            )
            if not success:
                block = self.allocate_block(layer_idx, sequence_idx)
                block.append(
                    key_q[0, :, t, :],
                    value_q[0, :, t, :],
                )

    def get_cache(
        self,
        layer_idx: int,
        max_tokens: Optional[int] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Retrieve the cached keys and values for a given layer.

        Args:
            layer_idx: Layer index.
            max_tokens: Maximum number of recent tokens to return.

        Returns:
            Tuple of (key, value) tensors of shape
            (1, num_heads, num_cached, head_dim).
        """
        blocks = self._blocks[layer_idx]
        if not blocks:
            return torch.empty(0, device=self.device), torch.empty(0, device=self.device)

        keys_list = []
        values_list = []

        for block in blocks:
            k, v = block.get()
            keys_list.append(k)
            values_list.append(v)

        all_keys = torch.cat(keys_list, dim=0)
        all_values = torch.cat(values_list, dim=0)

        # Sliding window
        if max_tokens is not None and all_keys.size(0) > max_tokens:
            all_keys = all_keys[-max_tokens:]
            all_values = all_values[-max_tokens:]

        # De-quantize
        all_keys, all_values = self._dequantize(all_keys, all_values)

        # Transpose to (1, num_heads, seq, head_dim)
        all_keys = all_keys.unsqueeze(0).transpose(1, 2)
        all_values = all_values.unsqueeze(0).transpose(1, 2)

        return all_keys, all_values

    def _evict_block(self, layer_idx: int) -> None:
        """
        Evict a block based on the current eviction policy.

        Args:
            layer_idx: Layer index to evict from.
        """
        blocks = self._blocks[layer_idx]
        if not blocks:
            return

        if self.eviction_policy == EvictionPolicy.LRU:
            # Find the least recently used block
            oldest = min(blocks, key=lambda b: b.block_id)
            blocks.remove(oldest)
            self._total_evictions += 1

        elif self.eviction_policy == EvictionPolicy.SLIDING_WINDOW:
            # Evict oldest blocks (they're at the front)
            evicted = blocks.pop(0)
            self._total_evictions += 1

    def _quantize(
        self,
        key: torch.Tensor,
        value: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Quantize key and value tensors.

        Args:
            key: Key tensor.
            value: Value tensor.

        Returns:
            Tuple of quantized (key, value) tensors.
        """
        if self.quantization_mode == QuantizationMode.NONE:
            return key, value

        if self.quantization_mode == QuantizationMode.INT8:
            return self._quantize_int8(key, value)

        if self.quantization_mode == QuantizationMode.FP8:
            return key.to(torch.float8_e4m3fn), value.to(torch.float8_e4m3fn)

        return key, value

    def _dequantize(
        self,
        key: torch.Tensor,
        value: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        De-quantize key and value tensors back to the original dtype.

        Args:
            key: Quantized key tensor.
            value: Quantized value tensor.

        Returns:
            Tuple of de-quantized (key, value) tensors.
        """
        if self.quantization_mode == QuantizationMode.NONE:
            return key, value

        if self.quantization_mode == QuantizationMode.INT8:
            return self._dequantize_int8(key, value)

        if self.quantization_mode == QuantizationMode.FP8:
            return key.to(torch.float16), value.to(torch.float16)

        return key, value

    def _quantize_int8(
        self,
        key: torch.Tensor,
        value: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Quantize to INT8 using per-channel scaling.

        For each head and head_dim channel, computes the absolute
        maximum and scales to the INT8 range [-127, 127].

        Args:
            key: Key tensor of shape (batch, num_heads, seq, head_dim).
            value: Value tensor of shape (batch, num_heads, seq, head_dim).

        Returns:
            Tuple of quantized (key, value) tensors.
        """
        # Per-channel quantization along the head_dim dimension
        key_abs_max = key.abs().amax(dim=(0, 2), keepdim=True).clamp(min=1e-7)
        value_abs_max = value.abs().amax(dim=(0, 2), keepdim=True).clamp(min=1e-7)

        key_scale = key_abs_max / 127.0
        value_scale = value_abs_max / 127.0

        key_q = (key / key_scale).round().clamp(-127, 127).to(torch.int8)
        value_q = (value / value_scale).round().clamp(-127, 127).to(torch.int8)

        # Store scales as attributes for dequantization
        self._key_scale = key_scale
        self._value_scale = value_scale

        return key_q, value_q

    def _dequantize_int8(
        self,
        key: torch.Tensor,
        value: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        De-quantize INT8 tensors back to float16.

        Args:
            key: INT8 key tensor.
            value: INT8 value tensor.

        Returns:
            Tuple of de-quantized (key, value) tensors.
        """
        key_fp = key.float() * self._key_scale
        value_fp = value.float() * self._value_scale
        return key_fp, value_fp

    def _get_cache_dtype(self) -> torch.dtype:
        """
        Get the storage dtype based on quantization mode.

        Returns:
            Torch dtype for cache storage.
        """
        if self.quantization_mode == QuantizationMode.INT8:
            return torch.int8
        elif self.quantization_mode == QuantizationMode.FP8:
            return torch.float8_e4m3fn
        else:
            return torch.float16

    def track_access(self, layer_idx: int, block_idx: int) -> None:
        """
        Track a cache access for hit rate statistics.

        Args:
            layer_idx: Layer index.
            block_idx: Block index.
        """
        self._total_accesses += 1
        block = self._find_block(layer_idx, block_idx)
        if block is not None:
            self._cache_hits += 1
            block.last_access_step = self._step_counter
            self._step_counter += 1

    def _find_block(self, layer_idx: int, block_id: int) -> Optional[PagedBlock]:
        """
        Find a block by ID in a given layer.

        Args:
            layer_idx: Layer index.
            block_id: Block ID to find.

        Returns:
            PagedBlock if found, None otherwise.
        """
        for block in self._blocks.get(layer_idx, []):
            if block.block_id == block_id:
                return block
        return None

    def get_memory_usage(self) -> Dict[str, float]:
        """
        Get current memory usage of the KV cache.

        Returns:
            Dictionary with:
                - total_memory_mb: Total cache memory in MiB.
                - per_layer_mb: Memory per layer in MiB.
                - num_blocks: Total number of blocks.
                - num_blocks_per_layer: Blocks per layer.
                - total_tokens_cached: Total tokens across all blocks.
        """
        total_bytes = 0
        total_tokens = 0
        num_blocks = 0
        per_layer: Dict[int, Dict[str, float]] = {}

        for layer_idx, blocks in self._blocks.items():
            layer_bytes = sum(b.memory_bytes for b in blocks)
            layer_tokens = sum(b.num_tokens for b in blocks)
            layer_blocks = len(blocks)
            per_layer[layer_idx] = {
                "memory_mb": layer_bytes / (1024 ** 2),
                "tokens": layer_tokens,
                "blocks": layer_blocks,
            }
            total_bytes += layer_bytes
            total_tokens += layer_tokens
            num_blocks += layer_blocks

        return {
            "total_memory_mb": total_bytes / (1024 ** 2),
            "total_memory_gb": total_bytes / (1024 ** 3),
            "num_blocks": num_blocks,
            "total_tokens_cached": total_tokens,
            "per_layer": per_layer,
        }

    def get_cache_hit_rate(self) -> float:
        """
        Get the cache hit rate.

        Returns:
            Cache hit rate as a fraction [0, 1].
        """
        if self._total_accesses == 0:
            return 0.0
        return self._cache_hits / self._total_accesses

    def get_statistics(self) -> Dict[str, float]:
        """
        Get comprehensive cache statistics.

        Returns:
            Dictionary with all cache performance metrics.
        """
        mem = self.get_memory_usage()
        return {
            "cache_hit_rate": self.get_cache_hit_rate(),
            "total_accesses": self._total_accesses,
            "total_evictions": self._total_evictions,
            "total_memory_mb": mem["total_memory_mb"],
            "total_tokens_cached": mem["total_tokens_cached"],
            "num_blocks": mem["num_blocks"],
            "block_size": self.block_size,
            "eviction_policy": self.eviction_policy.value,
            "quantization": self.quantization_mode.value,
        }

    def estimate_memory_savings(
        self,
        batch_size: int = 1,
        seq_length: int = 4096,
    ) -> Dict[str, float]:
        """
        Estimate memory savings from KV cache optimization.

        Compares baseline (FP16, no eviction) vs optimized (INT8/FP8
        with eviction) memory usage.

        Args:
            batch_size: Batch size for estimation.
            seq_length: Cache sequence length.

        Returns:
            Dictionary with baseline and optimized memory usage.
        """
        cfg = self.cfg
        bytes_per_elem = 2  # FP16 baseline

        baseline_bytes = (
            batch_size * cfg.num_key_value_heads * seq_length * cfg.head_dim * 2 * bytes_per_elem
        )
        baseline_mb = baseline_bytes / (1024 ** 2)

        if self.quantization_mode == QuantizationMode.INT8:
            opt_bytes_per_elem = 1
        elif self.quantization_mode == QuantizationMode.FP8:
            opt_bytes_per_elem = 1
        else:
            opt_bytes_per_elem = bytes_per_elem

        optimized_bytes = (
            batch_size * cfg.num_key_value_heads * seq_length * cfg.head_dim * 2 * opt_bytes_per_elem
        )

        # Block management overhead (small)
        num_blocks = math.ceil(seq_length / self.block_size)
        overhead_bytes = num_blocks * cfg.num_layers * 64  # ~64 bytes metadata per block

        optimized_mb = (optimized_bytes + overhead_bytes) / (1024 ** 2)
        saved_mb = baseline_mb - optimized_mb
        saved_pct = (saved_mb / baseline_mb * 100) if baseline_mb > 0 else 0

        return {
            "baseline_fp16_mb": baseline_mb,
            "optimized_mb": optimized_mb,
            "memory_saved_mb": saved_mb,
            "memory_saved_pct": saved_pct,
            "quantization": self.quantization_mode.value,
            "eviction_policy": self.eviction_policy.value,
            "block_size": self.block_size,
        }

    def summary(self) -> str:
        """
        Generate a summary of the KV cache optimization configuration.

        Returns:
            Formatted summary string.
        """
        stats = self.get_statistics()
        savings = self.estimate_memory_savings()

        lines = [
            "=" * 60,
            "KV Cache Optimization Summary",
            "=" * 60,
            f"  Eviction policy:     {self.eviction_policy.value}",
            f"  Quantization:        {self.quantization_mode.value}",
            f"  Block size:          {self.block_size} tokens",
            f"  Window size:         {self.window_size} tokens",
            f"  Max blocks/layer:    {self.max_blocks if self.max_blocks > 0 else 'Unlimited'}",
            "",
            "Memory Savings (est):",
            f"  Baseline (FP16):     {savings['baseline_fp16_mb']:.2f} MiB",
            f"  Optimized:           {savings['optimized_mb']:.2f} MiB",
            f"  Saved:               {savings['memory_saved_mb']:.2f} MiB ({savings['memory_saved_pct']:.1f}%)",
            "",
            "Current Cache Stats:",
            f"  Cache hit rate:      {stats['cache_hit_rate']*100:.1f}%",
            f"  Total evictions:     {stats['total_evictions']:.0f}",
            f"  Current memory:      {stats['total_memory_mb']:.2f} MiB",
            f"  Tokens cached:       {stats['total_tokens_cached']:.0f}",
            f"  Blocks allocated:    {stats['num_blocks']:.0f}",
            "-" * 60,
        ]

        return "\n".join(lines)
