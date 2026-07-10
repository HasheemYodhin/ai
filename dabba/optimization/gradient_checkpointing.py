"""
Gradient checkpointing (activation checkpointing) for memory-efficient
transformer training.

Selectively checkpoints activations during the forward pass for specific
layers, recomputing them during the backward pass. This trades compute
for memory, reducing the peak memory usage by only storing the inputs
to checkpointed segments rather than all intermediate activations.

Reference:
    "Training Deep Nets with Sublinear Memory Cost" (Chen et al., 2016)
    https://arxiv.org/abs/1604.06174
"""

import math
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

import torch
import torch.nn as nn
from torch.utils.checkpoint import checkpoint

from dabba.model.transformer import Transformer
from dabba.model.decoder_block import DecoderBlock


class CheckpointPolicy(Enum):
    """
    Policy for selecting which layers to checkpoint.

    Attributes:
        NONE: No checkpointing (full activation storage).
        ALL: Checkpoint all decoder layers (max memory savings).
        EVEN: Checkpoint only even-indexed layers (balanced).
        ODD: Checkpoint only odd-indexed layers.
        FIRST_HALF: Checkpoint the first half of layers.
        LAST_HALF: Checkpoint the last half of layers.
        CUSTOM: Use a user-provided selection function.
    """
    NONE = "none"
    ALL = "all"
    EVEN = "even"
    ODD = "odd"
    FIRST_HALF = "first_half"
    LAST_HALF = "last_half"
    CUSTOM = "custom"


class GradientCheckpointing:
    """
    Gradient checkpointing manager for transformer models.

    Provides selective checkpointing of decoder layers, configurable
    memory vs compute trade-off, and benchmark helpers to quantify
    memory savings and runtime overhead.

    Args:
        model: The transformer model to apply checkpointing to.
        policy: Default checkpointing policy.
        num_checkpointed_layers: Number of layers to checkpoint
            (overrides policy when set).
        preserve_layer_list: Explicit list of layer indices to
            checkpoint (used with CUSTOM policy).
    """

    def __init__(
        self,
        model: Transformer,
        policy: CheckpointPolicy = CheckpointPolicy.ALL,
        num_checkpointed_layers: Optional[int] = None,
        preserve_layer_list: Optional[List[int]] = None,
    ):
        self.model = model
        self.num_layers = len(model.layers)
        self._original_forward = model.layers[0].forward if self.num_layers > 0 else None

        self._policy = policy
        self._num_checkpointed = num_checkpointed_layers
        self._preserve_layer_list = preserve_layer_list or []

        # Track original forward functions for restoration
        self._original_forwards: Dict[int, Callable] = {}

        # Apply initial policy
        self.apply_policy(policy)

    def apply_policy(
        self,
        policy: Optional[CheckpointPolicy] = None,
        num_layers: Optional[int] = None,
        layer_indices: Optional[List[int]] = None,
    ) -> None:
        """
        Apply a checkpointing policy to the model.

        Args:
            policy: CheckpointPolicy to apply. Uses stored policy if None.
            num_layers: Override number of layers to checkpoint.
            layer_indices: Explicit layer indices for CUSTOM policy.
        """
        if policy is not None:
            self._policy = policy
        if num_layers is not None:
            self._num_checkpointed = num_layers
        if layer_indices is not None:
            self._preserve_layer_list = layer_indices

        # Restore original forwards first
        self._restore_forwards()

        # Select layers to checkpoint
        indices = self._select_layers()

        # Patch selected layers with checkpointed forward
        for idx in indices:
            if idx < len(self.model.layers):
                layer = self.model.layers[idx]
                self._original_forwards[idx] = layer.forward
                layer.forward = self._make_checkpointed_forward(layer, idx)

        # Update model's gradient_checkpointing flag
        self.model.gradient_checkpointing = len(indices) > 0

    def enable(self) -> None:
        """Enable gradient checkpointing with the current policy."""
        self.apply_policy()

    def disable(self) -> None:
        """Disable all gradient checkpointing."""
        self._restore_forwards()
        self.model.gradient_checkpointing = False

    def _select_layers(self) -> List[int]:
        """
        Select layer indices based on the current policy.

        Returns:
            List of layer indices to checkpoint.
        """
        if self._policy == CheckpointPolicy.NONE:
            return []

        if self._policy == CheckpointPolicy.ALL:
            indices = list(range(self.num_layers))

        elif self._policy == CheckpointPolicy.EVEN:
            indices = [i for i in range(self.num_layers) if i % 2 == 0]

        elif self._policy == CheckpointPolicy.ODD:
            indices = [i for i in range(self.num_layers) if i % 2 == 1]

        elif self._policy == CheckpointPolicy.FIRST_HALF:
            indices = list(range(self.num_layers // 2))

        elif self._policy == CheckpointPolicy.LAST_HALF:
            indices = list(range(self.num_layers // 2, self.num_layers))

        elif self._policy == CheckpointPolicy.CUSTOM:
            indices = [i for i in self._preserve_layer_list if i < self.num_layers]

        else:
            indices = []

        # Apply count limit
        if self._num_checkpointed is not None and self._num_checkpointed < len(indices):
            if self._policy in (CheckpointPolicy.FIRST_HALF, CheckpointPolicy.EVEN):
                indices = indices[:self._num_checkpointed]
            elif self._policy in (CheckpointPolicy.LAST_HALF, CheckpointPolicy.ODD):
                indices = indices[-self._num_checkpointed:]
            else:
                indices = indices[:self._num_checkpointed]

        return indices

    def _make_checkpointed_forward(
        self,
        layer: DecoderBlock,
        layer_idx: int,
    ) -> Callable:
        """
        Create a checkpointed forward function for a decoder block.

        The checkpoint function saves only the input activations during
        the forward pass, then recomputes the layer during backward.

        Args:
            layer: The decoder block to checkpoint.
            layer_idx: Index of the layer in the model.

        Returns:
            Checkpointed forward function.
        """
        def checkpointed_forward(
            hidden_states: torch.Tensor,
            attention_mask: Optional[torch.Tensor] = None,
            position_ids: Optional[torch.Tensor] = None,
            past_key_value: Optional[object] = None,
            use_cache: bool = False,
            output_attentions: bool = False,
        ) -> Tuple[torch.Tensor, Optional[object]]:
            use_reentrant = False
            return checkpoint(
                layer._original_forward_wrapper,
                hidden_states,
                attention_mask,
                position_ids,
                use_reentrant,
            )
        # We'll use a simpler approach - patch directly
        return self._build_checkpoint_wrapper(layer)

    def _build_checkpoint_wrapper(self, layer: DecoderBlock) -> Callable:
        """
        Build a checkpoint wrapper using torch.utils.checkpoint.

        Args:
            layer: The decoder block to wrap.

        Returns:
            Wrapped forward function.
        """
        original_forward = self._original_forwards.get(
            id(layer),
            layer.forward,
        )

        def wrapped_forward(
            hidden_states: torch.Tensor,
            attention_mask: Optional[torch.Tensor] = None,
            position_ids: Optional[torch.Tensor] = None,
            past_key_value: Optional[object] = None,
            use_cache: bool = False,
            output_attentions: bool = False,
        ) -> Tuple[torch.Tensor, Optional[object]]:
            # Use non-reentrant checkpointing for better performance
            return checkpoint(
                original_forward,
                hidden_states,
                attention_mask,
                position_ids,
                past_key_value,
                use_cache,
                output_attentions,
                use_reentrant=False,
            )

        return wrapped_forward

    def _restore_forwards(self) -> None:
        """Restore all original forward functions."""
        for idx, forward_fn in self._original_forwards.items():
            if idx < len(self.model.layers):
                self.model.layers[idx].forward = forward_fn
        self._original_forwards.clear()

    def estimate_memory_savings(
        self,
        batch_size: int = 1,
        seq_length: int = 2048,
    ) -> Dict[str, float]:
        """
        Estimate memory savings from the current checkpointing policy.

        Uses model configuration to compute the reduction in activation
        memory.

        Args:
            batch_size: Batch size for estimation.
            seq_length: Sequence length for estimation.

        Returns:
            Dictionary with:
                - "baseline_mb": Activation memory without checkpointing.
                - "checkpointed_mb": Activation memory with checkpoints.
                - "saved_mb": Absolute memory saved.
                - "saved_pct": Percentage of memory saved.
                - "checkpointed_layers": Number of checkpointed layers.
                - "compute_overhead_estimate": Estimated runtime overhead.
        """
        cfg = self.model.config
        hidden_size = cfg.hidden_size
        num_layers = cfg.num_layers
        kv_heads = cfg.num_key_value_heads
        num_heads = cfg.num_attention_heads
        head_dim = cfg.head_dim
        intermediate_size = cfg.intermediate_size
        bytes_per_elem = 4

        # Per-layer activation memory estimate
        attn_q = batch_size * seq_length * num_heads * head_dim * bytes_per_elem
        attn_k = batch_size * seq_length * kv_heads * head_dim * bytes_per_elem
        attn_v = batch_size * seq_length * kv_heads * head_dim * bytes_per_elem
        attn_scores = batch_size * num_heads * seq_length * seq_length * bytes_per_elem
        attn_output = batch_size * seq_length * hidden_size * bytes_per_elem
        attn_residual = batch_size * seq_length * hidden_size * bytes_per_elem
        attn_total = attn_q + attn_k + attn_v + attn_scores + attn_output + attn_residual

        ffn_gate = batch_size * seq_length * intermediate_size * bytes_per_elem
        ffn_up = batch_size * seq_length * intermediate_size * bytes_per_elem
        ffn_down = batch_size * seq_length * hidden_size * bytes_per_elem
        ffn_residual = batch_size * seq_length * hidden_size * bytes_per_elem
        ffn_total = ffn_gate + ffn_up + ffn_down + ffn_residual

        norm_total = 2 * batch_size * seq_length * hidden_size * bytes_per_elem

        per_layer_mb = (attn_total + ffn_total + norm_total) / (1024 ** 2)

        baseline_mb = per_layer_mb * num_layers

        active = self._select_layers()
        num_checkpointed = len(active)
        num_active = num_layers - num_checkpointed

        # Checkpointed layers only store input (1 activation vs ~7)
        checkpointed_mb = (per_layer_mb * num_active) + (per_layer_mb * num_checkpointed / 7)
        saved_mb = baseline_mb - checkpointed_mb
        saved_pct = (saved_mb / baseline_mb * 100) if baseline_mb > 0 else 0

        # Compute overhead: each checkpointed layer does ~1.33x the FLOPS
        compute_overhead = num_checkpointed / num_layers * 0.33 * 100

        return {
            "baseline_mb": baseline_mb,
            "checkpointed_mb": checkpointed_mb,
            "saved_mb": saved_mb,
            "saved_pct": saved_pct,
            "checkpointed_layers": num_checkpointed,
            "total_layers": num_layers,
            "compute_overhead_estimate_pct": compute_overhead,
        }

    def benchmark_savings(
        self,
        batch_size: int = 1,
        seq_length: int = 2048,
        num_steps: int = 10,
    ) -> Dict[str, float]:
        """
        Measure actual memory savings by running a forward/backward pass.

        This is a benchmark helper that measures CUDA memory with and
        without checkpointing.

        Args:
            batch_size: Batch size for the test.
            seq_length: Sequence length for the test.
            num_steps: Number of training steps to average.

        Returns:
            Dictionary with measured memory and timing data.
        """
        if not torch.cuda.is_available():
            return {"error": "CUDA is not available for measurement"}

        device = next(self.model.parameters()).device
        dummy_input = torch.randint(
            0, self.model.config.vocab_size - 1,
            (batch_size, seq_length),
            device=device,
        )

        # Measure WITHOUT checkpointing
        self.disable()
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.empty_cache()

        no_gc_times = []
        no_gc_peak = 0
        for _ in range(num_steps):
            torch.cuda.reset_peak_memory_stats()
            start_event = torch.cuda.Event(enable_timing=True)
            end_event = torch.cuda.Event(enable_timing=True)

            start_event.record()
            outputs = self.model(input_ids=dummy_input)
            loss = outputs["logits"].sum()
            loss.backward()
            end_event.record()
            torch.cuda.synchronize()

            no_gc_times.append(start_event.elapsed_time(end_event))
            peak = torch.cuda.max_memory_allocated() / (1024 ** 2)
            no_gc_peak = max(no_gc_peak, peak)

        # Measure WITH checkpointing
        self.enable()
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.empty_cache()

        gc_times = []
        gc_peak = 0
        for _ in range(num_steps):
            torch.cuda.reset_peak_memory_stats()
            start_event = torch.cuda.Event(enable_timing=True)
            end_event = torch.cuda.Event(enable_timing=True)

            start_event.record()
            outputs = self.model(input_ids=dummy_input)
            loss = outputs["logits"].sum()
            loss.backward()
            end_event.record()
            torch.cuda.synchronize()

            gc_times.append(start_event.elapsed_time(end_event))
            peak = torch.cuda.max_memory_allocated() / (1024 ** 2)
            gc_peak = max(gc_peak, peak)

        avg_no_gc_time = sum(no_gc_times) / len(no_gc_times)
        avg_gc_time = sum(gc_times) / len(gc_times)

        return {
            "no_checkpoint_peak_memory_mb": no_gc_peak,
            "checkpoint_peak_memory_mb": gc_peak,
            "memory_saved_mb": no_gc_peak - gc_peak,
            "memory_saved_pct": ((no_gc_peak - gc_peak) / no_gc_peak * 100) if no_gc_peak > 0 else 0,
            "no_checkpoint_avg_time_ms": avg_no_gc_time,
            "checkpoint_avg_time_ms": avg_gc_time,
            "time_overhead_pct": ((avg_gc_time - avg_no_gc_time) / avg_no_gc_time * 100) if avg_no_gc_time > 0 else 0,
            "num_checkpointed_layers": len(self._select_layers()),
            "total_layers": self.num_layers,
            "batch_size": batch_size,
            "seq_length": seq_length,
            "num_steps": num_steps,
        }

    def summary(self) -> str:
        """
        Generate a summary of the current checkpointing configuration.

        Returns:
            Formatted summary string.
        """
        indices = self._select_layers()
        savings = self.estimate_memory_savings()

        lines = [
            "=" * 60,
            "Gradient Checkpointing Summary",
            "=" * 60,
            f"  Policy:              {self._policy.value}",
            f"  Total layers:        {self.num_layers}",
            f"  Checkpointed layers: {len(indices)}",
            f"  Active layers:       {self.num_layers - len(indices)}",
            "",
            "  Checkpointed layer indices: " + (
                ", ".join(str(i) for i in indices) if indices else "None"
            ),
            "",
            "Memory Savings Estimate:",
            f"  Baseline activation memory:  {savings['baseline_mb']:.2f} MiB",
            f"  Checkpointed activation mem: {savings['checkpointed_mb']:.2f} MiB",
            f"  Memory saved:                {savings['saved_mb']:.2f} MiB ({savings['saved_pct']:.1f}%)",
            f"  Estimated compute overhead:  {savings['compute_overhead_estimate_pct']:.1f}%",
            "-" * 60,
        ]

        return "\n".join(lines)
