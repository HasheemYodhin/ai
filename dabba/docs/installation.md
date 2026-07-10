# Installation Guide

## Prerequisites

- Python 3.10 or higher
- CUDA-capable GPU (optional, for training)
- 8GB+ RAM (16GB+ recommended for training)

## Install from Source

```bash
git clone https://github.com/yourusername/dabba.git
cd dabba
pip install -e .
```

## Install with Dependencies

### Core dependencies
```bash
pip install -e ".[core]"
```

### Training dependencies (includes CUDA support)
```bash
pip install -e ".[train]"
```

### All dependencies
```bash
pip install -e ".[all]"
```

## Docker Installation

```bash
# Build the image
docker build -t dabba .

# Run with GPU support
docker run --gpus all -p 8000:8000 dabba
```

## Verify Installation

```python
from dabba import Dabba

# Should print successfully
print("Dabba installed successfully!")

# Load a small model
model = Dabba.from_preset("tiny")
print(f"Model loaded with {model.get_num_params():,} parameters")
```

## Optional Dependencies

- **ChromaDB**: For vector storage (`pip install chromadb`)
- **Sentence Transformers**: For embeddings (`pip install sentence-transformers`)
- **Whisper**: For audio transcription (`pip install openai-whisper`)
- **Flash Attention**: For optimized attention (`pip install flash-attn`)

## Troubleshooting

### CUDA not available
If you don't have a GPU, Dabba will fall back to CPU. For training, this will be slow.

### Out of memory
Reduce model size by using a smaller preset or adjust `max_position_embeddings` in config.

### Import errors
Ensure all dependencies are installed: `pip install -e ".[all]"`

## Development Setup

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Format code
black src/ tests/
ruff check src/ tests/
```
