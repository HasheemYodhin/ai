"""
Complete RAG pipeline orchestration.

Coordinates embedding, retrieval, re-ranking, context formatting,
and answer generation into a single end-to-end pipeline.
"""

from typing import Any, Dict, List, Optional, Tuple

from dabba.config.rag_config import RagConfig
from dabba.rag.document_indexer import DocumentIndexer
from dabba.rag.embedding_model import EmbeddingModel
from dabba.rag.hybrid_search import HybridSearch
from dabba.rag.reranker import Reranker
from dabba.rag.retriever import Retriever
from dabba.rag.vector_store import SearchResult, VectorStore
from dabba.utils.logging import get_logger

logger = get_logger("dabba.rag.pipeline")


class RagPipeline:
    """
    End-to-end Retrieval-Augmented Generation pipeline.

    Orchestrates the full RAG workflow:
        1. Encode the user query into an embedding.
        2. Retrieve relevant documents from the vector store.
        3. Optionally re-rank results with a cross-encoder.
        4. Format the retrieved context for the LLM prompt.
        5. Generate an answer using a language model.

    Usage:
        pipeline = RagPipeline(
            embedding_model=embedding_model,
            vector_store=vector_store,
            llm_generate_fn=my_model.generate,
        )
        answer = pipeline.query("What is the capital of France?")
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        config: Optional[RagConfig] = None,
        retriever: Optional[Retriever] = None,
        reranker: Optional[Reranker] = None,
        hybrid_search: Optional[HybridSearch] = None,
        document_indexer: Optional[DocumentIndexer] = None,
        llm_generate_fn=None,
        system_prompt: Optional[str] = None,
    ) -> None:
        """
        Initialize the RAG pipeline.

        Args:
            embedding_model: Model for encoding queries and documents.
            vector_store: Vector database for document storage and retrieval.
            config: RAG configuration. Falls back to defaults if not provided.
            retriever: Document retriever. Created from defaults if not provided.
            reranker: Optional cross-encoder re-ranker. Enabled based on config.
            hybrid_search: Optional hybrid dense/sparse search. Used when
                config.retrieval_mode is "hybrid".
            document_indexer: Optional document indexer. Created from defaults.
            llm_generate_fn: Callable(str, **kwargs) -> str that generates
                an answer given a prompt. If None, query() will return the
                context without generating.
            system_prompt: System-level instruction prepended to the prompt.
        """
        self.config = config or RagConfig()
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.llm_generate_fn = llm_generate_fn
        self.system_prompt = system_prompt or (
            "You are a helpful AI assistant. Answer the question based on "
            "the provided context. If the context does not contain enough "
            "information to answer, say so."
        )

        # Build sub-components
        self.retriever = retriever or Retriever(
            embedding_model=embedding_model,
            vector_store=vector_store,
            config=self.config,
        )

        if reranker is not None:
            self.reranker = reranker
        elif self.config.use_reranker:
            self.reranker = Reranker(config=self.config)
        else:
            self.reranker = None

        self.hybrid_search = hybrid_search
        self.document_indexer = document_indexer

        self._conversation_history: List[Dict[str, str]] = []

    @property
    def document_count(self) -> int:
        """Number of documents currently in the vector store."""
        return self.vector_store.count()

    def _build_prompt(
        self,
        query: str,
        context: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Build a prompt for the LLM from the query and retrieved context.

        Args:
            query: User query.
            context: Formatted context string from retrieved documents.
            history: Optional conversation history.

        Returns:
            Full prompt string ready for LLM inference.
        """
        parts: List[str] = []

        if self.system_prompt:
            parts.append(f"System: {self.system_prompt}\n")

        if history:
            parts.append("Conversation History:")
            for turn in history[-6:]:  # keep last 6 turns
                role = turn.get("role", "user")
                content = turn.get("content", "")
                parts.append(f"{role.capitalize()}: {content}")
            parts.append("")

        if context:
            parts.append("Retrieved Context:")
            parts.append(context)
            parts.append("")

        parts.append(f"Question: {query}")
        parts.append("Answer:")

        return "\n".join(parts)

    def format_context(
        self,
        results: List[SearchResult],
        include_scores: bool = False,
        max_tokens: Optional[int] = None,
        separator: str = "\n---\n",
    ) -> str:
        """
        Format retrieved documents into a context string for the prompt.

        Args:
            results: List of SearchResult from retriever or reranker.
            include_scores: If True, prepend each document with its score.
            max_tokens: Maximum approximate token count for the context.
                Documents are truncated from the bottom to fit.
            separator: String placed between documents.

        Returns:
            Formatted context string.
        """
        if not results:
            return ""

        formatted_docs: List[str] = []
        for i, result in enumerate(results):
            prefix = f"Document [{result.rank}]"
            if include_scores:
                prefix += f" (relevance: {result.score:.4f})"

            doc_text = result.document.text.strip()
            formatted_docs.append(f"{prefix}:\n{doc_text}")

        context = separator.join(formatted_docs)

        # Approximate token-based truncation (4 chars ≈ 1 token)
        if max_tokens is not None:
            max_chars = max_tokens * 4
            if len(context) > max_chars:
                # Truncate from the end, keeping document boundaries
                truncated: List[str] = []
                char_count = 0
                for doc_str in formatted_docs:
                    doc_len = len(doc_str) + len(separator)
                    if char_count + doc_len > max_chars:
                        remaining = max_chars - char_count
                        if remaining > 50:
                            truncated.append(doc_str[:remaining])
                        break
                    truncated.append(doc_str)
                    char_count += doc_len
                context = separator.join(truncated)

        return context

    def retrieve_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
        include_scores_in_context: bool = False,
        max_context_tokens: Optional[int] = None,
    ) -> Tuple[List[SearchResult], str]:
        """
        Retrieve and format context for a query.

        This method runs the retrieval (and optionally re-ranking) steps
        without generating an answer.

        Args:
            query: User query string.
            top_k: Number of documents to retrieve.
            score_threshold: Minimum similarity threshold.
            filter_criteria: Optional metadata filters.
            include_scores_in_context: Include scores in formatted context.
            max_context_tokens: Truncate context to this many tokens.

        Returns:
            Tuple of (list of SearchResult, formatted context string).
        """
        effective_top_k = top_k if top_k is not None else self.config.top_k
        effective_threshold = (
            score_threshold
            if score_threshold is not None
            else self.config.score_threshold
        )

        # Choose retrieval strategy
        if (
            self.hybrid_search is not None
            and self.config.retrieval_mode == "hybrid"
        ):
            results = self.hybrid_search.search(
                query=query,
                top_k=effective_top_k,
                alpha=self.config.hybrid_search_alpha
                if hasattr(self.config, "hybrid_search_alpha")
                else 0.5,
                score_threshold=effective_threshold,
                filter_criteria=filter_criteria,
            )
        else:
            results = self.retriever.retrieve(
                query=query,
                top_k=effective_top_k,
                score_threshold=effective_threshold,
                filter_criteria=filter_criteria,
            )

        # Re-rank if enabled
        if self.reranker is not None and results:
            results = self.reranker.rerank(
                query=query,
                results=results,
                top_k=self.config.rerank_top_k,
            )

        context = self.format_context(
            results,
            include_scores=include_scores_in_context,
            max_tokens=max_context_tokens,
        )

        return results, context

    def query(
        self,
        query: str,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
        include_scores_in_context: bool = False,
        max_context_tokens: Optional[int] = None,
        generation_kwargs: Optional[Dict[str, Any]] = None,
        add_to_history: bool = True,
    ) -> Dict[str, Any]:
        """
        Run the full RAG pipeline: retrieve, format, and generate.

        Args:
            query: User query string.
            top_k: Number of documents to retrieve.
            score_threshold: Minimum similarity threshold.
            filter_criteria: Optional metadata filters.
            include_scores_in_context: Include scores in the prompt context.
            max_context_tokens: Truncate context to approximate token count.
            generation_kwargs: Additional keyword arguments passed to the
                LLM generate function (temperature, max_tokens, etc.).
            add_to_history: If True, add the query and answer to conversation
                history.

        Returns:
            Dictionary with keys:
                - "query": The original query.
                - "results": List of SearchResult objects.
                - "context": Formatted context string.
                - "answer": Generated answer (None if no llm_generate_fn).
                - "answer_generated": Whether an answer was generated.
        """
        results, context = self.retrieve_context(
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            filter_criteria=filter_criteria,
            include_scores_in_context=include_scores_in_context,
            max_context_tokens=max_context_tokens,
        )

        answer = None
        answer_generated = False

        if self.llm_generate_fn is not None:
            prompt = self._build_prompt(
                query=query,
                context=context,
                history=(
                    self._conversation_history if add_to_history else None
                ),
            )

            kwargs = generation_kwargs or {}
            try:
                answer = self.llm_generate_fn(prompt, **kwargs)
                answer_generated = True
            except Exception as exc:
                logger.error("LLM generation failed: %s", exc)
                answer = None
        else:
            logger.info(
                "No llm_generate_fn provided; returning context only."
            )

        result: Dict[str, Any] = {
            "query": query,
            "results": results,
            "context": context,
            "answer": answer,
            "answer_generated": answer_generated,
        }

        if add_to_history:
            self._conversation_history.append(
                {"role": "user", "content": query}
            )
            if answer is not None:
                self._conversation_history.append(
                    {"role": "assistant", "content": answer}
                )

        logger.info(
            "Query processed: %d results, answer_generated=%s",
            len(results),
            answer_generated,
        )
        return result

    def query_batch(
        self,
        queries: List[str],
        top_k: Optional[int] = None,
        generation_kwargs: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Process multiple queries sequentially.

        Args:
            queries: List of query strings.
            top_k: Number of documents to retrieve per query.
            generation_kwargs: Additional LLM generation kwargs.

        Returns:
            List of result dictionaries, one per query.
        """
        return [
            self.query(
                query=q,
                top_k=top_k,
                generation_kwargs=generation_kwargs,
                add_to_history=False,
            )
            for q in queries
        ]

    def add_documents(
        self,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Index documents from a file or directory.

        Convenience method that delegates to DocumentIndexer.

        Args:
            source: Path to a file or directory to index.
            metadata: Additional metadata.

        Returns:
            List of document IDs created.
        """
        import os

        if self.document_indexer is None:
            self.document_indexer = DocumentIndexer(
                embedding_model=self.embedding_model,
                vector_store=self.vector_store,
                config=self.config,
            )

        if os.path.isdir(source):
            result = self.document_indexer.index_directory(
                source, metadata=metadata
            )
            ids: List[str] = []
            for file_ids in result.values():
                ids.extend(file_ids)
            return ids
        else:
            return self.document_indexer.index_file(source, metadata=metadata)

    def reset_conversation(self) -> None:
        """Clear the conversation history."""
        self._conversation_history.clear()
        logger.info("Conversation history reset.")

    def clear_index(self) -> None:
        """Clear all documents from the vector store."""
        if hasattr(self.vector_store, 'clear'):
            self.vector_store.clear()
        elif hasattr(self.vector_store, 'reset'):
            self.vector_store.reset()

    def get_stats(self) -> dict:
        """Return statistics about the pipeline."""
        count = 0
        if hasattr(self.vector_store, '__len__'):
            count = len(self.vector_store)
        elif hasattr(self.vector_store, 'count'):
            count = self.vector_store.count()
        return {
            "document_count": count,
            "conversation_length": len(self._conversation_history),
        }
