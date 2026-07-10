# Retrieval Augmented Generation (RAG)

## Overview

Dabba's RAG pipeline grounds model responses in retrieved documents, enabling factual and up-to-date answers by combining retrieval with generation.

## Architecture

```
User Query
    │
    ▼
┌─────────────┐     ┌──────────────┐
│  Embedding   │────▶│ Vector Store │
│   Model      │     │  (ChromaDB)  │
└─────────────┘     └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Retriever   │
                    │  (Hybrid)    │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Reranker    │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   LLM +      │
                    │  Context     │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   Response   │
                    └──────────────┘
```

## Quick Start

```python
from dabba.rag import RAGPipeline

# Create pipeline
rag = RAGPipeline(
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    top_k=5,
)

# Add documents
rag.add_documents([
    {"text": "Dabba is a modular LLM framework.", "metadata": {"source": "docs"}},
    {"text": "RAG improves factual accuracy.", "metadata": {"source": "paper"}},
])

# Query
result = rag.query("What is Dabba?")
print(result["answer"])  # Generated answer
print(result["documents"])  # Retrieved sources
```

## Components

### Embedding Model
```python
from dabba.rag.embedding import EmbeddingModel

model = EmbeddingModel(model_name="all-MiniLM-L6-v2")
embeddings = model.encode(["text1", "text2"])
print(embeddings.shape)  # (2, 384)
```

### Vector Store
```python
from dabba.rag.vector_store import VectorStore

store = VectorStore(dimension=384, metric="cosine")
store.add(embeddings, metadata=[{"id": i} for i in range(10)])
results = store.search(query_embedding, k=5)
```

### Hybrid Retrieval

Combines semantic search with keyword (BM25) search:

```python
from dabba.rag.hybrid import HybridRetriever

retriever = HybridRetriever(
    vector_store=store,
    alpha=0.5,  # Balance between semantic (1.0) and keyword (0.0)
)
results = retriever.search("query", alpha=0.7, k=5)
```

### Reranker

Improves retrieval quality by re-ranking with a cross-encoder:

```python
from dabba.rag.reranker import Reranker

reranker = Reranker(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
reranked = reranker.rerank(query, documents, top_k=3)
```

## Configuration

```python
from dabba.rag import RAGConfig

config = RAGConfig(
    top_k=5,
    embedding_dim=384,
    similarity_metric="cosine",
    rerank_enabled=True,
    chunk_size=512,
    chunk_overlap=50,
)
```

## Advanced Usage

### Custom Embedding Model
```python
rag = RAGPipeline(
    embedding_model="your-custom-model",
    embedding_dim=768,
)
```

### Batch Document Addition
```python
docs = [
    {"text": f"Document {i}", "metadata": {"id": i}}
    for i in range(1000)
]
rag.add_documents(docs, batch_size=100)
```

### Persistent Vector Store
```python
store = VectorStore(dimension=384)
store.add(embeddings)
store.save("vectors.npz")

# Later
loaded = VectorStore.load("vectors.npz")
```
