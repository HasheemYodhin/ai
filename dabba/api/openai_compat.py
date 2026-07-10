"""
OpenAI-compatible request/response schemas for the API server.

Implements the standard OpenAI chat completion and embedding API
formats so that any OpenAI client library can connect to dabba.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class Message:
    """
    A chat message with role and content.

    Supports text content and multimodal content arrays.
    """

    role: str  # "system", "user", "assistant", "tool"
    content: Union[str, List[Dict[str, Any]]]
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class FunctionDefinition:
    """
    Definition of a function that the model may call.
    """

    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


@dataclass
class ToolDefinition:
    """
    A tool that the model may call. Follows OpenAI tool format.
    """

    type: str = "function"
    function: Optional[FunctionDefinition] = None


@dataclass
class ChatCompletionRequest:
    """
    Request body for POST /v1/chat/completions.

    Follows the OpenAI chat completion request format.
    """

    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    n: int = 1
    stream: bool = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    logit_bias: Optional[Dict[int, float]] = None
    user: Optional[str] = None
    seed: Optional[int] = None
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    # Reasoning effort tier (low|medium|high|xhigh|max) for provider-backed models.
    # Non-standard OpenAI field — Dabba-specific, ignored by the local model.
    effort: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatCompletionRequest":
        """Create request from a raw dictionary."""
        messages = []
        for msg in data.get("messages", []):
            messages.append(Message(**msg))

        tools = None
        if "tools" in data:
            tools = [ToolDefinition(**t) for t in data["tools"]]

        return cls(
            model=data.get("model", "dabba"),
            messages=messages,
            temperature=data.get("temperature", 0.7),
            top_p=data.get("top_p", 0.9),
            n=data.get("n", 1),
            stream=data.get("stream", False),
            stop=data.get("stop"),
            max_tokens=data.get("max_tokens"),
            presence_penalty=data.get("presence_penalty", 0.0),
            frequency_penalty=data.get("frequency_penalty", 0.0),
            logit_bias=data.get("logit_bias"),
            user=data.get("user"),
            seed=data.get("seed"),
            tools=tools,
            tool_choice=data.get("tool_choice"),
            effort=data.get("effort"),
        )


@dataclass
class CompletionUsage:
    """
    Token usage information for a completion.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatCompletionChoice:
    """
    A single choice in a chat completion response.
    """

    index: int
    message: Message
    finish_reason: str = "stop"
    logprobs: Optional[Any] = None


@dataclass
class ChatCompletionResponse:
    """
    Response body for a non-streaming chat completion.

    Follows the OpenAI chat completion response format.
    """

    id: str = field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = field(default_factory=lambda: int(time.time()))
    model: str = "dabba"
    choices: List[ChatCompletionChoice] = field(default_factory=list)
    usage: CompletionUsage = field(default_factory=CompletionUsage)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": [
                {
                    "index": c.index,
                    "message": {
                        "role": c.message.role,
                        "content": c.message.content,
                        **({"tool_calls": c.message.tool_calls} if c.message.tool_calls else {}),
                    },
                    "finish_reason": c.finish_reason,
                }
                for c in self.choices
            ],
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
            },
        }


@dataclass
class ChatCompletionChunk:
    """
    A single chunk in a streaming chat completion.

    Follows the OpenAI streaming chunk format for SSE.
    """

    id: str = field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion.chunk"
    created: int = field(default_factory=lambda: int(time.time()))
    model: str = "dabba"
    choices: List[Dict[str, Any]] = field(default_factory=list)

    def to_sse(self) -> str:
        """Serialize to SSE format string."""
        data = {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": self.choices,
        }
        import json
        return f"data: {json.dumps(data)}\n\n"

    @classmethod
    def done(cls) -> str:
        """Return the SSE done signal."""
        return "data: [DONE]\n\n"


@dataclass
class EmbeddingRequest:
    """
    Request body for POST /v1/embeddings.

    Follows the OpenAI embedding request format.
    """

    model: str = "dabba"
    input: Union[str, List[str], List[List[int]]] = ""
    encoding_format: str = "float"  # "float" or "base64"
    user: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmbeddingRequest":
        """Create request from a raw dictionary."""
        return cls(
            model=data.get("model", "dabba"),
            input=data.get("input", ""),
            encoding_format=data.get("encoding_format", "float"),
            user=data.get("user"),
        )


@dataclass
class EmbeddingData:
    """
    A single embedding result.
    """

    index: int
    embedding: List[float]
    object: str = "embedding"


@dataclass
class EmbeddingResponse:
    """
    Response body for an embedding request.

    Follows the OpenAI embedding response format.
    """

    object: str = "list"
    data: List[EmbeddingData] = field(default_factory=list)
    model: str = "dabba"
    usage: CompletionUsage = field(default_factory=CompletionUsage)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "object": self.object,
            "data": [
                {
                    "index": d.index,
                    "object": d.object,
                    "embedding": d.embedding,
                }
                for d in self.data
            ],
            "model": self.model,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "total_tokens": self.usage.total_tokens,
            },
        }


@dataclass
class ModelInfo:
    """
    Information about an available model.
    """

    id: str
    object: str = "model"
    created: int = field(default_factory=lambda: int(time.time()))
    owned_by: str = "dabba"
    permission: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ModelList:
    """
    Response body for GET /v1/models.
    """

    object: str = "list"
    data: List[ModelInfo] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "object": self.object,
            "data": [
                {
                    "id": m.id,
                    "object": m.object,
                    "created": m.created,
                    "owned_by": m.owned_by,
                }
                for m in self.data
            ],
        }


class OpenAIError(Exception):
    """
    OpenAI-compatible API error.

    Attributes:
        message: Human-readable error message.
        code: Error code string.
        status: HTTP status code.
    """

    def __init__(self, message: str, code: str = "internal_error", status: int = 500):
        self.message = message
        self.code = code
        self.status = status
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible error dictionary."""
        return {
            "error": {
                "message": self.message,
                "type": self.code,
                "code": self.code,
            }
        }
