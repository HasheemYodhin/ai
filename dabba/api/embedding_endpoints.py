"""
Embedding API endpoints.

Provides POST /v1/embeddings compatible with the OpenAI embedding API format.
"""

from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request

from dabba.api.openai_compat import (
    EmbeddingData,
    EmbeddingRequest,
    EmbeddingResponse,
    CompletionUsage,
    OpenAIError,
)
from dabba.api.auth import ApiKeyAuth
from dabba.api.rate_limiter import RateLimiter


def create_embedding_router(
    embedding_engine: Optional[object] = None,
    auth: Optional[ApiKeyAuth] = None,
    rate_limiter: Optional[RateLimiter] = None,
) -> APIRouter:
    """
    Create a FastAPI router for embedding endpoints.

    Args:
        embedding_engine: Optional embedding model engine.
        auth: Optional API key authentication.
        rate_limiter: Optional rate limiter.

    Returns:
        Configured FastAPI APIRouter.
    """
    router = APIRouter(prefix="/v1", tags=["embeddings"])

    @router.post("/embeddings")
    async def create_embeddings(
        body: Dict,
        request: Request,
        api_key: Optional[str] = None,
    ):
        """
        Create embeddings for the given input.

        Follows the OpenAI embedding API format.

        Args:
            body: Request body.
            request: FastAPI request.
            api_key: Optional API key.

        Returns:
            EmbeddingResponse as a dictionary.
        """
        try:
            req = EmbeddingRequest.from_dict(body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        if rate_limiter:
            await rate_limiter.check_request(request, api_key)

        inputs = []
        if isinstance(req.input, str):
            inputs = [req.input]
        elif isinstance(req.input, list):
            if req.input and isinstance(req.input[0], str):
                inputs = req.input
            else:
                inputs = [str(req.input)]

        embeddings_list = _generate_embeddings(inputs, embedding_engine)
        dim = len(embeddings_list[0]) if embeddings_list else 0

        token_count = sum(len(text.split()) for text in inputs)

        response = EmbeddingResponse(
            model=req.model,
            data=[
                EmbeddingData(index=i, embedding=emb)
                for i, emb in enumerate(embeddings_list)
            ],
            usage=CompletionUsage(
                prompt_tokens=token_count,
                total_tokens=token_count,
            ),
        )

        return response.to_dict()

    return router


def _generate_embeddings(
    texts: List[str],
    embedding_engine: Optional[object],
) -> List[List[float]]:
    """
    Generate embeddings for a list of texts.

    Falls back to random embeddings if no engine is available.

    Args:
        texts: List of input texts.
        embedding_engine: Optional embedding model engine.

    Returns:
        List of embedding vectors.
    """
    if embedding_engine is not None:
        try:
            if hasattr(embedding_engine, "encode"):
                return embedding_engine.encode(texts).tolist()
        except Exception:
            pass

    import random
    rng = random.Random(42)
    return [
        [rng.random() for _ in range(384)]
        for _ in texts
    ]
