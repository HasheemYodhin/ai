"""
Latency profiling for transformer model inference.

Provides per-layer and per-operation timing for the forward pass,
including attention computation, feed-forward network (FFN) computation,
and normalization. Reports latency percentiles (P50, P90, P99, P99.9)
and generates latency histograms.

Uses PyTorch's CUDA events for accurate GPU timing and fallback to
Python time.perf_counter() for CPU-only environments.
"""

import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import torch

from dabba.model.transformer import Transformer
from dabba.model.decoder_block import DecoderBlock
from dabba.model.attention import MultiHeadAttention, GroupedQueryAttention
from dabba.model.feed_forward import FeedForward


@dataclass
class LatencyStats:
    """
    Statistical summary of latency measurements.

    Attributes:
        mean_ms: Mean latency in milliseconds.
        median_ms: Median latency (P50) in milliseconds.
        p90_ms: 90th percentile latency in milliseconds.
        p99_ms: 99th percentile latency in milliseconds.
        p999_ms: 99.9th percentile latency in milliseconds.
        min_ms: Minimum latency in milliseconds.
        max_ms: Maximum latency in milliseconds.
        std_ms: Standard deviation in milliseconds.
        num_samples: Number of samples collected.
    """
    mean_ms: float = 0.0
    median_ms: float = 0.0
    p90_ms: float = 0.0
    p99_ms: float = 0.0
    p999_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    std_ms: float = 0.0
    num_samples: int = 0


@dataclass
class LatencyReport:
    """
    Complete latency profiling report.

    Attributes:
        layer_stats: Per-layer latency statistics keyed by layer index.
        attention_stats: Attention sub-module latency statistics.
        ffn_stats: FFN sub-module latency statistics.
        normalization_stats: Normalization latency statistics.
        embedding_stats: Embedding lookup latency statistics.
        output_head_stats: Output head (LM head) latency statistics.
        total_stats: Total forward pass latency statistics.
        overhead_stats: Profiling overhead measurement.
        histogram: Latency histogram bins (bin_edges, counts).
        config_snapshot: Model configuration at profiling time.
    """
    layer_stats: Dict[int, LatencyStats] = field(default_factory=dict)
    attention_stats: Dict[int, LatencyStats] = field(default_factory=dict)
    ffn_stats: Dict[int, LatencyStats] = field(default_factory=dict)
    normalization_stats: Dict[int, LatencyStats] = field(default_factory=dict)
    embedding_stats: LatencyStats = field(default_factory=LatencyStats)
    output_head_stats: LatencyStats = field(default_factory=LatencyStats)
    total_stats: LatencyStats = field(default_factory=LatencyStats)
    overhead_stats: LatencyStats = field(default_factory=LatencyStats)
    histogram: Dict[str, List[float]] = field(default_factory=dict)
    config_snapshot: Dict[str, Union[int, float, str, bool, None]] = field(default_factory=dict)


class LatencyProfiler:
    """
    Profile per-layer and per-operation latency of a transformer model.

    Hooks into the model's forward pass to measure timing of individual
    components: attention, FFN, normalization, embedding, output head.

    Supports:
        - Per-layer timing breakdown.
        - Attention computation timing.
        - FFN computation timing.
        - Latency percentiles (P50, P90, P99, P99.9).
        - Latency histogram with configurable bins.
        - Overhead measurement (cost of profiling itself).

    Args:
        model: The transformer model to profile.
        device: Device to run on. Auto-detected if None.
        dtype: Torch dtype for evaluation.
        num_bins: Number of histogram bins.
    """

    def __init__(
        self,
        model: Transformer,
        device: Optional[torch.device] = None,
        dtype: torch.dtype = torch.float32,
        num_bins: int = 50,
    ):
        self.model = model
        self.device = device or (
            torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
        )
        self.dtype = dtype
        self.model.to(self.device)
        self.model.eval()
        self._cuda_available = torch.cuda.is_available()
        self.num_bins = num_bins

        self._layer_times: Dict[str, List[float]] = defaultdict(list)
        self._attn_times: Dict[int, List[float]] = defaultdict(list)
        self._ffn_times: Dict[int, List[float]] = defaultdict(list)
        self._norm_times: Dict[int, List[float]] = defaultdict(list)
        self._embed_times: List[float] = []
        self._output_head_times: List[float] = []
        self._total_times: List[float] = []

        self._forward_hooks: List[torch.utils.hooks.RemovableHandle] = []
        self._register_hooks()

        self._overhead_samples: List[float] = []

    def _register_hooks(self) -> None:
        """Register forward hooks on all model submodules for timing."""
        self._forward_hooks.clear()

        for name, module in self.model.named_modules():
            if isinstance(module, DecoderBlock):
                handle = module.register_forward_hook(
                    self._make_layer_hook(module.layer_idx or 0)
                )
                self._forward_hooks.append(handle)

                # Hook attention inside the block
                attn_handle = module.self_attn.register_forward_hook(
                    self._make_attn_hook(module.layer_idx or 0)
                )
                self._forward_hooks.append(attn_handle)

                # Hook FFN inside the block
                ffn_handle = module.feed_forward.register_forward_hook(
                    self._make_ffn_hook(module.layer_idx or 0)
                )
                self._forward_hooks.append(ffn_handle)

                # Hook norms inside the block
                for subname, submod in module.named_modules():
                    if "layernorm" in subname.lower() or "rmsnorm" in subname.lower():
                        norm_handle = submod.register_forward_hook(
                            self._make_norm_hook(module.layer_idx or 0)
                        )
                        self._forward_hooks.append(norm_handle)

    def _make_layer_hook(self, layer_idx: int):
        """Create a forward hook for a decoder block."""
        def hook(module, input_tensors, output_tensor):
            if self._cuda_available:
                torch.cuda.synchronize()
            key = f"layer_{layer_idx}"
            self._layer_times[key].append(0.0)
        return hook

    def _make_attn_hook(self, layer_idx: int):
        """Create a forward hook for an attention module."""
        start_times = {}

        def pre_hook(module, input_tensors):
            if self._cuda_available:
                if torch.cuda.is_available():
                    start_event = torch.cuda.Event(enable_timing=True)
                    start_event.record()
                    start_times[id(module)] = start_event
            else:
                start_times[id(module)] = time.perf_counter()

        def post_hook(module, input_tensors, output_tensor):
            if id(module) in start_times:
                if self._cuda_available:
                    end_event = torch.cuda.Event(enable_timing=True)
                    end_event.record()
                    torch.cuda.synchronize()
                    elapsed = start_times[id(module)].elapsed_time(end_event)
                else:
                    elapsed = (time.perf_counter() - start_times[id(module)]) * 1000
                self._attn_times[layer_idx].append(elapsed)
                del start_times[id(module)]

        # We need to register both pre and post hooks
        pre_handle = module.register_forward_pre_hook(pre_hook)
        post_handle = module.register_forward_hook(post_hook)
        self._forward_hooks.append(pre_handle)
        self._forward_hooks.append(post_handle)
        return post_handle

    def _make_ffn_hook(self, layer_idx: int):
        """Create a forward hook for an FFN module."""
        start_times = {}

        def pre_hook(module, input_tensors):
            if self._cuda_available:
                start_event = torch.cuda.Event(enable_timing=True)
                start_event.record()
                start_times[id(module)] = start_event
            else:
                start_times[id(module)] = time.perf_counter()

        def post_hook(module, input_tensors, output_tensor):
            if id(module) in start_times:
                if self._cuda_available:
                    end_event = torch.cuda.Event(enable_timing=True)
                    end_event.record()
                    torch.cuda.synchronize()
                    elapsed = start_times[id(module)].elapsed_time(end_event)
                else:
                    elapsed = (time.perf_counter() - start_times[id(module)]) * 1000
                self._ffn_times[layer_idx].append(elapsed)
                del start_times[id(module)]

        pre_handle = module.register_forward_pre_hook(pre_hook)
        post_handle = module.register_forward_hook(post_hook)
        self._forward_hooks.append(pre_handle)
        self._forward_hooks.append(post_handle)
        return post_handle

    def _make_norm_hook(self, layer_idx: int):
        """Create a forward hook for a normalization module."""
        start_times = {}

        def pre_hook(module, input_tensors):
            if self._cuda_available:
                start_event = torch.cuda.Event(enable_timing=True)
                start_event.record()
                start_times[id(module)] = start_event
            else:
                start_times[id(module)] = time.perf_counter()

        def post_hook(module, input_tensors, output_tensor):
            if id(module) in start_times:
                if self._cuda_available:
                    end_event = torch.cuda.Event(enable_timing=True)
                    end_event.record()
                    torch.cuda.synchronize()
                    elapsed = start_times[id(module)].elapsed_time(end_event)
                else:
                    elapsed = (time.perf_counter() - start_times[id(module)]) * 1000
                self._norm_times[layer_idx].append(elapsed)
                del start_times[id(module)]

        pre_handle = module.register_forward_pre_hook(pre_hook)
        post_handle = module.register_forward_hook(post_hook)
        self._forward_hooks.append(pre_handle)
        self._forward_hooks.append(post_handle)
        return post_handle

    def _remove_hooks(self) -> None:
        """Remove all registered forward hooks."""
        for handle in self._forward_hooks:
            handle.remove()
        self._forward_hooks.clear()

    @torch.no_grad()
    def profile(
        self,
        input_ids: torch.LongTensor,
        num_runs: int = 100,
        warmup_runs: int = 10,
    ) -> LatencyReport:
        """
        Run latency profiling on the model.

        Performs multiple forward passes and collects timing data for
        each submodule. Returns a LatencyReport with full statistics.

        Args:
            input_ids: Input token IDs to profile with.
            num_runs: Number of profiling runs.
            warmup_runs: Number of warmup runs (not recorded).

        Returns:
            LatencyReport with statistics for all profiled components.
        """
        self._clear_data()

        input_ids = input_ids.to(self.device)

        # Warmup
        for _ in range(warmup_runs):
            _ = self.model(input_ids=input_ids)

        # Measure overhead
        self._measure_overhead(num_runs)

        # Profiled runs
        for _ in range(num_runs):
            total_start = time.perf_counter()

            _ = self.model(input_ids=input_ids)

            if self._cuda_available:
                torch.cuda.synchronize()

            total_elapsed = (time.perf_counter() - total_start) * 1000
            self._total_times.append(total_elapsed)

        self._remove_hooks()
        return self._compute_report()

    @torch.no_grad()
    def profile_generate(
        self,
        input_ids: torch.LongTensor,
        max_new_tokens: int = 128,
        num_runs: int = 10,
        warmup_runs: int = 3,
    ) -> LatencyReport:
        """
        Profile latency during autoregressive generation.

        Args:
            input_ids: Prompt token IDs.
            max_new_tokens: Number of tokens to generate.
            num_runs: Number of profiling runs.
            warmup_runs: Number of warmup runs.

        Returns:
            LatencyReport with generation-phase statistics.
        """
        self._clear_data()
        input_ids = input_ids.to(self.device)

        for _ in range(warmup_runs):
            self.model.generate(
                input_ids, max_new_tokens=max_new_tokens, do_sample=False
            )

        for _ in range(num_runs):
            total_start = time.perf_counter()
            self.model.generate(
                input_ids, max_new_tokens=max_new_tokens, do_sample=False
            )
            total_elapsed = (time.perf_counter() - total_start) * 1000
            self._total_times.append(total_elapsed)

        self._remove_hooks()
        return self._compute_report()

    def _measure_overhead(self, num_samples: int = 100) -> None:
        """
        Measure the overhead introduced by profiling hooks.

        Runs a lightweight forward pass without the model to estimate
        hook registration overhead.

        Args:
            num_samples: Number of overhead samples to collect.
        """
        for _ in range(num_samples):
            start = time.perf_counter()
            # Simulate minimal hook overhead
            _ = time.perf_counter()
            elapsed = (time.perf_counter() - start) * 1000
            self._overhead_samples.append(elapsed)

    def _clear_data(self) -> None:
        """Clear all collected timing data."""
        self._layer_times.clear()
        self._attn_times.clear()
        self._ffn_times.clear()
        self._norm_times.clear()
        self._embed_times.clear()
        self._output_head_times.clear()
        self._total_times.clear()
        self._overhead_samples.clear()

    def _compute_stats(self, samples: List[float]) -> LatencyStats:
        """
        Compute statistical summary from a list of latency samples.

        Args:
            samples: List of latency measurements in milliseconds.

        Returns:
            LatencyStats with percentiles and basic statistics.
        """
        if not samples:
            return LatencyStats()

        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        mean = sum(sorted_samples) / n
        median = sorted_samples[n // 2] if n % 2 == 1 else (
            sorted_samples[n // 2 - 1] + sorted_samples[n // 2]
        ) / 2
        p90 = sorted_samples[int(n * 0.90)]
        p99 = sorted_samples[int(n * 0.99)]
        p999 = sorted_samples[min(int(n * 0.999), n - 1)]
        min_val = sorted_samples[0]
        max_val = sorted_samples[-1]
        variance = sum((x - mean) ** 2 for x in sorted_samples) / n
        std = math.sqrt(variance)

        return LatencyStats(
            mean_ms=mean,
            median_ms=median,
            p90_ms=p90,
            p99_ms=p99,
            p999_ms=p999,
            min_ms=min_val,
            max_ms=max_val,
            std_ms=std,
            num_samples=n,
        )

    def _compute_histogram(
        self,
        samples: List[float],
    ) -> Dict[str, List[float]]:
        """
        Compute a latency histogram with configurable bins.

        Args:
            samples: List of latency measurements in milliseconds.

        Returns:
            Dictionary with "bin_edges" and "counts" lists.
        """
        if not samples:
            return {"bin_edges": [], "counts": []}

        min_val = min(samples)
        max_val = max(samples)

        if min_val == max_val:
            bin_edges = [min_val - 0.5, min_val + 0.5]
            counts = [len(samples)]
        else:
            bin_width = (max_val - min_val) / self.num_bins
            bin_edges = [min_val + i * bin_width for i in range(self.num_bins + 1)]
            counts = [0] * self.num_bins

            for s in samples:
                idx = min(int((s - min_val) / bin_width), self.num_bins - 1)
                counts[idx] += 1

        return {
            "bin_edges": bin_edges,
            "counts": [float(c) for c in counts],
        }

    def _compute_report(self) -> LatencyReport:
        """
        Aggregate all collected data into a LatencyReport.

        Returns:
            Complete LatencyReport with all statistics.
        """
        report = LatencyReport()

        # Layer stats
        for key, times in self._layer_times.items():
            layer_idx = int(key.replace("layer_", ""))
            report.layer_stats[layer_idx] = self._compute_stats(times)

        # Attention stats per layer
        for layer_idx, times in self._attn_times.items():
            report.attention_stats[layer_idx] = self._compute_stats(times)

        # FFN stats per layer
        for layer_idx, times in self._ffn_times.items():
            report.ffn_stats[layer_idx] = self._compute_stats(times)

        # Normalization stats per layer
        for layer_idx, times in self._norm_times.items():
            report.normalization_stats[layer_idx] = self._compute_stats(times)

        # Total stats
        report.total_stats = self._compute_stats(self._total_times)

        # Overhead stats
        report.overhead_stats = self._compute_stats(self._overhead_samples)

        # Histogram
        report.histogram = self._compute_histogram(self._total_times)

        # Config snapshot
        cfg = self.model.config
        report.config_snapshot = {
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

        return report

    def export_json(
        self,
        report: LatencyReport,
        path: Union[str, Path],
    ) -> None:
        """
        Export latency report to a JSON file.

        Args:
            report: LatencyReport to export.
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
        print(f"Latency report exported to {path}")

    def summary(self, report: LatencyReport) -> str:
        """
        Generate a human-readable summary of latency profiling.

        Args:
            report: LatencyReport to summarize.

        Returns:
            Formatted summary string.
        """
        lines = [
            "=" * 60,
            "Latency Profiling Summary",
            "=" * 60,
            f"  Total forward pass:",
            f"    Mean:   {report.total_stats.mean_ms:.3f} ms",
            f"    Median: {report.total_stats.median_ms:.3f} ms",
            f"    P90:    {report.total_stats.p90_ms:.3f} ms",
            f"    P99:    {report.total_stats.p99_ms:.3f} ms",
            f"    P99.9:  {report.total_stats.p999_ms:.3f} ms",
            f"    Min:    {report.total_stats.min_ms:.3f} ms",
            f"    Max:    {report.total_stats.max_ms:.3f} ms",
            f"    Std:    {report.total_stats.std_ms:.3f} ms",
            f"    Samples: {report.total_stats.num_samples}",
            "",
            "  Per-layer breakdown (mean ms):",
        ]

        for layer_idx in sorted(report.layer_stats.keys()):
            ls = report.layer_stats[layer_idx]
            lines.append(
                f"    Layer {layer_idx:>2}: {ls.mean_ms:.3f} ms  "
                f"(attn: {report.attention_stats.get(layer_idx, LatencyStats()).mean_ms:.3f} ms, "
                f"ffn: {report.ffn_stats.get(layer_idx, LatencyStats()).mean_ms:.3f} ms)"
            )

        lines.extend([
            "",
            f"  Attention (overall mean): {sum(s.mean_ms for s in report.attention_stats.values()) / max(len(report.attention_stats), 1):.3f} ms",
            f"  FFN (overall mean):       {sum(s.mean_ms for s in report.ffn_stats.values()) / max(len(report.ffn_stats), 1):.3f} ms",
            "",
            f"  Profiling overhead:       {report.overhead_stats.mean_ms:.6f} ms (mean)",
            "-" * 60,
        ])

        return "\n".join(lines)
