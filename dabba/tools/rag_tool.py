"""
RAG (Retrieval-Augmented Generation) tool for the dabba agent.

Wraps the RagPipeline to provide knowledge base querying
capabilities to the agent system.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry
from dabba.utils.logging import get_logger

logger = get_logger("dabba.tools.rag_tool")

try:
    from dabba.rag.rag_pipeline import RagPipeline
    HAS_RAG = True
except ImportError:
    HAS_RAG = False


class RagToolError(Exception):
    """Base exception for RAG tool errors."""


_rag_pipeline_instance: Optional[Any] = None


def _get_rag_pipeline() -> Any:
    """
    Get or create the global RagPipeline instance.

    Returns:
        RagPipeline instance.

    Raises:
        RagToolError: If the RAG module is not available.
    """
    global _rag_pipeline_instance

    if _rag_pipeline_instance is not None:
        return _rag_pipeline_instance

    if not HAS_RAG:
        raise RagToolError(
            "RAG module is not available. Ensure dabba.rag is properly installed "
            "with all dependencies."
        )

    try:
        _rag_pipeline_instance = RagPipeline()
        logger.info("Initialized RAG pipeline for tool usage")
        return _rag_pipeline_instance
    except Exception as exc:
        raise RagToolError(f"Failed to initialize RAG pipeline: {exc}")


def set_rag_pipeline(pipeline: Any) -> None:
    """
    Set a custom RagPipeline instance for the tool to use.

    Args:
        pipeline: An initialized RagPipeline instance.
    """
    global _rag_pipeline_instance
    _rag_pipeline_instance = pipeline
    logger.info("Custom RAG pipeline set for tool usage")


def query_knowledge_base(
    query: str,
    top_k: int = 5,
) -> Dict[str, object]:
    """
    Query the RAG knowledge base and return relevant documents.

    Args:
        query: The search query or question.
        top_k: Number of top documents to retrieve (1-20).

    Returns:
        Dictionary with:
          - query: The original query.
          - results: List of result dicts with keys: content, score, source, metadata.
          - total_results: Number of results returned.

    Raises:
        RagToolError: If the RAG pipeline is unavailable or query fails.
    """
    if not query or not query.strip():
        raise ValueError("Query cannot be empty")

    top_k = max(1, min(top_k, 20))

    try:
        pipeline = _get_rag_pipeline()
    except RagToolError:
        return _simulate_rag_query(query, top_k)

    try:
        if hasattr(pipeline, "query"):
            raw_results = pipeline.query(query=query, top_k=top_k)
        elif hasattr(pipeline, "retrieve"):
            raw_results = pipeline.retrieve(query=query, top_k=top_k)
        elif hasattr(pipeline, "search"):
            raw_results = pipeline.search(query=query, top_k=top_k)
        else:
            raise RagToolError(
                "RAG pipeline has no query/retrieve/search method"
            )

        results = _normalize_rag_results(raw_results)

        logger.info(
            "RAG query '%s': retrieved %d results", query, len(results)
        )
        return {
            "query": query,
            "results": results,
            "total_results": len(results),
        }

    except Exception as exc:
        logger.error("RAG query failed: %s", exc)
        raise RagToolError(f"RAG query failed: {exc}")


def _normalize_rag_results(raw_results: Any) -> List[Dict[str, object]]:
    """
    Normalize various RAG result formats into a uniform structure.

    Args:
        raw_results: Results from RagPipeline in various formats.

    Returns:
        List of normalized result dicts.
    """
    normalized: List[Dict[str, object]] = []

    if isinstance(raw_results, list):
        for item in raw_results:
            if isinstance(item, dict):
                if "content" in item or "text" in item or "document" in item:
                    normalized.append({
                        "content": item.get("content") or item.get("text") or item.get("document", ""),
                        "score": item.get("score") or item.get("similarity") or item.get("relevance", 0.0),
                        "source": item.get("source") or item.get("path") or item.get("url", ""),
                        "metadata": item.get("metadata", {}),
                    })
                else:
                    normalized.append({
                        "content": str(item),
                        "score": 0.0,
                        "source": "",
                        "metadata": {},
                    })
            else:
                normalized.append({
                    "content": str(item),
                    "score": 0.0,
                    "source": "",
                    "metadata": {},
                })
    elif isinstance(raw_results, dict):
        docs = (
            raw_results.get("documents")
            or raw_results.get("results")
            or raw_results.get("chunks")
            or raw_results.get("passages")
            or []
        )
        scores = (
            raw_results.get("scores")
            or raw_results.get("distances")
            or raw_results.get("similarities")
            or []
        )
        sources = (
            raw_results.get("sources")
            or raw_results.get("metadatas")
            or raw_results.get("ids")
            or []
        )

        if isinstance(docs, list):
            for i, doc in enumerate(docs):
                score = scores[i] if isinstance(scores, list) and i < len(scores) else 0.0
                source = sources[i] if isinstance(sources, list) and i < len(sources) else ""
                meta = {}
                if isinstance(source, dict):
                    meta = source
                    source = str(source.get("source", source.get("path", "")))
                normalized.append({
                    "content": str(doc),
                    "score": float(score) if score is not None else 0.0,
                    "source": str(source) if source else "",
                    "metadata": meta,
                })

    return normalized


def _simulate_rag_query(
    query: str,
    top_k: int,
) -> Dict[str, object]:
    """
    Simulate a RAG query when the RAG pipeline is not configured.

    Returns a helpful message indicating the pipeline needs to be set up.

    Args:
        query: The search query.
        top_k: Number of results requested.

    Returns:
        Simulated response directing the user to configure RAG.
    """
    logger.warning(
        "RAG pipeline not available. Returning simulated results."
    )
    return {
        "query": query,
        "results": [
            {
                "content": (
                    "The RAG (Retrieval-Augmented Generation) pipeline is not "
                    "currently configured. To enable RAG queries, initialize "
                    "the RagPipeline with a vector store and document index, "
                    "then call set_rag_pipeline()."
                ),
                "score": 1.0,
                "source": "rag_tool.py",
                "metadata": {"note": "simulated_result"},
            }
        ],
        "total_results": 1,
        "note": (
            "RAG pipeline is not configured. "
            "These are placeholder results. "
            "Call set_rag_pipeline() with a configured RagPipeline instance."
        ),
    }


def register_rag_tools(registry: ToolRegistry) -> None:
    """
    Register all RAG query tools with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
    """
    registry.register(
        ToolDefinition(
            name="rag_query",
            description="Query the RAG knowledge base for documents relevant to the query.",
            parameters=[
                ToolParameter(name="query", type="string", description="The search query or question."),
                ToolParameter(name="top_k", type="integer", description="Number of results to retrieve (1-20).", required=False, default=5),
            ],
            handler=query_knowledge_base,
            handler_sync=True,
            category="rag",
        )
    )
