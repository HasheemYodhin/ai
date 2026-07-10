"""
Hybrid dense + sparse search.

Combines dense retrieval (embedding similarity) with sparse retrieval
(BM25) using configurable weighting and Reciprocal Rank Fusion (RRF)
for result combination.
"""

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np
import numpy.typing as npt

from dabba.config.rag_config import RagConfig
from dabba.rag.embedding_model import EmbeddingModel
from dabba.rag.vector_store import SearchResult, VectorStore
from dabba.utils.logging import get_logger

logger = get_logger("dabba.rag.hybrid")


class BM25SparseRetriever:
    """
    BM25 sparse retrieval using a best-matching algorithm.

    Implements the BM25+ variant for improved term frequency saturation
    and document length normalization.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        delta: float = 0.5,
    ) -> None:
        """
        Initialize the BM25 retriever.

        Args:
            k1: Term frequency saturation parameter.
            b: Length normalization parameter (0 = no normalization, 1 = full).
            delta: BM25+ delta parameter for non-retrieved term adjustment.
        """
        self.k1 = k1
        self.b = b
        self.delta = delta

        self._doc_freqs: Dict[str, Dict[str, int]] = {}
        self._doc_lengths: Dict[str, int] = {}
        self._term_doc_freq: Dict[str, int] = {}
        self._total_docs: int = 0
        self._avg_doc_length: float = 0.0
        self._doc_texts: Dict[str, str] = {}
        self._doc_metadata: Dict[str, Dict[str, Any]] = {}
        self._doc_ids: List[str] = []
        self._fitted: bool = False

    def index(
        self,
        documents: List[Any],
    ) -> None:
        """
        Index a list of documents for BM25 retrieval.

        Args:
            documents: List of objects with .id, .text, and .metadata attributes.
        """
        self._doc_freqs = {}
        self._doc_lengths = {}
        self._term_doc_freq = defaultdict(int)
        self._doc_texts = {}
        self._doc_metadata = {}
        self._doc_ids = []

        total_length = 0

        for doc in documents:
            doc_id = doc.id
            text = doc.text
            tokens = text.lower().split()

            self._doc_ids.append(doc_id)
            self._doc_texts[doc_id] = text
            self._doc_metadata[doc_id] = doc.metadata

            doc_freq: Dict[str, int] = {}
            for token in tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1

            self._doc_freqs[doc_id] = doc_freq
            self._doc_lengths[doc_id] = len(tokens)
            total_length += len(tokens)

            for token in set(tokens):
                self._term_doc_freq[token] += 1

        self._total_docs = len(documents)
        self._avg_doc_length = total_length / self._total_docs if self._total_docs > 0 else 0.0
        self._fitted = True

        logger.debug(
            "BM25 index built: %d docs, %d unique terms, avg length=%.1f",
            self._total_docs,
            len(self._term_doc_freq),
            self._avg_doc_length,
        )

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[SearchResult]:
        """
        Search the BM25 index and return scored results.

        Args:
            query: Query string.
            top_k: Number of results to return.

        Returns:
            List of SearchResult objects sorted by BM25 score (descending).
        """
        if not self._fitted or self._total_docs == 0:
            return []

        query_tokens = query.lower().split()
        if not query_tokens:
            return []

        scores: Dict[str, float] = defaultdict(float)

        for doc_id in self._doc_ids:
            doc_len = self._doc_lengths[doc_id]
            doc_freq = self._doc_freqs[doc_id]
            score = 0.0

            for token in query_tokens:
                if token not in self._term_doc_freq:
                    continue

                tf = doc_freq.get(token, 0)
                idf = math.log(
                    (self._total_docs + 1) / (self._term_doc_freq[token] + 1)
                ) + 1.0

                tf_saturated = (
                    tf * (self.k1 + 1.0)
                ) / (
                    tf
                    + self.k1
                    * (1.0 - self.b + self.b * doc_len / self._avg_doc_length)
                )

                score += idf * (tf_saturated + self.delta)

            if score > 0.0:
                scores[doc_id] = score

        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        sorted_docs = sorted_docs[:top_k]

        results: List[SearchResult] = []
        for rank, (doc_id, score) in enumerate(sorted_docs):
            from dabba.rag.vector_store import Document

            doc = Document(
                id=doc_id,
                text=self._doc_texts.get(doc_id, ""),
                metadata=self._doc_metadata.get(doc_id, {}),
            )
            results.append(
                SearchResult(document=doc, score=float(score), rank=rank + 1)
            )

        return results


class HybridSearch:
    """
    Hybrid dense + sparse search using configurable fusion.

    Combines dense retrieval (embedding similarity via VectorStore) with
    sparse retrieval (BM25) using either a weighted linear combination
    or Reciprocal Rank Fusion (RRF).

    Usage:
        hybrid = HybridSearch(embedding_model, vector_store)
        results = hybrid.search("What is RAG?", alpha=0.5)
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        bm25_retriever: Optional[BM25SparseRetriever] = None,
        config: Optional[RagConfig] = None,
    ) -> None:
        """
        Initialize the hybrid search.

        Args:
            embedding_model: Model for dense query encoding.
            vector_store: Vector database for dense search.
            bm25_retriever: BM25 sparse retriever. Created from config if not
                provided.
            config: RAG configuration.
        """
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.config = config

        if bm25_retriever is None:
            k1 = config.bm25_k1 if config else 1.5
            b = config.bm25_b if config else 0.75
            self.bm25 = BM25SparseRetriever(k1=k1, b=b)
        else:
            self.bm25 = bm25_retriever

    def _rrf_score(
        self,
        dense_results: List[SearchResult],
        sparse_results: List[SearchResult],
        k: int = 60,
    ) -> Dict[str, float]:
        """
        Combine ranks using Reciprocal Rank Fusion.

        Args:
            dense_results: Results from dense retrieval.
            sparse_results: Results from sparse retrieval.
            k: RRF constant (default 60).

        Returns:
            Dictionary mapping document IDs to combined RRF scores.
        """
        rrf_scores: Dict[str, float] = defaultdict(float)

        for rank, r in enumerate(dense_results):
            rrf_scores[r.document.id] += 1.0 / (k + rank + 1)

        for rank, r in enumerate(sparse_results):
            rrf_scores[r.document.id] += 1.0 / (k + rank + 1)

        return dict(rrf_scores)

    def _linear_combination(
        self,
        dense_results: List[SearchResult],
        sparse_results: List[SearchResult],
        alpha: float = 0.5,
    ) -> Dict[str, float]:
        """
        Combine scores using a weighted linear combination.

        Scores from each system are min-max normalized before combination.

        Args:
            dense_results: Dense retrieval results.
            sparse_results: Sparse retrieval results.
            alpha: Weight for dense scores (0.0 = sparse only, 1.0 = dense only).

        Returns:
            Dictionary mapping document IDs to combined scores.
        """
        scores: Dict[str, float] = defaultdict(float)

        def _normalize(
            results: List[SearchResult],
        ) -> Dict[str, float]:
            if not results:
                return {}
            scores_dict = {r.document.id: r.score for r in results}
            min_s = min(scores_dict.values())
            max_s = max(scores_dict.values())
            if max_s - min_s < 1e-12:
                return {k: 1.0 for k in scores_dict}
            return {
                k: (v - min_s) / (max_s - min_s)
                for k, v in scores_dict.items()
            }

        dense_norm = _normalize(dense_results)
        sparse_norm = _normalize(sparse_results)

        all_ids = set(dense_norm.keys()) | set(sparse_norm.keys())
        for doc_id in all_ids:
            d_score = dense_norm.get(doc_id, 0.0)
            s_score = sparse_norm.get(doc_id, 0.0)
            scores[doc_id] = alpha * d_score + (1.0 - alpha) * s_score

        return dict(scores)

    def index_documents(
        self,
        documents: List[Any],
    ) -> None:
        """
        Index documents for BM25 retrieval.

        Should be called after documents have been added to the vector store
        to ensure the BM25 index is in sync.

        Args:
            documents: List of Document objects to index in BM25.
        """
        self.bm25.index(documents)

    def search(
        self,
        query: str,
        top_k: int = 10,
        alpha: float = 0.5,
        fusion_method: str = "linear",
        rrf_k: int = 60,
        score_threshold: Optional[float] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
        sparse_top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Perform hybrid dense + sparse search.

        Args:
            query: Query string.
            top_k: Number of final results to return.
            alpha: Weight for dense retrieval (0.0–1.0). Only used when
                fusion_method is "linear".
            fusion_method: "linear" or "rrf".
            rrf_k: RRF constant (used when fusion_method is "rrf").
            score_threshold: Minimum score threshold for dense results.
            filter_criteria: Metadata filters for dense search.
            sparse_top_k: Number of results from sparse retrieval (defaults
                to top_k * 2).

        Returns:
            Combined list of SearchResult objects sorted by fused score.
        """
        if not query or not query.strip():
            return []

        effective_sparse_k = sparse_top_k or top_k * 2

        # Dense retrieval
        query_embedding = self.embedding_model.encode_queries([query])[0]
        dense_results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=effective_sparse_k,
            score_threshold=score_threshold,
            filter_criteria=filter_criteria,
        )

        # Sparse retrieval (BM25)
        sparse_results = self.bm25.search(query, top_k=effective_sparse_k)

        if not dense_results and not sparse_results:
            return []
        if not dense_results:
            return sparse_results[:top_k]
        if not sparse_results:
            return dense_results[:top_k]

        # Fuse results
        if fusion_method == "rrf":
            fused = self._rrf_score(dense_results, sparse_results, k=rrf_k)
        else:
            fused = self._linear_combination(
                dense_results, sparse_results, alpha=alpha
            )

        # Reconstruct result objects with fused scores
        doc_map: Dict[str, SearchResult] = {}
        for r in dense_results + sparse_results:
            if r.document.id not in doc_map:
                doc_map[r.document.id] = SearchResult(
                    document=r.document,
                    score=0.0,
                    rank=0,
                )

        for doc_id, fused_score in fused.items():
            if doc_id in doc_map:
                doc_map[doc_id].score = float(fused_score)

        combined = sorted(doc_map.values(), key=lambda r: r.score, reverse=True)

        for i, r in enumerate(combined):
            r.rank = i + 1

        return combined[:top_k]
