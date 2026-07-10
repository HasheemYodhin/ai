#!/usr/bin/env python3

"""
dabba — A production-grade open-source foundation model training framework.

Dabba provides a complete toolkit for building, training, and deploying
decoder-only transformer language models from scratch. It supports model
sizes from 10M to 7B+ parameters with custom BPE tokenization, streaming
data pipelines, distributed training, and a full inference engine.

Architecture:
    Config System → Data Pipeline → Model → Training Engine → Inference

Core Components:
    config      : YAML-driven configuration for model, training, and data
    tokenizer   : BPE tokenizer trained from scratch
    data        : Streaming dataset with packing, shuffling, and masking
    model       : Decoder-only transformer (RoPE, GQA, SwiGLU, RMSNorm)
    trainer     : Training loop with AdamW, AMP, checkpointing, logging
    inference   : Text generation with sampling, beam search, streaming
    rag         : Retrieval-Augmented Generation pipeline
    agent       : MCP-based agent with tool calling and planning
    multimodal  : Vision, audio, and video input processing
    api         : FastAPI server with OpenAI-compatible endpoints
"""

__version__ = "0.1.0"
