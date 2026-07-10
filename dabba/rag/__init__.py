"""
RAG (Retrieval-Augmented Generation) pipeline for dabba.

Provides a modular pipeline for embedding, indexing, retrieving,
re-ranking, and generating answers grounded in external documents.
"""

from dabba.rag.embedding_model import EmbeddingModel
from dabba.rag.vector_store import VectorStore, ChromaVectorStore, FAISSVectorStore
from dabba.rag.document_indexer import DocumentIndexer
from dabba.rag.retriever import Retriever
from dabba.rag.reranker import Reranker
from dabba.rag.hybrid_search import HybridSearch
from dabba.rag.rag_pipeline import RagPipeline
from dabba.config.rag_config import RagConfig

RAGPipeline = RagPipeline
RAGConfig = RagConfig

__all__ = [
    "EmbeddingModel",
    "VectorStore",
    "ChromaVectorStore",
    "FAISSVectorStore",
    "DocumentIndexer",
    "Retriever",
    "Reranker",
    "HybridSearch",
    "RagPipeline",
    "RagConfig",
    "RAGPipeline",
    "RAGConfig",
]
