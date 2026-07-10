# Dabba Documentation

Welcome to the Dabba documentation. Dabba is a modular, scalable Large Language Model (LLM) built for research and production use.

## Table of Contents

- [Installation](installation.md) - How to install and set up Dabba
- [Configuration](configuration.md) - Configuration options and presets
- [Training](training.md) - How to train and fine-tune models
- [RAG Pipeline](rag.md) - Retrieval Augmented Generation
- [Inference](inference.md) - Model inference and generation
- [API Reference](api.md) - REST API endpoints
- [Deployment](deployment.md) - Docker and production deployment

## Overview

Dabba provides:

- **Transformer-based LLM** with support for multi-head, grouped-query, and multi-query attention
- **Efficient tokenization** with BPE tokenizer supporting byte-level encoding
- **Comprehensive training pipeline** with gradient checkpointing, mixed precision, and distributed training
- **RAG pipeline** for grounded generation with vector stores and hybrid search
- **Modular agent system** with tool registry and MCP support
- **Multimodal capabilities** supporting images and audio
- **FastAPI server** with OpenAI-compatible API endpoints
- **Production-ready** with Docker support and monitoring

## Quick Start

```python
from dabba import Dabba
from dabba.config import ModelConfig

# Load a small model
model = Dabba.from_preset("small")

# Generate text
response = model.generate("The future of AI is")
print(response)
```

## Architecture

Dabba follows a modular architecture with the following components:

```
dabba/
├── config/         # Configuration management
├── tokenizer/      # BPE tokenization
├── data/           # Data processing pipeline
├── model/          # Transformer model
├── trainer/        # Training loop
├── inference/      # Generation & sampling
├── rag/            # RAG pipeline
├── agent/          # Agent system
├── api/            # REST API server
├── multimodal/     # Image & audio processing
└── utils/          # Shared utilities
```

## License

Dabba is released under the MIT License.
