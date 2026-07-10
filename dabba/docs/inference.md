# Inference Guide

## Overview

Dabba provides flexible text generation with support for various sampling strategies, beam search, and streaming.

## Quick Start

```python
from dabba import Dabba

# Load model
model = Dabba.from_preset("small")

# Generate text
response = model.generate(
    "The future of artificial intelligence",
    max_length=200,
    temperature=0.7,
)
print(response)
```

## Generation Configuration

```python
from dabba.inference import GenerationConfig

config = GenerationConfig(
    max_length=200,
    min_length=10,
    temperature=0.8,
    top_k=50,
    top_p=0.9,
    do_sample=True,
    repetition_penalty=1.1,
    no_repeat_ngram_size=3,
    num_beams=1,
)
```

## Sampling Strategies

### Greedy Sampling
Always picks the most likely token:
```python
output = model.generate("Text", do_sample=False)
```

### Temperature Sampling
Controls randomness (lower = more deterministic):
```python
output = model.generate("Text", temperature=0.7, do_sample=True)
```

### Top-K Sampling
Limits to top K most likely tokens:
```python
output = model.generate("Text", top_k=40, do_sample=True)
```

### Top-P (Nucleus) Sampling
Limits to tokens with cumulative probability P:
```python
output = model.generate("Text", top_p=0.9, do_sample=True)
```

### Combined Sampling
```python
output = model.generate(
    "Text",
    temperature=0.8,
    top_k=50,
    top_p=0.9,
    do_sample=True,
)
```

## Beam Search

```python
from dabba.inference import BeamSearch

beam = BeamSearch(
    model=model,
    num_beams=4,
    max_length=100,
    early_stopping=True,
    no_repeat_ngram_size=2,
)
output = beam.search(input_ids)
```

## Streaming

### Token-by-token streaming
```python
for token in model.generate_stream("Tell me a story", max_length=100):
    print(token, end="", flush=True)
```

### Using StreamingHandler
```python
from dabba.inference import StreamingHandler

handler = StreamingHandler()

def on_token(token):
    print(token, end="", flush=True)

handler.on_next_token = on_token

for token in model.generate_stream("Once upon a time", max_length=200):
    handler.on_next_token(token)
```

## Batch Generation

```python
prompts = [
    "The capital of France is",
    "The meaning of life is",
    "The best programming language",
]
outputs = model.generate_batch(prompts, max_length=50)
for prompt, output in zip(prompts, outputs):
    print(f"{prompt} {output}")
```

## Constrained Generation

### Repetition Penalty
```python
output = model.generate("Text", repetition_penalty=1.2)
```

### No Repeat N-gram
```python
output = model.generate("Text", no_repeat_ngram_size=3)
```

### Min/Max Length
```python
output = model.generate("Text", min_length=50, max_length=200)
```

## Performance Tips

1. **Use KV cache** for faster autoregressive generation
2. **Use beam search** for higher quality but slower generation
3. **Use streaming** for real-time applications
4. **Batch prompts** for throughput
5. **Reduce max_length** for faster responses

## GPU/CPU Inference

```python
# CPU
model = Dabba.from_preset("small", device="cpu")

# GPU
model = Dabba.from_preset("small", device="cuda")

# Half precision (faster on GPU)
model = Dabba.from_preset("small", device="cuda", dtype="float16")
```
