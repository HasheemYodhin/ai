"""
Memory profiling for transformer models.

Provides detailed analysis of memory usage including:
    - Peak and current CUDA memory tracking
    - Per-layer parameter memory breakdown
    - Activation memory estimation
    - Gradient memory estimation
    - KV cache memory calculation
    - Memory savings from optimizations (gradient checkpointing,
      quantization, KV cache optimization)
"""

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import torch
import torch.nn as nn

from dabba.model.transformer import Transformer
from dabba.model.decoder_block import DecoderBlock
from dabba.model.attention import MultiHeadAttention, GroupedQueryAttention
from dabba.model.feed_forward import FeedForward
from dabba.model.kv_cache import KVCache
from dabba.config.model_config import ModelConfig


@dataclass
class MemoryBreakdown:
    """
    Detailed memory breakdown for a single component.

    Attributes:
        parameter_mb: Memory used by parameters in MiB.
        buffer_mb: Memory used by buffers in MiB.
        total_mb: Total memory (parameters + buffers) in MiB.
        num_parameters: Number of trainable parameters.
        dtype: Data type of the component.
    """
    parameter_mb: float = 0.0
    buffer_mb: float = 0.0
    total_mb: float = 0.0
    num_parameters: int = 0
    dtype: str = "float32"


@dataclass
class MemoryReport:
    """
    Complete memory profiling report.

    Attributes:
        total_parameter_mb: Total parameter memory in MiB.
        total_buffer_mb: Total buffer memory in MiB.
        total_model_mb: Total model memory (params + buffers) in MiB.
        peak_allocated_mb: Peak CUDA allocated memory in MiB.
        current_allocated_mb: Current CUDA allocated memory in MiB.
        peak_reserved_mb: Peak CUDA reserved memory in MiB.
        current_reserved_mb: Current CUDA reserved memory in MiB.

        per_layer_parameters: Parameter memory breakdown by layer.
        per_layer_activations: Estimated activation memory by layer.
        per_layer_gradients: Estimated gradient memory by layer.

        embedding_mb: Embedding parameter memory in MiB.
        output_head_mb: Output head parameter memory in MiB.
        normalization_mb: Normalization parameter memory in MiB.

        attention_parameters_mb: Total attention parameter memory.
        ffn_parameters_mb: Total FFN parameter memory.

        kv_cache_mb: Estimated KV cache memory in MiB.
        kv_cache_per_layer_mb: Per-layer KV cache memory in MiB.

        activation_estimation_mb: Total estimated activation memory.
        gradient_estimation_mb: Total estimated gradient memory.
        optimizer_state_mb: Estimated optimizer state memory (AdamW).

        saved_memory_gradient_checkpointing_mb: Memory saved by
            gradient checkpointing.
        saved_memory_kv_cache_opt_mb: Memory saved by KV cache opt.
        saved_memory_quantization_mb: Memory saved by quantization.

        model_bytes: Total model size in bytes.
        model_size_mb: Total model size in MiB.
        model_size_gb: Total model size in GiB.

        config_snapshot: Model configuration at profiling time.
    """
    total_parameter_mb: float = 0.0
    total_buffer_mb: float = 0.0
    total_model_mb: float = 0.0
    peak_allocated_mb: float = 0.0
    current_allocated_mb: float = 0.0
    peak_reserved_mb: float = 0.0
    current_reserved_mb: float = 0.0

    per_layer_parameters: Dict[int, MemoryBreakdown] = field(default_factory=dict)
    per_layer_activations: Dict[int, float] = field(default_factory=dict)
    per_layer_gradients: Dict[int, float] = field(default_factory=dict)

    embedding_mb: float = 0.0
    output_head_mb: float = 0.0
    normalization_mb: float = 0.0

    attention_parameters_mb: float = 0.0
    ffn_parameters_mb: float = 0.0

    kv_cache_mb: float = 0.0
    kv_cache_per_layer_mb: float = 0.0

    activation_estimation_mb: float = 0.0
    gradient_estimation_mb: float = 0.0
    optimizer_state_mb: float = 0.0

    saved_memory_gradient_checkpointing_mb: float = 0.0
    saved_memory_kv_cache_opt_mb: float = 0.0
    saved_memory_quantization_mb: float = 0.0

    model_bytes: int = 0
    model_size_mb: float = 0.0
    model_size_gb: float = 0.0

    config_snapshot: Dict[str, Union[int, float, str, bool, None]] = field(default_factory=dict)


class MemoryProfiler:
    """
    Profile the memory usage of a transformer model.

    Provides detailed breakdowns of parameter memory, activation memory,
    gradient memory, and KV cache memory. Tracks CUDA memory allocation
    and estimates memory savings from various optimization techniques.

    Args:
        model: The transformer model to profile.
        device: Device to profile memory on.
        dtype: Torch dtype used for the model.
    """

    def __init__(
        self,
        model: Transformer,
        device: Optional[torch.device] = None,
        dtype: torch.dtype = torch.float32,
    ):
        self.model = model
        self.device = device or (
            torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
        )
        self.dtype = dtype
        self._cuda_available = torch.cuda.is_available()
        self._cuda_device = self.device.index if self._cuda_available else None

    def profile(
        self,
        batch_size: int = 1,
        seq_length: int = 2048,
        profile_cuda: bool = True,
    ) -> MemoryReport:
        """
        Run comprehensive memory profiling on the model.

        Args:
            batch_size: Batch size for activation estimation.
            seq_length: Sequence length for activation/KV cache estimation.
            profile_cuda: If True, run a forward pass to measure CUDA
                          memory allocation.

        Returns:
            MemoryReport with full memory breakdown.
        """
        report = MemoryReport()
        report.config_snapshot = self._config_snapshot()

        self._profile_parameters(report)
        self._estimate_activations(report, batch_size, seq_length)
        self._estimate_gradients(report)
        self._estimate_optimizer_state(report)
        self._estimate_kv_cache(report, batch_size, seq_length)

        if profile_cuda and self._cuda_available:
            self._profile_cuda_memory(report, batch_size, seq_length)

        # Model size summary
        report.model_bytes = sum(
            p.numel() * p.element_size() for p in self.model.parameters()
        )
        report.model_size_mb = report.model_bytes / (1024 ** 2)
        report.model_size_gb = report.model_bytes / (1024 ** 3)
        report.total_parameter_mb = sum(
            p.numel() * p.element_size() for p in self.model.parameters()
        ) / (1024 ** 2)
        report.total_buffer_mb = sum(
            b.numel() * b.element_size() for b in self.model.buffers()
        ) / (1024 ** 2)
        report.total_model_mb = report.total_parameter_mb + report.total_buffer_mb

        return report

    def _profile_parameters(self, report: MemoryReport) -> None:
        """
        Profile parameter memory usage per component.

        Args:
            report: MemoryReport to populate.
        """
        total_attn_params = 0
        total_ffn_params = 0
        total_norm_params = 0
        total_norm_bytes = 0

        for name, module in self.model.named_modules():
            if isinstance(module, DecoderBlock):
                layer_idx = module.layer_idx or 0
                br = self._breakdown_module(module)
                report.per_layer_parameters[layer_idx] = br

            if isinstance(module, (MultiHeadAttention, GroupedQueryAttention)):
                total_attn_params += sum(p.numel() for p in module.parameters())

            if isinstance(module, FeedForward):
                total_ffn_params += sum(p.numel() for p in module.parameters())

            if "layernorm" in name.lower() or "rmsnorm" in name.lower() or "norm" in name.lower():
                if not isinstance(module, (MultiHeadAttention, GroupedQueryAttention, FeedForward)):
                    for p in module.parameters():
                        total_norm_params += p.numel()
                        total_norm_bytes += p.numel() * p.element_size()

        # Embedding
        embed_params = sum(p.numel() for p in self.model.embed_tokens.parameters())
        embed_bytes = embed_params * self._element_size(self.model.embed_tokens)
        report.embedding_mb = embed_bytes / (1024 ** 2)

        # Output head
        head_params = sum(p.numel() for p in self.model.lm_head.parameters())
        head_bytes = head_params * self._element_size(self.model.lm_head)
        report.output_head_mb = head_bytes / (1024 ** 2)

        # Normalization (overall)
        report.normalization_mb = total_norm_bytes / (1024 ** 2)

        # Attention and FFN totals
        attn_bytes = total_attn_params * 4  # assume float32
        ffn_bytes = total_ffn_params * 4
        report.attention_parameters_mb = attn_bytes / (1024 ** 2)
        report.ffn_parameters_mb = ffn_bytes / (1024 ** 2)

    def _estimate_activations(
        self,
        report: MemoryReport,
        batch_size: int,
        seq_length: int,
    ) -> None:
        """
        Estimate activation memory for the forward pass.

        Uses the model configuration to compute the memory required
        to store activations during the forward pass. This is a
        lower-bound estimate based on known tensor shapes.

        Args:
            report: MemoryReport to populate.
            batch_size: Batch size for estimation.
            seq_length: Sequence length for estimation.
        """
        cfg = self.model.config
        hidden_size = cfg.hidden_size
        num_layers = cfg.num_layers
        num_heads = cfg.num_attention_heads
        head_dim = cfg.head_dim
        intermediate_size = cfg.intermediate_size
        kv_heads = cfg.num_key_value_heads

        bytes_per_elem = 4  # float32 assumption

        # Per-layer activation breakdown:
        # 1. Attention: Q, K, V projections + output + residual
        #    Q: (batch, seq, num_heads * head_dim)
        #    K: (batch, seq, kv_heads * head_dim)
        #    V: (batch, seq, kv_heads * head_dim)
        #    attn_output: (batch, seq, hidden)
        #    residual: (batch, seq, hidden)
        # 2. FFN: gate, up, down + residual
        #    gate_proj: (batch, seq, intermediate)
        #    up_proj: (batch, seq, intermediate)
        #    down_proj input: (batch, seq, intermediate)
        #    residual: (batch, seq, hidden)
        # 3. Two normalizations: input_layernorm, post_attention_layernorm

        # Attention activations (simplified: just the outputs stored for backward)
        attn_q = batch_size * seq_length * num_heads * head_dim * bytes_per_elem
        attn_k = batch_size * seq_length * kv_heads * head_dim * bytes_per_elem
        attn_v = batch_size * seq_length * kv_heads * head_dim * bytes_per_elem
        attn_scores = (
            batch_size * num_heads * seq_length * seq_length * bytes_per_elem
        )
        attn_output = batch_size * seq_length * hidden_size * bytes_per_elem
        attn_residual = batch_size * seq_length * hidden_size * bytes_per_elem
        attn_total = attn_q + attn_k + attn_v + attn_scores + attn_output + attn_residual

        # FFN activations
        ffn_gate = batch_size * seq_length * intermediate_size * bytes_per_elem
        ffn_up = batch_size * seq_length * intermediate_size * bytes_per_elem
        ffn_down = batch_size * seq_length * hidden_size * bytes_per_elem
        ffn_residual = batch_size * seq_length * hidden_size * bytes_per_elem
        ffn_total = ffn_gate + ffn_up + ffn_down + ffn_residual

        norm_total = 2 * batch_size * seq_length * hidden_size * bytes_per_elem

        per_layer_mb = (attn_total + ffn_total + norm_total) / (1024 ** 2)

        # Without gradient checkpointing: all layer activations are stored
        total_activations_mb = per_layer_mb * num_layers

        # With full gradient checkpointing: only the input to each checkpoint
        # segment is stored (approx 1 / num_layers of above)
        checkpointed_activations_mb = per_layer_mb * 2  # ~2 checkpoints

        report.activation_estimation_mb = total_activations_mb
        report.saved_memory_gradient_checkpointing_mb = (
            total_activations_mb - checkpointed_activations_mb
        )

        # Per-layer activation estimates
        for i in range(num_layers):
            report.per_layer_activations[i] = per_layer_mb

    def _estimate_gradients(self, report: MemoryReport) -> None:
        """
        Estimate gradient memory usage.

        Gradients have the same size as parameters for the parameters
        that require gradients.

        Args:
            report: MemoryReport to populate.
        """
        total_grad_bytes = 0

        for p in self.model.parameters():
            if p.requires_grad:
                total_grad_bytes += p.numel() * p.element_size()

        report.gradient_estimation_mb = total_grad_bytes / (1024 ** 2)

        # Per-layer gradient estimates (proportional to parameters)
        total_params = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        for layer_idx, br in report.per_layer_parameters.items():
            if total_params > 0:
                ratio = br.num_parameters / total_params
                report.per_layer_gradients[layer_idx] = report.gradient_estimation_mb * ratio
            else:
                report.per_layer_gradients[layer_idx] = 0.0

    def _estimate_optimizer_state(self, report: MemoryReport) -> None:
        """
        Estimate optimizer state memory for AdamW.

        AdamW stores two momentum buffers per parameter (exp_avg and
        exp_avg_sq), each the same size as the parameter.

        Args:
            report: MemoryReport to populate.
        """
        total_params_bytes = sum(
            p.numel() * p.element_size() for p in self.model.parameters()
        )
        # AdamW: 2 momentum buffers per parameter
        report.optimizer_state_mb = (total_params_bytes * 2) / (1024 ** 2)

    def _estimate_kv_cache(
        self,
        report: MemoryReport,
        batch_size: int,
        seq_length: int,
    ) -> None:
        """
        Estimate KV cache memory for inference.

        The KV cache stores keys and values for each layer, head, and
        cached token. Memory scales with batch_size * num_layers *
        num_kv_heads * seq_length * head_dim * 2 (for K and V).

        Args:
            report: MemoryReport to populate.
            batch_size: Batch size for estimation.
            seq_length: Maximum cache sequence length.
        """
        cfg = self.model.config
        bytes_per_elem = 2  # FP16 KV cache (typical)

        per_layer_bytes = (
            batch_size * cfg.num_key_value_heads * seq_length * cfg.head_dim * 2 * bytes_per_elem
        )
        per_layer_mb = per_layer_bytes / (1024 ** 2)
        total_mb = per_layer_mb * cfg.num_layers

        report.kv_cache_mb = total_mb
        report.kv_cache_per_layer_mb = per_layer_mb

    def _profile_cuda_memory(
        self,
        report: MemoryReport,
        batch_size: int,
        seq_length: int,
    ) -> None:
        """
        Measure actual CUDA memory usage by running a forward pass.

        Args:
            report: MemoryReport to populate.
            batch_size: Batch size for the test forward pass.
            seq_length: Sequence length for the test forward pass.
        """
        torch.cuda.reset_peak_memory_stats(self._cuda_device)
        torch.cuda.empty_cache()

        dummy_input = torch.randint(
            0, self.model.config.vocab_size - 1,
            (batch_size, seq_length),
            device=self.device,
        )

        # Before forward pass
        mem_before = torch.cuda.memory_allocated(self._cuda_device)

        with torch.no_grad():
            _ = self.model(input_ids=dummy_input, use_cache=True)
            torch.cuda.synchronize()

        peak_memory = torch.cuda.max_memory_allocated(self._cuda_device)
        current_memory = torch.cuda.memory_allocated(self._cuda_device)
        reserved_peak = torch.cuda.max_memory_reserved(self._cuda_device)
        reserved_current = torch.cuda.memory_reserved(self._cuda_device)

        report.peak_allocated_mb = peak_memory / (1024 ** 2)
        report.current_allocated_mb = current_memory / (1024 ** 2)
        report.peak_reserved_mb = reserved_peak / (1024 ** 2)
        report.current_reserved_mb = reserved_current / (1024 ** 2)

    def estimate_kv_cache_size(
        self,
        batch_size: int = 1,
        seq_length: int = 2048,
        dtype_bits: int = 16,
    ) -> Dict[str, float]:
        """
        Estimate the size of the KV cache under different configurations.

        Useful for understanding memory requirements before deployment.

        Args:
            batch_size: Batch size for estimation.
            seq_length: Cache sequence length.
            dtype_bits: Bits per element (16 for FP16, 8 for INT8, etc.).

        Returns:
            Dictionary with per-layer and total KV cache sizes.
        """
        cfg = self.model.config
        bytes_per_elem = dtype_bits / 8

        per_layer_bytes = (
            batch_size * cfg.num_key_value_heads * seq_length * cfg.head_dim * 2 * bytes_per_elem
        )
        total_bytes = per_layer_bytes * cfg.num_layers

        return {
            "per_layer_kv_cache_mb": per_layer_bytes / (1024 ** 2),
            "total_kv_cache_mb": total_bytes / (1024 ** 2),
            "per_layer_kv_cache_gb": per_layer_bytes / (1024 ** 3),
            "total_kv_cache_gb": total_bytes / (1024 ** 3),
            "batch_size": batch_size,
            "seq_length": seq_length,
            "dtype_bits": dtype_bits,
            "num_layers": cfg.num_layers,
            "num_kv_heads": cfg.num_key_value_heads,
            "head_dim": cfg.head_dim,
        }

    def estimate_savings(
        self,
        quantization_bits: Optional[int] = None,
        kv_cache_bits: Optional[int] = None,
        use_gradient_checkpointing: bool = False,
    ) -> Dict[str, float]:
        """
        Estimate memory savings from various optimization techniques.

        Args:
            quantization_bits: Target quantization bits (4, 8) or None.
            kv_cache_bits: Target KV cache bits (8) or None.
            use_gradient_checkpointing: Whether to estimate GC savings.

        Returns:
            Dictionary with memory savings estimates.
        """
        base_memory = self._get_base_memory()
        savings = {}

        if quantization_bits is not None:
            current_bits = self._get_current_weight_bits()
            ratio = quantization_bits / current_bits
            quantized_memory = base_memory * ratio
            savings["quantization_mb"] = base_memory - quantized_memory
            savings["quantization_pct"] = (1 - ratio) * 100
        else:
            savings["quantization_mb"] = 0.0
            savings["quantization_pct"] = 0.0

        if kv_cache_bits is not None:
            savings["kv_cache_mb"] = self._estimate_kv_cache_savings(kv_cache_bits)
        else:
            savings["kv_cache_mb"] = 0.0

        if use_gradient_checkpointing:
            cfg = self.model.config
            seq_length = 2048
            batch_size = 1
            hidden_size = cfg.hidden_size
            bytes_per_elem = 4
            per_layer = batch_size * seq_length * hidden_size * bytes_per_elem * 7 / (1024 ** 2)
            activations_no_gc = per_layer * cfg.num_layers
            activations_with_gc = per_layer * 2
            savings["gradient_checkpointing_mb"] = activations_no_gc - activations_with_gc
        else:
            savings["gradient_checkpointing_mb"] = 0.0

        total_saved = (
            savings["quantization_mb"]
            + savings["kv_cache_mb"]
            + savings["gradient_checkpointing_mb"]
        )
        savings["total_saved_mb"] = total_saved
        savings["remaining_mb"] = base_memory - total_saved

        return savings

    def _get_base_memory(self) -> float:
        """Get the current model parameter memory in MiB."""
        return sum(p.numel() * p.element_size() for p in self.model.parameters()) / (1024 ** 2)

    def _get_current_weight_bits(self) -> int:
        """Get the current weight precision in bits."""
        for p in self.model.parameters():
            return p.element_size() * 8
        return 32

    def _estimate_kv_cache_savings(self, target_bits: int) -> float:
        """Estimate memory savings from KV cache quantization."""
        cfg = self.model.config
        batch_size = 1
        seq_length = 2048
        bytes_per_elem_fp16 = 2
        bytes_per_elem_target = target_bits / 8
        per_layer_bytes_fp16 = (
            batch_size * cfg.num_key_value_heads * seq_length * cfg.head_dim * 2 * bytes_per_elem_fp16
        )
        per_layer_bytes_target = (
            batch_size * cfg.num_key_value_heads * seq_length * cfg.head_dim * 2 * bytes_per_elem_target
        )
        savings_per_layer = (per_layer_bytes_fp16 - per_layer_bytes_target) / (1024 ** 2)
        return savings_per_layer * cfg.num_layers

    def _breakdown_module(self, module: nn.Module) -> MemoryBreakdown:
        """
        Get a memory breakdown for a specific module.

        Args:
            module: The PyTorch module to analyze.

        Returns:
            MemoryBreakdown with parameter statistics.
        """
        param_bytes = 0
        param_count = 0
        param_dtype = "float32"

        for p in module.parameters():
            param_bytes += p.numel() * p.element_size()
            param_count += p.numel()
            param_dtype = str(p.dtype)

        buffer_bytes = 0
        for b in module.buffers():
            buffer_bytes += b.numel() * b.element_size()

        return MemoryBreakdown(
            parameter_mb=param_bytes / (1024 ** 2),
            buffer_mb=buffer_bytes / (1024 ** 2),
            total_mb=(param_bytes + buffer_bytes) / (1024 ** 2),
            num_parameters=param_count,
            dtype=param_dtype,
        )

    def _element_size(self, module: nn.Module) -> int:
        """
        Get the element size of the module's parameters (in bytes).

        Args:
            module: PyTorch module.

        Returns:
            Element size in bytes.
        """
        for p in module.parameters():
            return p.element_size()
        return 4

    def _config_snapshot(self) -> Dict[str, Union[int, float, str, bool, None]]:
        """Capture a snapshot of the model configuration."""
        cfg = self.model.config
        return {
            "vocab_size": cfg.vocab_size,
            "hidden_size": cfg.hidden_size,
            "num_layers": cfg.num_layers,
            "num_attention_heads": cfg.num_attention_heads,
            "num_key_value_heads": cfg.num_key_value_heads,
            "head_dim": cfg.head_dim,
            "intermediate_size": cfg.intermediate_size,
            "max_position_embeddings": cfg.max_position_embeddings,
            "num_params": cfg.num_params,
            "dtype": str(self.dtype),
            "device": str(self.device),
        }

    def export_json(self, report: MemoryReport, path: Union[str, Path]) -> None:
        """
        Export memory report to a JSON file.

        Args:
            report: MemoryReport to export.
            path: Output file path.
        """
        data = asdict(report)

        def convert(obj):
            if isinstance(obj, dict):
                return {str(k): convert(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [convert(v) for v in obj]
            if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
                return str(obj)
            return obj

        data = convert(data)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Memory report exported to {path}")

    def summary(self, report: MemoryReport) -> str:
        """
        Generate a human-readable memory profiling summary.

        Args:
            report: MemoryReport to summarize.

        Returns:
            Formatted summary string.
        """
        lines = [
            "=" * 60,
            "Memory Profiling Summary",
            "=" * 60,
            "Model Size:",
            f"  Parameters:       {report.config_snapshot.get('num_params', 0):,}",
            f"  Model Size:       {report.model_size_mb:.2f} MiB ({report.model_size_gb:.2f} GiB)",
            f"  Parameter Memory: {report.total_parameter_mb:.2f} MiB",
            f"  Buffer Memory:    {report.total_buffer_mb:.2f} MiB",
            "",
            "Component Breakdown:",
            f"  Embeddings:       {report.embedding_mb:.2f} MiB",
            f"  Output Head:      {report.output_head_mb:.2f} MiB",
            f"  Normalization:    {report.normalization_mb:.2f} MiB",
            f"  Attention Total:  {report.attention_parameters_mb:.2f} MiB",
            f"  FFN Total:        {report.ffn_parameters_mb:.2f} MiB",
            "",
            "Per-Layer Parameters:",
        ]

        for layer_idx in sorted(report.per_layer_parameters.keys()):
            br = report.per_layer_parameters[layer_idx]
            lines.append(f"  Layer {layer_idx:>2}: {br.total_mb:.3f} MiB ({br.num_parameters:,} params)")

        lines.extend([
            "",
            "Memory Estimates:",
            f"  Activation Memory (no GC):  {report.activation_estimation_mb:.2f} MiB",
            f"  Gradient Memory:             {report.gradient_estimation_mb:.2f} MiB",
            f"  Optimizer State (AdamW):     {report.optimizer_state_mb:.2f} MiB",
            f"  KV Cache (FP16, 2048 ctx):   {report.kv_cache_mb:.2f} MiB",
            "",
            "CUDA Memory (measured):" if report.peak_allocated_mb > 0 else "CUDA Memory: N/A (no GPU)",
        ])

        if report.peak_allocated_mb > 0:
            lines.extend([
                f"  Peak Allocated:  {report.peak_allocated_mb:.2f} MiB",
                f"  Current Allocated: {report.current_allocated_mb:.2f} MiB",
                f"  Peak Reserved:   {report.peak_reserved_mb:.2f} MiB",
            ])

        lines.extend([
            "",
            "Estimated Savings from Optimizations:",
            f"  Gradient Checkpointing: {report.saved_memory_gradient_checkpointing_mb:.2f} MiB",
            "-" * 60,
        ])

        return "\n".join(lines)
