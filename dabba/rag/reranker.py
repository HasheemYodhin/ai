"""
Cross-encoder re-ranking module.

Uses cross-encoder models to re-rank documents retrieved by the
first-stage retriever, producing a more accurate relevance ordering.
"""

from typing import List, Optional

from dabba.config.rag_config import RagConfig
from dabba.rag.vector_store import SearchResult
from dabba.utils.logging import get_logger

logger = get_logger("dabba.rag.reranker")


class Reranker:
    """
    Cross-encoder re-ranker for improving retrieval quality.

    Takes a list of retrieved documents and a query, scores each
    (query, document) pair through a cross-encoder model, and returns
    a re-ranked list with updated relevance scores.

    Usage:
        reranker = Reranker(model_name="BAAI/bge-reranker-small")
        results = reranker.rerank(query, initial_results)
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-small",
        device: str = "cpu",
        top_k: Optional[int] = None,
        batch_size: int = 32,
        config: Optional[RagConfig] = None,
    ) -> None:
        """
        Initialize the re-ranker.

        Args:
            model_name: Cross-encoder model name (HuggingFace hub or path).
            device: Target device ("cpu", "cuda", etc.).
            top_k: Number of top results to keep after re-ranking. If None,
                all results are returned.
            batch_size: Batch size for cross-encoder inference.
            config: RAG configuration. If provided, its re-ranker settings
                take precedence over individual arguments.
        """
        if config is not None:
            self.model_name = config.reranker_model_name
            self.device = config.reranker_device
            self.top_k = config.rerank_top_k if top_k is None else top_k
        else:
            self.model_name = model_name
            self.device = device
            self.top_k = top_k

        self.batch_size = batch_size
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        """Lazy-load the cross-encoder model."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self.model_name,
                device=self.device,
            )
            logger.info(
                "Loaded cross-encoder reranker '%s' on %s",
                self.model_name,
                self.device,
            )
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for re-ranking. "
                "Install with: pip install sentence-transformers"
            )

    def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Re-rank the given search results using the cross-encoder.

        The cross-encoder scores each (query, document) pair jointly,
        producing more accurate relevance judgments than embedding
        similarity alone.

        Args:
            query: The original query string.
            results: List of SearchResult from the first-stage retriever.
            top_k: Maximum number of re-ranked results to return. If not
                provided, defaults to the instance's top_k setting.

        Returns:
            Re-ranked list of SearchResult objects, sorted by descending
            cross-encoder score.
        """
        if not query or not results:
            return []

        self._load_model()
        effective_top_k = (
            top_k if top_k is not None else self.top_k
        )

        # Prepare (query, document) pairs for the cross-encoder.
        pairs = [(query, r.document.text) for r in results]

        try:
            scores = self._model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
        except Exception:
            logger.warning("Cross-encoder prediction failed; using original scores.")
            scores = [r.score for r in results]

        # Attach cross-encoder scores and re-sort.
        reranked: List[SearchResult] = []
        for i, result in enumerate(results):
            ce_score = float(scores[i])
            # Log-odds combination: blend original similarity with CE score.
            blended = 0.3 * result.score + 0.7 * ce_score
            reranked.append(
                SearchResult(
                    document=result.document,
                    score=blended,
                    rank=0,
                )
            )

        reranked.sort(key=lambda r: r.score, reverse=True)

        # Assign final ranks and truncate.
        for i, r in enumerate(reranked):
            r.rank = i + 1

        if effective_top_k is not None and effective_top_k > 0:
            reranked = reranked[:effective_top_k]

        logger.debug(
            "Reranked %d results → %d (top_k=%s)",
            len(results),
            len(reranked),
            effective_top_k,
        )
        return reranked

    def rerank_batch(
        self,
        query_doc_pairs: List[List[SearchResult]],
        queries: List[str],
        top_k: Optional[int] = None,
    ) -> List[List[SearchResult]]:
        """
        Re-rank multiple query result sets in batch.

        Args:
            query_doc_pairs: List of result lists, one per query.
            queries: List of query strings (same length as query_doc_pairs).
            top_k: Maximum number of results per query.

        Returns:
            List of re-ranked result lists.
        """
        return [
            self.rerank(q, res, top_k=top_k)
            for q, res in zip(queries, query_doc_pairs)
        ]
