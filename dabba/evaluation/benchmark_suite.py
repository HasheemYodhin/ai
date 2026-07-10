"""
Full benchmark orchestration suite.

Runs all evaluation benchmarks (perplexity, throughput, latency, memory)
and aggregates results into a comprehensive report. Supports configurable
scenarios, comparison mode (before/after optimization), and multiple
output formats (JSON, formatted text).
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import torch

from dabba.model.transformer import Transformer
from dabba.data.streaming_dataset import StreamingDataset
from dabba.evaluation.perplexity import PerplexityEvaluator
from dabba.evaluation.benchmark import Benchmark, BenchmarkResults
from dabba.evaluation.latency import LatencyProfiler, LatencyReport
from dabba.evaluation.memory_profile import MemoryProfiler, MemoryReport


@dataclass
class SuiteConfig:
    """
    Configuration for a benchmark scenario.

    Attributes:
        name: Scenario name for reporting.
        batch_sizes: List of batch sizes to test.
        input_lengths: List of input sequence lengths to test.
        output_lengths: List of output generation lengths to test.
        num_warmup: Number of warmup runs.
        num_trials: Number of measured trials.
        eval_batch_size: Batch size for perplexity evaluation.
        eval_max_batches: Max batches for perplexity eval (None = all).
        eval_stride: Stride for sliding window perplexity.
        dataset_path: Path to evaluation dataset.
        num_latency_runs: Number of runs for latency profiling.
        seq_length: Sequence length for memory profiling.
    """
    name: str = "default"
    batch_sizes: List[int] = field(default_factory=lambda: [1, 2, 4, 8])
    input_lengths: List[int] = field(default_factory=lambda: [64, 128, 256, 512])
    output_lengths: List[int] = field(default_factory=lambda: [32, 64, 128])
    num_warmup: int = 3
    num_trials: int = 5
    eval_batch_size: int = 4
    eval_max_batches: Optional[int] = 100
    eval_stride: Optional[int] = None
    dataset_path: Optional[str] = None
    num_latency_runs: int = 50
    seq_length: int = 2048


@dataclass
class SuiteResults:
    """
    Aggregated results from a full benchmark suite run.

    Attributes:
        suite_name: Name of the benchmark scenario.
        start_time: ISO timestamp of start.
        end_time: ISO timestamp of end.
        perplexity: Perplexity evaluation results (or None).
        throughput: Throughput benchmark results (keyed by config).
        latency: Latency profiling report (or None).
        memory: Memory profiling report (or None).
        comparison: Comparison results dict (before/after).
        config_snapshot: Model configuration.
    """
    suite_name: str = ""
    start_time: str = ""
    end_time: str = ""
    perplexity: Optional[Dict[str, float]] = None
    throughput: Dict[str, BenchmarkResults] = field(default_factory=dict)
    latency: Optional[LatencyReport] = None
    memory: Optional[MemoryReport] = None
    comparison: Dict[str, Dict[str, float]] = field(default_factory=dict)
    config_snapshot: Dict[str, Union[int, float, str, bool, None]] = field(default_factory=dict)


class BenchmarkSuite:
    """
    Orchestrate all benchmarks and aggregate results.

    Runs a configurable suite of evaluations on a model and produces
    comprehensive reports. Supports comparison mode to measure the
    impact of optimizations.

    Args:
        model: The transformer model to benchmark.
        device: Device to run on. Auto-detected if None.
        dtype: Torch dtype for evaluation.
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

        self.model.to(self.device)
        self.model.eval()

        self._benchmark = Benchmark(model, device=self.device, dtype=self.dtype)
        self._perplexity = PerplexityEvaluator(
            model, batch_size=1, device=self.device, dtype=self.dtype
        )
        self._latency = LatencyProfiler(model, device=self.device, dtype=self.dtype)
        self._memory = MemoryProfiler(model, device=self.device, dtype=self.dtype)

    def run(
        self,
        config: Optional[SuiteConfig] = None,
        run_perplexity: bool = True,
        run_throughput: bool = True,
        run_latency: bool = True,
        run_memory: bool = True,
        dataset: Optional[StreamingDataset] = None,
        verbose: bool = True,
    ) -> SuiteResults:
        """
        Run the full benchmark suite.

        Args:
            config: SuiteConfig with benchmark parameters.
                    Uses defaults if None.
            run_perplexity: If True, run perplexity evaluation.
            run_throughput: If True, run throughput benchmarks.
            run_latency: If True, run latency profiling.
            run_memory: If True, run memory profiling.
            dataset: Dataset for perplexity evaluation.
            verbose: Print progress information.

        Returns:
            SuiteResults with all aggregated benchmark data.
        """
        if config is None:
            config = SuiteConfig()

        results = SuiteResults(
            suite_name=config.name,
            start_time=time.strftime("%Y-%m-%dT%H:%M:%S"),
            config_snapshot=self._config_snapshot(),
        )

        if run_perplexity and dataset is not None:
            if verbose:
                print("\n[1/4] Running perplexity evaluation...")
            ppl_results = self._perplexity.evaluate(
                dataset,
                max_batches=config.eval_max_batches,
                verbose=verbose,
            )
            results.perplexity = ppl_results
            if verbose:
                print(self._perplexity.summary(ppl_results))

        if run_throughput:
            if verbose:
                print("\n[2/4] Running throughput benchmarks...")

            # Throughput scan over config
            for bs in config.batch_sizes:
                for il in config.input_lengths:
                    for ol in config.output_lengths:
                        scenario_key = f"bs{bs}_in{il}_out{ol}"
                        if verbose:
                            print(f"  Scenario: {scenario_key}")

                        thr_results = self._benchmark.measure_throughput(
                            input_length=il,
                            output_length=ol,
                            batch_size=bs,
                            num_warmup=config.num_warmup,
                            num_trials=config.num_trials,
                        )
                        results.throughput[scenario_key] = thr_results

                        lat_results = self._benchmark.measure_latency(
                            input_length=il,
                            output_length=ol,
                            batch_size=bs,
                            num_warmup=config.num_warmup,
                            num_trials=config.num_trials,
                        )
                        results.throughput[f"{scenario_key}_latency"] = lat_results

        if run_latency:
            if verbose:
                print("\n[3/4] Running latency profiling...")
            dummy_input = torch.randint(
                0, self.model.config.vocab_size - 1,
                (1, 128),
                device=self.device,
            )
            lat_report = self._latency.profile(
                dummy_input,
                num_runs=config.num_latency_runs,
                warmup_runs=config.num_warmup,
            )
            results.latency = lat_report
            if verbose:
                print(self._latency.summary(lat_report))

        if run_memory:
            if verbose:
                print("\n[4/4] Running memory profiling...")
            mem_report = self._memory.profile(
                batch_size=1,
                seq_length=config.seq_length,
                profile_cuda=(self.device.type == "cuda"),
            )
            results.memory = mem_report
            if verbose:
                print(self._memory.summary(mem_report))

        results.end_time = time.strftime("%Y-%m-%dT%H:%M:%S")
        return results

    def compare(
        self,
        baseline: SuiteResults,
        optimized: SuiteResults,
    ) -> SuiteResults:
        """
        Compare two benchmark runs side by side.

        Args:
            baseline: Results before optimization.
            optimized: Results after optimization.

        Returns:
            SuiteResults with comparison data populated.
        """
        comparison = {}

        # Compare perplexity
        if baseline.perplexity and optimized.perplexity:
            comparison["perplexity"] = {
                "before": baseline.perplexity["perplexity"],
                "after": optimized.perplexity["perplexity"],
                "change_pct": (
                    (optimized.perplexity["perplexity"] - baseline.perplexity["perplexity"])
                    / baseline.perplexity["perplexity"] * 100
                ),
            }

        # Compare throughput scenarios
        for key in baseline.throughput:
            if key in optimized.throughput:
                b = baseline.throughput[key]
                a = optimized.throughput[key]
                comparison[key] = {
                    "throughput_before": b.throughput_tps,
                    "throughput_after": a.throughput_tps,
                    "throughput_change_pct": (
                        (a.throughput_tps - b.throughput_tps) / b.throughput_tps * 100
                    ) if b.throughput_tps > 0 else 0,
                    "ttft_before": b.ttft_ms,
                    "ttft_after": a.ttft_ms,
                    "ttft_change_pct": (
                        (a.ttft_ms - b.ttft_ms) / b.ttft_ms * 100
                    ) if b.ttft_ms > 0 else 0,
                    "tpot_before": b.tpot_ms,
                    "tpot_after": a.tpot_ms,
                    "tpot_change_pct": (
                        (a.tpot_ms - b.tpot_ms) / b.tpot_ms * 100
                    ) if b.tpot_ms > 0 else 0,
                    "peak_memory_before": b.peak_memory_mb,
                    "peak_memory_after": a.peak_memory_mb,
                    "peak_memory_change_pct": (
                        (a.peak_memory_mb - b.peak_memory_mb) / b.peak_memory_mb * 100
                    ) if b.peak_memory_mb > 0 else 0,
                }

        # Compare memory
        if baseline.memory and optimized.memory:
            comparison["memory"] = {
                "params_before": baseline.memory.total_parameter_mb,
                "params_after": optimized.memory.total_parameter_mb,
                "params_change_pct": (
                    (optimized.memory.total_parameter_mb - baseline.memory.total_parameter_mb)
                    / baseline.memory.total_parameter_mb * 100
                ),
                "activation_before": baseline.memory.activation_estimation_mb,
                "activation_after": optimized.memory.activation_estimation_mb,
                "kv_cache_before": baseline.memory.kv_cache_mb,
                "kv_cache_after": optimized.memory.kv_cache_mb,
                "peak_memory_before": baseline.memory.peak_allocated_mb,
                "peak_memory_after": optimized.memory.peak_allocated_mb,
            }

        result = SuiteResults(
            suite_name=f"comparison: {baseline.suite_name} vs {optimized.suite_name}",
            start_time=baseline.start_time,
            end_time=optimized.end_time,
            perplexity=optimized.perplexity,
            throughput=optimized.throughput,
            latency=optimized.latency,
            memory=optimized.memory,
            comparison=comparison,
        )

        return result

    def report_text(
        self,
        results: SuiteResults,
        detailed: bool = False,
    ) -> str:
        """
        Generate a human-readable report from suite results.

        Args:
            results: SuiteResults to report.
            detailed: If True, include per-scenario details.

        Returns:
            Formatted text report.
        """
        lines = [
            "=" * 70,
            f"Benchmark Suite: {results.suite_name}",
            "=" * 70,
            f"  Started:  {results.start_time}",
            f"  Finished: {results.end_time}",
            "",
            "Model Configuration:",
        ]

        for k, v in results.config_snapshot.items():
            lines.append(f"  {k}: {v}")

        if results.perplexity:
            lines.extend([
                "",
                "Perplexity:",
                f"  Perplexity: {results.perplexity['perplexity']:.4f}",
                f"  Loss:       {results.perplexity['loss']:.4f}",
                f"  Tokens:     {results.perplexity['num_tokens']:,}",
            ])

        if results.throughput and detailed:
            lines.extend(["", "Throughput Benchmarks:", "-" * 70])

            # Group by batch size
            for key, res in results.throughput.items():
                if "_latency" in key:
                    continue
                lines.append(f"\n  {key}:")
                lines.append(f"    Throughput: {res.throughput_tps:.2f} tokens/sec")
                lines.append(f"    Peak Mem:   {res.peak_memory_mb:.2f} MiB")

            lines.extend(["", "Latency Benchmarks:"])
            for key, res in results.throughput.items():
                if "_latency" in key:
                    scenario = key.replace("_latency", "")
                    lines.append(f"\n  {scenario}:")
                    lines.append(f"    TTFT: {res.ttft_ms:.2f} ms")
                    lines.append(f"    TPOT: {res.tpot_ms:.2f} ms")

        if results.latency and detailed:
            lines.extend([
                "",
                "Latency Profiling:",
                f"  Total forward (mean): {results.latency.total_stats.mean_ms:.3f} ms",
                f"  P50:  {results.latency.total_stats.median_ms:.3f} ms",
                f"  P90:  {results.latency.total_stats.p90_ms:.3f} ms",
                f"  P99:  {results.latency.total_stats.p99_ms:.3f} ms",
                f"  P99.9: {results.latency.total_stats.p999_ms:.3f} ms",
            ])

        if results.memory:
            lines.extend([
                "",
                "Memory:",
                f"  Model Size: {results.memory.model_size_mb:.2f} MiB",
                f"  Peak CUDA:  {results.memory.peak_allocated_mb:.2f} MiB",
            ])

        if results.comparison:
            lines.extend([
                "",
                "Comparison (Before vs After):",
                "-" * 70,
                f"{'Metric':<30} {'Before':>12} {'After':>12} {'Change':>10}",
                "-" * 70,
            ])
            for key, vals in results.comparison.items():
                if key == "perplexity":
                    lines.append(
                        f"{'Perplexity':<30} {vals['before']:>12.4f} {vals['after']:>12.4f} {vals['change_pct']:>+9.2f}%"
                    )
                elif key == "memory":
                    lines.append(
                        f"{'Params (MiB)':<30} {vals['params_before']:>12.2f} {vals['params_after']:>12.2f} {vals['params_change_pct']:>+9.2f}%"
                    )
                elif isinstance(vals, dict) and "throughput_before" in vals:
                    lines.append(
                        f"{'Throughput ' + key:<30} {vals['throughput_before']:>12.2f} {vals['throughput_after']:>12.2f} {vals['throughput_change_pct']:>+9.2f}%"
                    )

        lines.extend(["", "=" * 70])
        return "\n".join(lines)

    def export_json(
        self,
        results: SuiteResults,
        path: Union[str, Path],
    ) -> None:
        """
        Export suite results to a JSON file.

        Args:
            results: SuiteResults to export.
            path: Output file path.
        """
        data = asdict(results)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"Suite results exported to {path}")

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
