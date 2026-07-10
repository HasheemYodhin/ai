"""
Inference engine for text generation with trained transformer models.

Provides sampling strategies (top-K, top-P, temperature), beam search,
greedy decoding, and streaming token generation.
"""

from dabba.inference.generator import Generator, GenerationConfig
from dabba.inference.samplers import (
    Sampler, SamplerBase, TopKSampler, TopPSampler, TemperatureSampler,
    GreedySampler, BeamSampler,
)
from dabba.inference.beam_search import BeamSearch
from dabba.inference.streaming import StreamingGenerator, StreamingHandler

__all__ = [
    "Generator",
    "GenerationConfig",
    "Sampler",
    "SamplerBase",
    "TopKSampler",
    "TopPSampler",
    "TemperatureSampler",
    "GreedySampler",
    "BeamSampler",
    "BeamSearch",
    "StreamingGenerator",
    "StreamingHandler",
]
