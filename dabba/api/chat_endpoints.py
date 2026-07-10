"""
Chat completion API endpoints.

Provides POST /v1/chat/completions with both streaming and non-streaming
responses, fully compatible with the OpenAI API format.
"""

import asyncio
import re
import time
from typing import AsyncGenerator, Dict, Iterator, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request

from dabba.api.openai_compat import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompletionUsage,
    Message,
    OpenAIError,
)
from dabba.api.auth import ApiKeyAuth
from dabba.api.rate_limiter import RateLimiter
from dabba.api.streaming_handler import StreamingHandler


def _content_to_text(content) -> str:
    """Flatten a message's content (str or multimodal parts) to plain text.

    Multimodal arrays follow the OpenAI vision format: a list of parts, each
    either {"type": "text", "text": ...} or {"type": "image_url", ...}. Only
    the text parts survive flattening — used for the local dabba model and for
    token estimates, since the local model can't see images.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content)


def _sampling_kwargs(req: ChatCompletionRequest) -> Dict:
    """Extract explicit sampling overrides from the request for provider models."""
    return {
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "top_p": req.top_p,
        "presence_penalty": req.presence_penalty or None,
        "frequency_penalty": req.frequency_penalty or None,
        "stop": req.stop or None,
    }


def _has_images(messages: list) -> bool:
    """True if any message carries an image part (multimodal request)."""
    for m in messages:
        content = m.get("content")
        if isinstance(content, list) and any(
            isinstance(p, dict) and p.get("type") == "image_url" for p in content
        ):
            return True
    return False


def _next_stream_token(iterator: Iterator[str]) -> Tuple[bool, str]:
    try:
        return True, next(iterator)
    except StopIteration:
        return False, ""


class ChatEndpoint:
    """Simple chat endpoint class for testing and direct use."""

    def __init__(self, model_engine=None, auth=None, rate_limiter=None):
        self.model_engine = model_engine
        self.auth = auth
        self.rate_limiter = rate_limiter

    def chat(self, messages, temperature=1.0, max_tokens=None, **kwargs):
        if not messages:
            raise ValueError("Messages cannot be empty")
        return _fallback_response(messages[-1].get("content", "") if isinstance(messages[-1], dict) else "")


def create_chat_router(
    model_engine: Optional[object] = None,
    auth: Optional[ApiKeyAuth] = None,
    rate_limiter: Optional[RateLimiter] = None,
) -> APIRouter:
    """
    Create a FastAPI router for chat completion endpoints.

    Args:
        model_engine: Optional model engine for generating responses.
        auth: Optional API key authentication.
        rate_limiter: Optional rate limiter.

    Returns:
        Configured FastAPI APIRouter.
    """
    router = APIRouter(prefix="/v1", tags=["chat"])

    async def get_auth(request: Request) -> Optional[str]:
        if auth is None:
            return None
        return await auth(request)

    @router.post("/chat/completions")
    async def chat_completions(
        body: Dict,
        request: Request,
        api_key: Optional[str] = Depends(lambda: None),
    ):
        """
        Create a chat completion.

        Accepts both streaming and non-streaming requests following
        the OpenAI chat completion format.

        Args:
            body: Request body as a dictionary.
            request: FastAPI request object.

        Returns:
            ChatCompletionResponse for non-streaming, or
            StreamingResponse for streaming requests.
        """
        try:
            req = ChatCompletionRequest.from_dict(body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        if rate_limiter:
            await rate_limiter.check_request(request, api_key)

        if req.stream:
            return await _handle_streaming_chat(req, model_engine)
        else:
            return await _handle_nonstreaming_chat(req, model_engine)

    @router.post("/chat/completions/stream")
    async def chat_completions_stream(
        body: Dict,
        request: Request,
        api_key: Optional[str] = Depends(lambda: None),
    ):
        """
        Streaming chat completion endpoint.

        Forces streaming even if the request specifies stream=False.
        Useful for clients that want explicit streaming endpoints.
        """
        try:
            req = ChatCompletionRequest.from_dict(body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        req.stream = True

        if rate_limiter:
            await rate_limiter.check_request(request, api_key)

        return await _handle_streaming_chat(req, model_engine)

    return router


async def _handle_nonstreaming_chat(
    req: ChatCompletionRequest,
    model_engine: Optional[object],
) -> Dict:
    """
    Handle a non-streaming chat completion request.

    Args:
        req: The parsed chat completion request.
        model_engine: The model engine for generation.

    Returns:
        ChatCompletionResponse as a dictionary.
    """
    # Preserve the original content structure (str OR multimodal parts) so
    # image_url parts reach vision-capable providers. _generate_response
    # flattens to text only for the local dabba model, which can't see images.
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    last_message = _content_to_text(messages[-1]["content"]) if messages else ""
    prompt_tokens = len(last_message.split())
    # _generate_response makes a blocking network/inference call — run it on a
    # worker thread so it doesn't freeze the whole server's event loop (this
    # previously made even unrelated /health checks hang for the full duration
    # of any in-flight chat request).
    response_text = await asyncio.to_thread(
        _generate_response, messages, model_engine, req.model, req.effort, _sampling_kwargs(req)
    )
    completion_tokens = len(response_text.split())

    choice = ChatCompletionChoice(
        index=0,
        message=Message(
            role="assistant",
            content=response_text,
        ),
        finish_reason="stop",
    )

    response = ChatCompletionResponse(
        model=req.model,
        choices=[choice],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )

    return response.to_dict()


async def _handle_streaming_chat(
    req: ChatCompletionRequest,
    model_engine: Optional[object],
):
    """
    Handle a streaming chat completion request.

    Args:
        req: The parsed chat completion request.
        model_engine: The model engine for generation.

    Returns:
        StreamingResponse with SSE events.
    """
    from fastapi.responses import StreamingResponse

    # Preserve multimodal content (see the non-streaming handler for why).
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    async def event_stream() -> AsyncGenerator[str, None]:
        handler = StreamingHandler(model_name=req.model)

        if req.model and not req.model.startswith("dabba"):
            try:
                async for token in _stream_provider_response(req, messages, model_engine):
                    yield handler.create_chunk(token, index=0)
                yield handler.create_chunk("", index=0, finish_reason="stop")
                yield "data: [DONE]\n\n"
            except Exception as exc:
                yield handler.create_chunk(
                    f"I encountered an error calling '{req.model}': {exc}",
                    index=0,
                    finish_reason="stop",
                )
                yield "data: [DONE]\n\n"
            return

        # See the comment on the non-streaming path above — same fix needed
        # here. Keep yielding SSE comments while slow provider calls (notably
        # NVIDIA GLM/R1 cold starts) are still running, otherwise browsers and
        # reverse proxies can treat the request as idle before the first token.
        response_task = asyncio.create_task(
            asyncio.to_thread(
                _generate_response,
                messages,
                model_engine,
                req.model,
                req.effort,
                _sampling_kwargs(req),
            )
        )
        while not response_task.done():
            yield ": keepalive\n\n"
            await asyncio.sleep(10)

        response_text = await response_task

        # Chunk for the typewriter effect while PRESERVING all whitespace —
        # newlines and indentation carry the structure of YAML/JSON/code, so
        # `str.split()` (which collapses every run of whitespace into one space)
        # would flatten a Pod manifest onto a single line. Splitting on the
        # capture group keeps each whitespace run as its own token instead.
        tokens = [t for t in re.split(r"(\s+)", response_text) if t != ""]

        for token in tokens:
            yield handler.create_chunk(token, index=0)
            await asyncio.sleep(0.01)

        yield handler.create_chunk("", index=0, finish_reason="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_provider_response(
    req: ChatCompletionRequest,
    messages: list,
    model_engine: Optional[object],
) -> AsyncGenerator[str, None]:
    del model_engine
    from dabba.api.agent_endpoints import _get_agent_proxy

    proxy = _get_agent_proxy()
    registry = proxy._get_provider_registry()
    resolved_effort = req.effort or getattr(proxy.cli_config, "effort", "medium")
    overrides = {k: v for k, v in _sampling_kwargs(req).items() if v is not None}
    iterator = registry.stream_chat(messages, model=req.model, effort=resolved_effort, **overrides)

    pending = asyncio.create_task(asyncio.to_thread(_next_stream_token, iterator))
    while True:
        done, _ = await asyncio.wait({pending}, timeout=10)
        if not done:
            yield ""
            continue

        has_token, token = pending.result()
        if not has_token:
            break
        yield token
        pending = asyncio.create_task(asyncio.to_thread(_next_stream_token, iterator))


def _generate_response(
    messages: list,
    model_engine: Optional[object],
    model_name: Optional[str] = None,
    effort: Optional[str] = None,
    sampling: Optional[Dict] = None,
) -> str:
    """
    Generate a response, routing to the right backend for the requested model.

    Any model other than the local "dabba" model (Claude, GPT, Gemini, NVIDIA,
    Ollama) goes through the same ProviderRegistry the VSCode extension's main
    chat panel uses — previously this endpoint ignored `model_name` entirely
    and always used the local model_engine, so Inline Chat and the right-click
    code actions silently ran on the tiny local model no matter what the user
    had selected.

    Args:
        messages: Full conversation as list of {"role", "content"} dicts.
        model_engine: The local model engine for generation (used for "dabba").
        model_name: The model id the client actually requested.

    Returns:
        Generated response text.
    """
    if model_name and not model_name.startswith("dabba"):
        try:
            from dabba.api.agent_endpoints import _get_agent_proxy
            proxy = _get_agent_proxy()
            registry = proxy._get_provider_registry()
            # Per-request effort wins; fall back to the server's configured default.
            resolved_effort = effort or getattr(proxy.cli_config, "effort", "medium")
            # Pass messages through verbatim — multimodal (image) parts must
            # reach vision-capable providers intact. Explicit sampling params
            # (temperature, top_p, penalties, stop, max_tokens) override the
            # effort tier's defaults — registry.chat() layers **kwargs on top
            # of EFFORT_PARAMS, so only non-None values should be forwarded.
            overrides = {k: v for k, v in (sampling or {}).items() if v is not None}
            return registry.chat(messages, model=model_name, effort=resolved_effort, **overrides)
        except Exception as exc:
            return f"I encountered an error calling '{model_name}': {exc}"

    # Local dabba model is text-only — flatten any multimodal content to text.
    local_messages = [{"role": m["role"], "content": _content_to_text(m["content"])} for m in messages]

    if _has_images(messages):
        # The client should route image requests to a vision model or OCR them
        # client-side; if an image still reaches the local model, say so plainly.
        note = ("\n\n[Note: an image was attached but the local dabba model can't "
                "read images. Select a vision model, or the app will OCR it to text.]")
    else:
        note = ""

    if model_engine is not None:
        try:
            if hasattr(model_engine, "chat"):
                return model_engine.chat(local_messages) + note
            if hasattr(model_engine, "generate"):
                last = local_messages[-1]["content"] if local_messages else ""
                return model_engine.generate(last) + note
        except Exception:
            pass

    last = local_messages[-1]["content"] if local_messages else ""
    return _fallback_response(last)


def _fallback_response(prompt: str) -> str:
    """
    Generate a simple fallback response.

    Used when no model engine is configured.

    Args:
        prompt: The input prompt.

    Returns:
        A placeholder response.
    """
    return (
        f"I received your message: \"{prompt[:100]}\". "
        f"This is a placeholder response. To enable actual model responses, "
        f"configure a model engine when starting the server."
    )
