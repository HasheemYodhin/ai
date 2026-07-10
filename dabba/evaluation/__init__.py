"""
Evaluation module for the dabba framework.

Provides tools for evaluating language model quality (perplexity),
measuring inference performance (benchmarking, latency profiling),
and analyzing memory usage.

Components:
    PerplexityEvaluator : Compute perplexity on validation datasets.
    Benchmark           : Throughput, latency, and resource utilization
                          measurement for inference.
    LatencyProfiler     : Per-layer and per-operation timing with
                          percentile reporting.
    MemoryProfiler      : Detailed memory usage breakdown across
                          parameters, activations, gradients, and KV cache.
    BenchmarkSuite      : Orchestrates all evaluations and generates
                          comprehensive reports.
"""

from dabba.evaluation.perplexity import PerplexityEvaluator
from dabba.evaluation.benchmark import Benchmark
from dabba.evaluation.latency import LatencyProfiler
from dabba.evaluation.memory_profile import MemoryProfiler
from dabba.evaluation.benchmark_suite import BenchmarkSuite

__all__ = [
    "PerplexityEvaluator",
    "Benchmark",
    "LatencyProfiler",
    "MemoryProfiler",
    "BenchmarkSuite",
]
