# Configuration Guide

## Overview

Dabba uses Pydantic-based configuration with hierarchical config classes. Configurations can be loaded from YAML, JSON, or Python dicts.

## Model Configuration

```python
from dabba.config import ModelConfig

config = ModelConfig(
    vocab_size=32000,
    hidden_size=768,
    num_layers=12,
    num_attention_heads=12,
    num_key_value_heads=4,  # GQA
    intermediate_size=3072,
    max_position_embeddings=2048,
    attention_dropout=0.1,
    hidden_dropout=0.1,
    activation="silu",
    normalization="rmsnorm",
)
```

### Config Presets

```python
from dabba.config import ModelConfig

# Available presets: tiny, small, base, medium, large, xl, xxl
config = ModelConfig.from_preset("small")

print(config)  # Shows all parameters for the "small" preset
```

| Preset | Parameters | Hidden Size | Layers | Heads | KV Heads |
|--------|-----------|-------------|--------|-------|----------|
| tiny   | 8M        | 256         | 4      | 4     | 2        |
| small  | 35M       | 512         | 8      | 8     | 4        |
| base   | 125M      | 768         | 12     | 12    | 4        |
| medium | 350M      | 1024        | 24     | 16    | 8        |
| large  | 780M      | 1536        | 24     | 16    | 8        |
| xl     | 1.5B      | 2048        | 32     | 32    | 8        |
| xxl    | 7B        | 4096        | 32     | 32    | 8        |

## Training Configuration

```python
from dabba.config import TrainingConfig

training_config = TrainingConfig(
    learning_rate=3e-4,
    batch_size=4,
    num_epochs=3,
    warmup_steps=1000,
    weight_decay=0.1,
    gradient_accumulation_steps=8,
    max_grad_norm=1.0,
    scheduler="cosine",
    optimizer="adamw",
    mixed_precision="bf16",
)
```

## Data Configuration

```python
from dabba.config import DataConfig

data_config = DataConfig(
    max_seq_length=2048,
    min_text_length=50,
    chunk_size=512,
    chunk_overlap=50,
    dedup_method="minhash",
    dedup_threshold=0.85,
)
```

## Inference Configuration

```python
from dabba.inference import GenerationConfig

gen_config = GenerationConfig(
    max_length=200,
    temperature=0.7,
    top_k=50,
    top_p=0.9,
    do_sample=True,
    repetition_penalty=1.1,
)
```

## RAG Configuration

```python
from dabba.rag import RAGConfig

rag_config = RAGConfig(
    top_k=5,
    embedding_dim=384,
    similarity_metric="cosine",
    rerank_enabled=True,
)
```

## Agent Configuration

```python
from dabba.agent import AgentConfig

agent_config = AgentConfig(
    system_prompt="You are a helpful assistant.",
    max_iterations=10,
    max_tool_calls=25,
)
```

## Loading from File

```yaml
# config.yaml
model:
  vocab_size: 32000
  hidden_size: 768
  num_layers: 12

training:
  learning_rate: 3e-4
  batch_size: 4
```

```python
from dabba.utils.config_loader import load_config

config = load_config("config.yaml")
```
