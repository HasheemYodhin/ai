"""
FastAPI-based inference server with OpenAI-compatible endpoints.

Provides REST API access to dabba models with streaming support,
authentication, rate limiting, and full OpenAI API compatibility.
"""

from dabba.api.server import create_app
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

app = create_app()

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
