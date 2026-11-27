"""
FastAPI-based inference server with OpenAI-compatible endpoints.

Provides REST API access to dabba models with streaming support,
authentication, rate limiting, and full OpenAI API compatibility.
"""

from typing import TYPE_CHECKING
from dabba.api.auth import ApiKeyAuth, authenticate_request
from dabba.api.rate_limiter import RateLimiter
from dabba.api.openai_compat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
    Message,
    EmbeddingRequest,
    EmbeddingResponse,
)
from dabba.api.streaming_handler import StreamingHandler

if TYPE_CHECKING:
    from fastapi import FastAPI
    from dabba.api.server import create_app

    app: FastAPI


def __getattr__(name: str):
    if name in {"app", "create_app"}:
        from dabba.api.server import create_app

        if name == "create_app":
            return create_app
        app = create_app()
        globals()["app"] = app
        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "create_app",
    "app",
    "ApiKeyAuth",
    "authenticate_request",
    "RateLimiter",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatCompletionChunk",
    "Message",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "StreamingHandler",
]
