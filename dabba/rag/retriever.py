"""
Document retrieval module.

Provides dense retrieval via embedding similarity against a vector store,
with configurable top-k and score threshold filtering.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import numpy.typing as npt

from dabba.config.rag_config import RagConfig
from dabba.rag.embedding_model import EmbeddingModel
from dabba.rag.vector_store import SearchResult, VectorStore
from dabba.utils.logging import get_logger

logger = get_logger("dabba.rag.retriever")


class Retriever:
    """
    Dense retriever that finds documents relevant to a query.

    Encodes the query using an EmbeddingModel, searches a VectorStore
    with the resulting embedding, and returns ranked results.

    Usage:
        retriever = Retriever(embedding_model, vector_store, top_k=5)
        results = retriever.retrieve("What is the capital of France?")
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        config: Optional[RagConfig] = None,
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> None:
        """
        Initialize the retriever.

        Args:
            embedding_model: Model used to encode queries.
            vector_store: Vector database to search against.
            config: RAG configuration. If provided, top_k and
                score_threshold override the passed-in values.
            top_k: Number of top results to retrieve.
            score_threshold: Minimum similarity score for results.
        """
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.config = config

        if config is not None:
            self.top_k = config.top_k
            self.score_threshold = config.score_threshold
        else:
            self.top_k = top_k
            self.score_threshold = score_threshold

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
        return_scores: bool = True,
    ) -> List[SearchResult]:
        """
        Retrieve documents relevant to the given query.

        The query is encoded using the embedding model, then the vector
        store is searched for the nearest neighbours.

        Args:
            query: Natural language query string.
            top_k: Override the default number of results.
            score_threshold: Override the default score threshold.
            filter_criteria: Optional metadata filters passed to the
                vector store.
            return_scores: If True (default), scores are populated in
                the results.

        Returns:
            List of SearchResult objects sorted by relevance (descending score).
        """
        if not query or not query.strip():
            return []

        effective_top_k = top_k if top_k is not None else self.top_k
        effective_threshold = (
            score_threshold
            if score_threshold is not None
            else self.score_threshold
        )

        query_embedding = self.embedding_model.encode_queries([query])[0]

        results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=effective_top_k,
            score_threshold=effective_threshold,
            filter_criteria=filter_criteria,
        )

        if not return_scores:
            for r in results:
                r.score = 0.0

        logger.debug(
            "Retrieved %d results for query (top_k=%d, threshold=%s)",
            len(results),
            effective_top_k,
            effective_threshold,
        )
        return results

    def retrieve_batch(
        self,
        queries: List[str],
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
    ) -> List[List[SearchResult]]:
        """
        Retrieve documents for multiple queries in batch.

        Args:
            queries: List of query strings.
            top_k: Override the default number of results.
            score_threshold: Override the default score threshold.
            filter_criteria: Optional metadata filters.

        Returns:
            List of result lists, one per query.
        """
        if not queries:
            return []

        query_embeddings = self.embedding_model.encode_queries(queries)
        effective_top_k = top_k if top_k is not None else self.top_k
        effective_threshold = (
            score_threshold
            if score_threshold is not None
            else self.score_threshold
        )

        all_results: List[List[SearchResult]] = []
        for q_emb in query_embeddings:
            results = self.vector_store.search(
                query_embedding=q_emb,
                top_k=effective_top_k,
                score_threshold=effective_threshold,
                filter_criteria=filter_criteria,
            )
            all_results.append(results)

        return all_results

    def get_document_by_id(self, doc_id: str) -> Any:
        """
        Retrieve a single document by its ID from the vector store.

        Not all vector store backends support direct ID lookup. This method
        returns None if the backend does not support it.

        Args:
            doc_id: Document identifier.

        Returns:
            The Document object if found, or None.
        """
        # Attempt to use ChromaDB's get method if available.
        vs = self.vector_store
        if hasattr(vs, "_collection") and vs._collection is not None:
            try:
                result = vs._collection.get(ids=[doc_id])
                if result["ids"]:
                    from dabba.rag.vector_store import Document

                    return Document(
                        id=result["ids"][0],
                        text=result["documents"][0],
                        metadata=result["metadatas"][0] if result["metadatas"] else {},
                    )
            except Exception:
                pass
        return None
