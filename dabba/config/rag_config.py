"""
RAG (Retrieval-Augmented Generation) configuration.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class RagConfig:
    """
    Configuration for the RAG pipeline: embedding model, vector store,
    retrieval parameters, and re-ranking.
    """

    # Embedding model
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32
    normalize_embeddings: bool = True

    # Vector store
    vector_store_type: str = "chroma"  # "chroma", "faiss", "pinecone"
    vector_store_path: str = "./vector_store"
    collection_name: str = "dabba_documents"

    # Pinecone config (if used)
    pinecone_api_key: Optional[str] = None
    pinecone_environment: Optional[str] = None
    pinecone_index_name: Optional[str] = None

    # Retrieval
    top_k: int = 5
    retrieval_mode: str = "dense"  # "dense", "sparse", "hybrid"
    similarity_metric: str = "cosine"  # "cosine", "dot", "euclidean"
    score_threshold: Optional[float] = None

    # Re-ranker
    use_reranker: bool = True
    reranker_model_name: str = "BAAI/bge-reranker-small"
    reranker_device: str = "cpu"
    rerank_top_k: int = 3

    # BM25 (sparse retrieval)
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    # Hybrid search
    hybrid_search_alpha: float = 0.5
    rrf_k: int = 60
    fusion_method: str = "linear"  # "linear" or "rrf"

    # FAISS config (if vector_store_type == "faiss")
    faiss_index_path: Optional[str] = None

    # Chunking for indexing
    chunk_size: int = 512
    chunk_overlap: int = 64

    # Document types supported
    supported_extensions: List[str] = field(
        default_factory=lambda: [".txt", ".md", ".pdf", ".json", ".jsonl", ".csv"]
    )

    max_file_size_mb: int = 50
