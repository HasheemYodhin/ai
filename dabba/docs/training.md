# Training Guide

## Quick Start

```python
from dabba import Dabba
from dabba.config import TrainingConfig, ModelConfig

# Load model
model = Dabba.from_preset("small")

# Configure training
training_config = TrainingConfig(
    learning_rate=3e-4,
    batch_size=4,
    num_epochs=3,
    warmup_steps=1000,
)

# Prepare data
train_data = [
    {"input_ids": [1, 2, 3, 4, 5], "labels": [2, 3, 4, 5, 6]},
    # ... more data
]

# Train
model.train(train_data, training_config)
```

## Data Preparation

Dabba provides a complete data processing pipeline:

### Text Cleaning
```python
from dabba.data import TextCleaner

cleaner = TextCleaner(
    remove_html=True,
    remove_urls=True,
    min_text_length=50,
)
cleaned_docs = cleaner.clean_batch(raw_docs)
```

### Deduplication
```python
from dabba.data import Deduplicator

dedup = Deduplicator(method="minhash", threshold=0.85)
unique_docs = dedup.deduplicate(cleaned_docs)
```

### Chunking and Packing
```python
from dabba.data import TextChunker, SequencePacker

chunker = TextChunker(chunk_size=512, strategy="paragraph")
packer = SequencePacker(max_length=2048)

chunks = chunker.chunk(large_document)
packed = packer.pack(chunks)
```

## Training Features

### Mixed Precision Training
```python
training_config = TrainingConfig(mixed_precision="bf16")  # or "fp16"
```

### Gradient Checkpointing
```python
training_config = TrainingConfig(gradient_checkpointing=True)
```

### Distributed Training
```bash
# Single node, multi-GPU
torchrun --nproc_per_node=4 train.py

# Multi-node
torchrun --nnodes=2 --nproc_per_node=8 train.py
```

### Checkpointing
```python
from dabba.trainer import save_checkpoint

# Auto-save during training
training_config = TrainingConfig(
    save_every_n_steps=1000,
    save_total_limit=5,
)
```

## Evaluation

```python
# Evaluate during training
eval_data = [
    {"input_ids": [1, 2, 3], "labels": [2, 3, 4]},
]
metrics = model.evaluate(eval_data)
print(metrics)
```

## Monitoring

### Metrics Tracking
```python
from dabba.trainer import MetricsTracker

tracker = MetricsTracker()
tracker.update("loss", 0.5)
tracker.update("accuracy", 0.85)
print(tracker.average("loss"))
```

### Logging
```python
training_config = TrainingConfig(
    log_interval=10,
    wandb_project="dabba-training",
)
```

## Fine-tuning

```python
# Load pretrained model
model = Dabba.from_pretrained("path/to/checkpoint")

# Fine-tune on new data
model.train(new_data, training_config)
```

## Best Practices

1. **Start with a small preset** (e.g., "tiny" or "small") to validate your pipeline
2. **Use gradient accumulation** to simulate larger batch sizes: `gradient_accumulation_steps=8`
3. **Monitor learning rate** with cosine scheduling and warmup
4. **Save checkpoints frequently** during long training runs
5. **Validate on a held-out set** every N steps
