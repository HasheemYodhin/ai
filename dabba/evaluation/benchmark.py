"""
Performance benchmarking for transformer inference.

Measures key performance metrics:
    - Throughput (tokens/second)
    - Time-to-first-token (TTFT)
    - Time-per-output-token (TPOT)
    - Memory usage (CUDA peak and current)
    - GPU utilization via nvidia-smi polling
    - CPU/GPU timing separation

All measurements are performed with configurable warmup runs and
multiple trials for statistical significance.
"""

import csv
import json
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import torch

from dabba.model.transformer import Transformer
from dabba.config.model_config import ModelConfig


@dataclass
class BenchmarkResults:
    """
    Container for benchmark measurement results.

    Attributes:
        throughput_tps: Generated tokens per second.
        ttft_ms: Time-to-first-token in milliseconds.
        tpot_ms: Time-per-output-token in milliseconds.
        peak_memory_mb: Peak CUDA memory in MiB.
        avg_memory_mb: Average CUDA memory in MiB.
        gpu_utilization_pct: GPU utilization percentage.
        batch_size: Batch size used.
        input_length: Input sequence length.
        output_length: Generated sequence length.
        num_warmup: Number of warmup runs.
        num_trials: Number of measured trials.
        trial_times_ms: Per-trial wall times.
        timing_breakdown: Dict of CPU vs GPU timing.
        config_snapshot: Model configuration snapshot.
    """
    throughput_tps: float = 0.0
    ttft_ms: float = 0.0
    tpot_ms: float = 0.0
    peak_memory_mb: float = 0.0
    avg_memory_mb: float = 0.0
    gpu_utilization_pct: float = 0.0
    batch_size: int = 1
    input_length: int = 0
    output_length: int = 0
    num_warmup: int = 3
    num_trials: int = 5
    trial_times_ms: List[float] = field(default_factory=list)
    timing_breakdown: Dict[str, float] = field(default_factory=dict)
    config_snapshot: Dict[str, Union[int, float, str, bool, None]] = field(default_factory=dict)


class _GPUUtilMonitor:
    """
    Background thread that polls GPU utilization via nvidia-smi.

    Polls at a fixed interval and records the utilization percentage
    at each sample point. Reports the average at the end.
    """

    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self._samples: List[float] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the monitoring thread."""
        self._samples.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        """
        Stop the monitoring thread and return average utilization.

        Returns:
            Average GPU utilization percentage.
        """
        if self._thread is None:
            return 0.0
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        return self._average()

    def _poll(self) -> None:
        """Poll GPU utilization at regular intervals."""
        while not self._stop_event.is_set():
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi", "--query-gpu=utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
                if result.returncode == 0:
                    value = float(result.stdout.strip())
                    self._samples.append(value)
            except (subprocess.SubprocessError, ValueError, FileNotFoundError):
                pass
            self._stop_event.wait(self.interval)

    def _average(self) -> float:
        """Compute the average of collected samples."""
        if not self._samples:
            return 0.0
        return sum(self._samples) / len(self._samples)


class Benchmark:
    """
    Measure inference performance of a transformer model.

    Provides accurate measurements of throughput, latency, and resource
    utilization for autoregressive text generation. Includes warmup
    runs, multiple trials, and detailed reporting.

    Args:
        model: The transformer model to benchmark.
        device: Device to run on. Auto-detected if None.
        dtype: Torch dtype for inference.
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

        self._cuda_available = torch.cuda.is_available()
        if self._cuda_available:
            self._cuda_device = self.device.index or 0

    @torch.no_grad()
    def measure_throughput(
        self,
        input_length: int = 128,
        output_length: int = 128,
        batch_size: int = 1,
        num_warmup: int = 3,
        num_trials: int = 5,
    ) -> BenchmarkResults:
        """
        Measure generation throughput in tokens per second.

        Generates output_length tokens for each sequence in the batch
        and measures the total wall time. Throughput is calculated as
        (batch_size * output_length) / time.

        Args:
            input_length: Length of the prompt in tokens.
            output_length: Number of tokens to generate.
            batch_size: Number of sequences to generate in parallel.
            num_warmup: Number of warmup runs (not measured).
            num_trials: Number of measured trials.

        Returns:
            BenchmarkResults with throughput and timing data.
        """
        self._reset_memory_stats()
        dummy_input = torch.randint(
            0, self.model.config.vocab_size - 1,
            (batch_size, input_length),
            device=self.device,
        )

        gpu_mon = _GPUUtilMonitor()

        # Warmup
        for _ in range(num_warmup):
            self.model.generate(
                dummy_input,
                max_new_tokens=output_length,
                do_sample=False,
            )
        torch.cuda.synchronize() if self._cuda_available else None

        # Measured trials
        trial_times: List[float] = []
        gpu_mon.start()

        for _ in range(num_trials):
            start_event = torch.cuda.Event(enable_timing=True) if self._cuda_available else None
            end_event = torch.cuda.Event(enable_timing=True) if self._cuda_available else None

            if self._cuda_available:
                start_event.record()
            else:
                cpu_start = time.perf_counter()

            self.model.generate(
                dummy_input,
                max_new_tokens=output_length,
                do_sample=False,
            )

            if self._cuda_available:
                end_event.record()
                torch.cuda.synchronize()
                elapsed_ms = start_event.elapsed_time(end_event)
            else:
                elapsed_ms = (time.perf_counter() - cpu_start) * 1000

            trial_times.append(elapsed_ms)

        gpu_util = gpu_mon.stop()

        total_tokens = batch_size * output_length
        avg_time_ms = sum(trial_times) / len(trial_times)
        throughput = total_tokens / (avg_time_ms / 1000)

        peak_mem = self._get_peak_memory()

        results = BenchmarkResults(
            throughput_tps=throughput,
            ttft_ms=0.0,
            tpot_ms=avg_time_ms / output_length,
            peak_memory_mb=peak_mem,
            avg_memory_mb=self._get_current_memory(),
            gpu_utilization_pct=gpu_util,
            batch_size=batch_size,
            input_length=input_length,
            output_length=output_length,
            num_warmup=num_warmup,
            num_trials=num_trials,
            trial_times_ms=trial_times,
            config_snapshot=self._config_snapshot(),
        )

        return results

    @torch.no_grad()
    def measure_latency(
        self,
        input_length: int = 128,
        output_length: int = 128,
        batch_size: int = 1,
        num_warmup: int = 3,
        num_trials: int = 5,
    ) -> BenchmarkResults:
        """
        Measure generation latency including TTFT and TPOT.

        Time-to-first-token (TTFT) is the time to generate the first
        output token (includes the prompt processing).
        Time-per-output-token (TPOT) is the average time for each
        subsequent token.

        Args:
            input_length: Length of the prompt in tokens.
            output_length: Number of tokens to generate.
            batch_size: Number of sequences to generate in parallel.
            num_warmup: Number of warmup runs.
            num_trials: Number of measured trials.

        Returns:
            BenchmarkResults with TTFT, TPOT, and throughput.
        """
        self._reset_memory_stats()
        dummy_input = torch.randint(
            0, self.model.config.vocab_size - 1,
            (batch_size, input_length),
            device=self.device,
        )

        gpu_mon = _GPUUtilMonitor()

        # Warmup
        for _ in range(num_warmup):
            self.model.generate(
                dummy_input,
                max_new_tokens=output_length,
                do_sample=False,
            )
        torch.cuda.synchronize() if self._cuda_available else None

        # Measured trials
        trial_ttft: List[float] = []
        trial_tpot: List[float] = []
        trial_total: List[float] = []

        gpu_mon.start()

        for _ in range(num_trials):
            ttft, tpot, total = self._timed_generate(dummy_input, output_length)
            trial_ttft.append(ttft)
            trial_tpot.append(tpot)
            trial_total.append(total)

        gpu_util = gpu_mon.stop()

        avg_ttft = sum(trial_ttft) / len(trial_ttft)
        avg_tpot = sum(trial_tpot) / len(trial_tpot)
        avg_total = sum(trial_total) / len(trial_total)
        total_tokens = batch_size * output_length
        throughput = total_tokens / (avg_total / 1000)

        peak_mem = self._get_peak_memory()

        results = BenchmarkResults(
            throughput_tps=throughput,
            ttft_ms=avg_ttft,
            tpot_ms=avg_tpot,
            peak_memory_mb=peak_mem,
            avg_memory_mb=self._get_current_memory(),
            gpu_utilization_pct=gpu_util,
            batch_size=batch_size,
            input_length=input_length,
            output_length=output_length,
            num_warmup=num_warmup,
            num_trials=num_trials,
            trial_times_ms=trial_total,
            config_snapshot=self._config_snapshot(),
        )

        return results

    @torch.no_grad()
    def measure_prefill(
        self,
        input_length: int = 2048,
        batch_size: int = 1,
        num_warmup: int = 3,
        num_trials: int = 10,
    ) -> BenchmarkResults:
        """
        Measure prompt prefill (context processing) performance.

        The prefill phase processes all prompt tokens in parallel to
        build the initial KV cache. This is typically compute-bound.

        Args:
            input_length: Length of the prompt in tokens.
            batch_size: Number of prompts to process.
            num_warmup: Number of warmup runs.
            num_trials: Number of measured trials.

        Returns:
            BenchmarkResults with prefill throughput.
        """
        self._reset_memory_stats()
        dummy_input = torch.randint(
            0, self.model.config.vocab_size - 1,
            (batch_size, input_length),
            device=self.device,
        )

        gpu_mon = _GPUUtilMonitor()

        for _ in range(num_warmup):
            self.model(input_ids=dummy_input, use_cache=True)
        torch.cuda.synchronize() if self._cuda_available else None

        trial_times: List[float] = []
        gpu_mon.start()

        for _ in range(num_trials):
            if self._cuda_available:
                start_event = torch.cuda.Event(enable_timing=True)
                end_event = torch.cuda.Event(enable_timing=True)
                start_event.record()
                self.model(input_ids=dummy_input, use_cache=True)
                end_event.record()
                torch.cuda.synchronize()
                elapsed_ms = start_event.elapsed_time(end_event)
            else:
                cpu_start = time.perf_counter()
                self.model(input_ids=dummy_input, use_cache=True)
                elapsed_ms = (time.perf_counter() - cpu_start) * 1000
            trial_times.append(elapsed_ms)

        gpu_util = gpu_mon.stop()

        total_tokens = batch_size * input_length
        avg_time_ms = sum(trial_times) / len(trial_times)
        throughput = total_tokens / (avg_time_ms / 1000)

        results = BenchmarkResults(
            throughput_tps=throughput,
            ttft_ms=trial_times[0] if trial_times else 0.0,
            tpot_ms=0.0,
            peak_memory_mb=self._get_peak_memory(),
            avg_memory_mb=self._get_current_memory(),
            gpu_utilization_pct=gpu_util,
            batch_size=batch_size,
            input_length=input_length,
            output_length=0,
            num_warmup=num_warmup,
            num_trials=num_trials,
            trial_times_ms=trial_times,
            config_snapshot=self._config_snapshot(),
        )

        return results

    @torch.no_grad()
    def measure_decode(
        self,
        output_length: int = 128,
        batch_size: int = 1,
        input_length: int = 128,
        num_warmup: int = 3,
        num_trials: int = 10,
    ) -> BenchmarkResults:
        """
        Measure decode (token-by-token generation) performance.

        This isolates the memory-bound decode phase by pre-filling the
        KV cache first, then measuring only the autoregressive token
        generation.

        Args:
            output_length: Number of tokens to generate.
            batch_size: Number of sequences.
            input_length: Prompt length for prefill.
            num_warmup: Number of warmup runs.
            num_trials: Number of measured trials.

        Returns:
            BenchmarkResults with decode throughput and TPOT.
        """
        self._reset_memory_stats()
        dummy_input = torch.randint(
            0, self.model.config.vocab_size - 1,
            (batch_size, input_length),
            device=self.device,
        )

        gpu_mon = _GPUUtilMonitor()

        def decode_step(input_ids, past_kv, temperature=0.0):
            """Single decode step."""
            outputs = self.model(
                input_ids=input_ids,
                past_key_values=past_kv,
                use_cache=True,
            )
            logits = outputs["logits"][:, -1, :]
            next_token = logits.argmax(dim=-1, keepdim=True)
            return next_token, outputs["past_key_values"]

        # Warmup
        for _ in range(num_warmup):
            past_kv = None
            outputs = self.model(input_ids=dummy_input, use_cache=True)
            past_kv = outputs["past_key_values"]
            next_input = outputs["logits"][:, -1, :].argmax(dim=-1, keepdim=True)
            for _ in range(output_length):
                next_input, past_kv = decode_step(next_input, past_kv)
        torch.cuda.synchronize() if self._cuda_available else None

        trial_times: List[float] = []
        gpu_mon.start()

        for _ in range(num_trials):
            past_kv = None
            outputs = self.model(input_ids=dummy_input, use_cache=True)
            past_kv = outputs["past_key_values"]
            next_input = outputs["logits"][:, -1, :].argmax(dim=-1, keepdim=True)

            if self._cuda_available:
                start_event = torch.cuda.Event(enable_timing=True)
                end_event = torch.cuda.Event(enable_timing=True)
                start_event.record()
            else:
                cpu_start = time.perf_counter()

            for _ in range(output_length):
                next_input, past_kv = decode_step(next_input, past_kv)

            if self._cuda_available:
                end_event.record()
                torch.cuda.synchronize()
                elapsed_ms = start_event.elapsed_time(end_event)
            else:
                elapsed_ms = (time.perf_counter() - cpu_start) * 1000

            trial_times.append(elapsed_ms)

        gpu_util = gpu_mon.stop()

        total_tokens = batch_size * output_length
        avg_time_ms = sum(trial_times) / len(trial_times)
        throughput = total_tokens / (avg_time_ms / 1000)
        tpot = avg_time_ms / output_length

        results = BenchmarkResults(
            throughput_tps=throughput,
            ttft_ms=0.0,
            tpot_ms=tpot,
            peak_memory_mb=self._get_peak_memory(),
            avg_memory_mb=self._get_current_memory(),
            gpu_utilization_pct=gpu_util,
            batch_size=batch_size,
            input_length=input_length,
            output_length=output_length,
            num_warmup=num_warmup,
            num_trials=num_trials,
            trial_times_ms=trial_times,
            config_snapshot=self._config_snapshot(),
        )

        return results

    def _timed_generate(
        self,
        input_ids: torch.LongTensor,
        max_new_tokens: int,
    ) -> Tuple[float, float, float]:
        """
        Time a generation with TTFT/TPOT separation.

        Args:
            input_ids: Prompt token IDs.
            max_new_tokens: Number of tokens to generate.

        Returns:
            Tuple of (ttft_ms, tpot_ms, total_ms).
        """
        batch_size = input_ids.size(0)
        past_kv = None

        # Prefill (timed separately)
        if self._cuda_available:
            prefill_start = torch.cuda.Event(enable_timing=True)
            prefill_end = torch.cuda.Event(enable_timing=True)
            prefill_start.record()
        else:
            cpu_start = time.perf_counter()

        outputs = self.model(input_ids=input_ids, use_cache=True)
        past_kv = outputs["past_key_values"]
        next_input = outputs["logits"][:, -1, :].argmax(dim=-1, keepdim=True)

        if self._cuda_available:
            prefill_end.record()
            torch.cuda.synchronize()
            ttft_ms = prefill_start.elapsed_time(prefill_end)
        else:
            ttft_ms = (time.perf_counter() - cpu_start) * 1000

        # Decode (timed)
        if self._cuda_available:
            decode_start = torch.cuda.Event(enable_timing=True)
            decode_end = torch.cuda.Event(enable_timing=True)
            decode_start.record()
        else:
            cpu_start = time.perf_counter()

        for _ in range(max_new_tokens - 1):
            outputs = self.model(
                input_ids=next_input,
                past_key_values=past_kv,
                use_cache=True,
            )
            past_kv = outputs["past_key_values"]
            next_input = outputs["logits"][:, -1, :].argmax(dim=-1, keepdim=True)

        if self._cuda_available:
            decode_end.record()
            torch.cuda.synchronize()
            decode_ms = decode_start.elapsed_time(decode_end)
        else:
            decode_ms = (time.perf_counter() - cpu_start) * 1000

        tpot_ms = decode_ms / (max_new_tokens - 1) if max_new_tokens > 1 else 0.0
        total_ms = ttft_ms + decode_ms

        return ttft_ms, tpot_ms, total_ms

    def _reset_memory_stats(self) -> None:
        """Reset CUDA memory statistics for accurate measurement."""
        if self._cuda_available:
            torch.cuda.reset_peak_memory_stats(self._cuda_device)
            torch.cuda.empty_cache()

    def _get_peak_memory(self) -> float:
        """
        Get peak CUDA memory usage in MiB.

        Returns:
            Peak memory in MiB.
        """
        if not self._cuda_available:
            return 0.0
        return torch.cuda.max_memory_allocated(self._cuda_device) / (1024 ** 2)

    def _get_current_memory(self) -> float:
        """
        Get current CUDA memory usage in MiB.

        Returns:
            Current memory in MiB.
        """
        if not self._cuda_available:
            return 0.0
        return torch.cuda.memory_allocated(self._cuda_device) / (1024 ** 2)

    def _config_snapshot(self) -> Dict[str, Union[int, float, str, bool, None]]:
        """
        Capture a snapshot of the model configuration.

        Returns:
            Dictionary of configuration parameters.
        """
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

    def export_json(
        self,
        results: BenchmarkResults,
        path: Union[str, Path],
    ) -> None:
        """
        Export benchmark results to a JSON file.

        Args:
            results: BenchmarkResults to export.
            path: Output file path.
        """
        data = asdict(results)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"Results exported to {path}")

    def summary(self, results: BenchmarkResults) -> str:
        """
        Generate a human-readable summary of benchmark results.

        Args:
            results: BenchmarkResults to summarize.

        Returns:
            Formatted summary string.
        """
        lines = [
            "=" * 60,
            "Benchmark Results",
            "=" * 60,
            f"  Batch size:          {results.batch_size}",
            f"  Input length:        {results.input_length}",
            f"  Output length:       {results.output_length}",
            f"  Warmup runs:         {results.num_warmup}",
            f"  Trials:              {results.num_trials}",
            "",
            "  Throughput:          {:.2f} tokens/sec".format(
                results.throughput_tps
            ),
            "  TTFT:                {:.2f} ms".format(results.ttft_ms),
            "  TPOT:                {:.2f} ms".format(results.tpot_ms),
            "",
            "  Peak GPU memory:     {:.2f} MiB".format(results.peak_memory_mb),
            "  Avg GPU memory:      {:.2f} MiB".format(results.avg_memory_mb),
            "  GPU utilization:     {:.1f}%".format(results.gpu_utilization_pct),
            "",
            "  Trial times (ms):    " + ", ".join(
                f"{t:.1f}" for t in results.trial_times_ms
            ),
            "-" * 60,
        ]
        return "\n".join(lines)

    def compare(
        self,
        before: BenchmarkResults,
        after: BenchmarkResults,
    ) -> str:
        """
        Compare two benchmark results side by side.

        Args:
            before: Baseline results.
            after: Optimized results.

        Returns:
            Formatted comparison string.
        """
        def pct(a, b):
            if a == 0:
                return float("inf")
            return (b - a) / a * 100

        lines = [
            "=" * 60,
            "Benchmark Comparison (Before vs After)",
            "=" * 60,
            f"{'Metric':<25} {'Before':>10} {'After':>10} {'Change':>10}",
            "-" * 60,
            f"{'Throughput (t/s)':<25} {before.throughput_tps:>10.2f} {after.throughput_tps:>10.2f} {pct(before.throughput_tps, after.throughput_tps):>+9.1f}%",
            f"{'TTFT (ms)':<25} {before.ttft_ms:>10.2f} {after.ttft_ms:>10.2f} {pct(before.ttft_ms, after.ttft_ms):>+9.1f}%",
            f"{'TPOT (ms)':<25} {before.tpot_ms:>10.2f} {after.tpot_ms:>10.2f} {pct(before.tpot_ms, after.tpot_ms):>+9.1f}%",
            f"{'Peak mem (MiB)':<25} {before.peak_memory_mb:>10.2f} {after.peak_memory_mb:>10.2f} {pct(before.peak_memory_mb, after.peak_memory_mb):>+9.1f}%",
            "-" * 60,
        ]
        return "\n".join(lines)
