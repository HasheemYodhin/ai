"""
Chat completion API endpoints.

Provides POST /v1/chat/completions with both streaming and non-streaming
responses, fully compatible with the OpenAI API format.
"""

import asyncio
import json
import re
from contextlib import aclosing
from threading import Event
from typing import AsyncGenerator, Dict, Iterator, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal

from dabba.api.openai_compat import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompletionUsage,
    Message,
)
from dabba.api.auth import ApiKeyAuth
from dabba.api.rate_limiter import RateLimiter
from dabba.api.streaming_handler import StreamingHandler
from dabba.providers.base import ReasoningDelta


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
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return "" if content is None else str(content)


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
        return _fallback_response(
            messages[-1].get("content", "") if isinstance(messages[-1], dict) else ""
        )


class ChatMessageInput(BaseModel):
    role: Literal["system", "developer", "user", "assistant", "tool", "function"]
    content: str | list[dict] | None = None
    name: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class ChatRequestInput(BaseModel):
    model: str = Field(default="dabba", min_length=1, max_length=256)
    messages: list[ChatMessageInput] = Field(min_length=1, max_length=1000)
    temperature: float | None = Field(default=0.7, ge=0, le=2)
    top_p: float | None = Field(default=0.9, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    stream: bool = False


async def _read_chat_request(request: Request) -> ChatCompletionRequest:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 16 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Chat payload exceeds 16 MiB")
        body.extend(chunk)

    try:
        payload = json.loads(body)
        validated = ChatRequestInput.model_validate(payload)
        for message in validated.messages:
            if message.content is None and not (
                message.role == "assistant" and message.tool_calls
            ):
                raise HTTPException(
                    status_code=422, detail="Chat message content is required"
                )
            if len(_content_to_text(message.content)) > 600_000:
                raise HTTPException(
                    status_code=422, detail="Chat message exceeds 600,000 characters"
                )
        return ChatCompletionRequest.from_dict({**payload, **validated.model_dump()})
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422, detail="Invalid chat completion request"
        ) from exc


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
        request: Request,
        api_key: Optional[str] = Depends(get_auth),
    ):
        """
        Create a chat completion.

        Accepts both streaming and non-streaming requests following
        the OpenAI chat completion format.

        Args:
            request: FastAPI request object.

        Returns:
            ChatCompletionResponse for non-streaming, or
            StreamingResponse for streaming requests.
        """
        req = await _read_chat_request(request)

        if rate_limiter:
            await rate_limiter.check_request(request, api_key)

        task_context = _create_chat_task(request, req)
        if req.stream:
            return await _handle_streaming_chat(req, model_engine, task_context)
        else:
            return await _handle_nonstreaming_chat(req, model_engine, task_context)

    @router.post("/chat/completions/stream")
    async def chat_completions_stream(
        request: Request,
        api_key: Optional[str] = Depends(get_auth),
    ):
        """
        Streaming chat completion endpoint.

        Forces streaming even if the request specifies stream=False.
        Useful for clients that want explicit streaming endpoints.
        """
        req = await _read_chat_request(request)

        req.stream = True

        if rate_limiter:
            await rate_limiter.check_request(request, api_key)

        return await _handle_streaming_chat(
            req, model_engine, _create_chat_task(request, req)
        )

    return router


async def _handle_nonstreaming_chat(
    req: ChatCompletionRequest,
    model_engine: Optional[object],
    task_context=None,
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
    # Populated in place by _generate_response if the resolved provider
    # captures real usage (see registry.py/base.py) — a fresh dict per
    # request, so no shared state races across concurrent requests.
    usage_holder: Dict[str, int] = {}
    # _generate_response makes a blocking network/inference call — run it on a
    # worker thread so it doesn't freeze the whole server's event loop (this
    # previously made even unrelated /health checks hang for the full duration
    # of any in-flight chat request).
    if task_context:
        tasks, task_id = task_context
        tasks.transition(task_id, "running", current_step="Generating response")
    try:
        response_text = await asyncio.to_thread(
            _generate_response,
            messages,
            model_engine,
            req.model,
            req.effort,
            _sampling_kwargs(req),
            usage_holder,
        )
    except Exception as exc:
        if task_context:
            from dabba.platform.provider_gateway import normalize_provider_error

            failure = normalize_provider_error(exc, model=req.model)
            tasks.transition(task_id, "failed", error=failure.as_dict())
        raise

    # Real usage when the provider reported it; a word-count estimate
    # otherwise (the local dabba model, or a provider that doesn't capture
    # usage yet) — word count is not token count, just the least-bad guess
    # available without a real tokenizer for every possible model.
    prompt_tokens = usage_holder.get("prompt_tokens") or len(last_message.split())
    completion_tokens = usage_holder.get("completion_tokens") or len(
        response_text.split()
    )
    total_tokens = usage_holder.get("total_tokens") or (
        prompt_tokens + completion_tokens
    )

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
            total_tokens=total_tokens,
        ),
    )

    payload = response.to_dict()
    if task_context:
        tasks.transition(
            task_id,
            "completed",
            record_model_usage=True,
            result={
                "content": response_text,
                "usage": usage_holder,
                "model": req.model,
            },
        )
        payload["dabba_task_id"] = task_id
    return payload


async def _handle_streaming_chat(
    req: ChatCompletionRequest,
    model_engine: Optional[object],
    task_context=None,
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
        tasks = task_id = None
        if task_context:
            tasks, task_id = task_context
            tasks.transition(task_id, "running", current_step="Streaming response")
            yield f": dabba-task-id={task_id}\n\n"

        if req.model and not req.model.startswith("dabba"):
            usage_holder: Dict[str, int] = {}
            complete_text = ""
            event_buffer = ""
            try:
                async with aclosing(
                    _stream_provider_response(req, messages, model_engine, usage_holder)
                ) as upstream:
                    async for token in upstream:
                        if token is None:
                            yield ": keepalive\n\n"
                            continue
                        if isinstance(token, ReasoningDelta):
                            yield handler.create_chunk("", reasoning=token)
                            continue
                        complete_text += token
                        event_buffer += token
                        if tasks and len(event_buffer) >= 500:
                            tasks.append_event(
                                task_id, "task.output.delta", {"content": event_buffer}
                            )
                            event_buffer = ""
                        yield handler.create_chunk(token, index=0)
                if tasks:
                    if event_buffer:
                        tasks.append_event(
                            task_id, "task.output.delta", {"content": event_buffer}
                        )
                    tasks.transition(
                        task_id,
                        "completed",
                        record_model_usage=True,
                        result={
                            "content": complete_text,
                            "usage": usage_holder,
                            "model": req.model,
                        },
                    )
                yield handler.create_chunk(
                    "", index=0, finish_reason="stop", usage=usage_holder or None
                )
                yield "data: [DONE]\n\n"
            except asyncio.CancelledError:
                if tasks:
                    tasks.cancel(task_id)
                raise
            except Exception as exc:
                from dabba.platform.provider_gateway import normalize_provider_error

                failure = normalize_provider_error(exc, model=req.model)
                if tasks:
                    tasks.transition(task_id, "failed", error=failure.as_dict())
                yield f"data: {json.dumps({'error': failure.as_dict()})}\n\n"
                yield "data: [DONE]\n\n"
            return

        # See the comment on the non-streaming path above — same fix needed
        # here. Keep yielding SSE comments while slow provider calls (notably
        # NVIDIA GLM/R1 cold starts) are still running, otherwise browsers and
        # reverse proxies can treat the request as idle before the first token.
        usage_holder: Dict[str, int] = {}
        response_task = asyncio.create_task(
            asyncio.to_thread(
                _generate_response,
                messages,
                model_engine,
                req.model,
                req.effort,
                _sampling_kwargs(req),
                usage_holder,
            )
        )
        while not response_task.done():
            yield ": keepalive\n\n"
            await asyncio.sleep(10)

        try:
            response_text = await response_task
        except Exception as exc:
            if tasks:
                from dabba.platform.provider_gateway import normalize_provider_error

                tasks.transition(
                    task_id,
                    "failed",
                    error=normalize_provider_error(exc, model=req.model).as_dict(),
                )
            raise

        # Chunk for the typewriter effect while PRESERVING all whitespace —
        # newlines and indentation carry the structure of YAML/JSON/code, so
        # `str.split()` (which collapses every run of whitespace into one space)
        # would flatten a Pod manifest onto a single line. Splitting on the
        # capture group keeps each whitespace run as its own token instead.
        tokens = [t for t in re.split(r"(\s+)", response_text) if t != ""]

        try:
            for token in tokens:
                yield handler.create_chunk(token, index=0)
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            if tasks:
                tasks.cancel(task_id)
            raise

        # Local dabba model never populates usage_holder — fall back to the
        # same word-count estimate the non-streaming path uses.
        if not usage_holder:
            last_message = _content_to_text(messages[-1]["content"]) if messages else ""
            prompt_tokens = len(last_message.split())
            completion_tokens = len(response_text.split())
            usage_holder = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }

        if tasks:
            tasks.append_event(task_id, "task.output.delta", {"content": response_text})
            tasks.transition(
                task_id,
                "completed",
                result={
                    "content": response_text,
                    "usage": usage_holder,
                    "model": req.model,
                },
            )
        yield handler.create_chunk(
            "", index=0, finish_reason="stop", usage=usage_holder
        )
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


def _create_chat_task(request: Request, req: ChatCompletionRequest):
    """Create a durable task when the caller supplies a valid Dabba session."""
    user = getattr(request.state, "dabba_user", None)
    if not user:
        return None
    try:
        from dabba.platform.services import TaskOrchestrator

        tasks = TaskOrchestrator()
        task = tasks.create(
            "chat",
            {
                "stream": req.stream,
                "effort": req.effort,
            },
            user_id=user["id"],
            model=req.model,
            idempotency_key=request.headers.get("x-idempotency-key"),
        )
        return tasks, task["id"]
    except Exception:
        # Durable tracking must never make a previously valid chat unavailable.
        return None


async def _stream_provider_response(
    req: ChatCompletionRequest,
    messages: list,
    model_engine: Optional[object],
    usage_out: Optional[Dict[str, int]] = None,
) -> AsyncGenerator[Optional[str], None]:
    del model_engine
    from dabba.api.agent_endpoints import _get_agent_proxy

    proxy = _get_agent_proxy()
    registry = proxy._get_provider_registry()
    resolved_effort = req.effort or getattr(proxy.cli_config, "effort", "medium")
    overrides = {k: v for k, v in _sampling_kwargs(req).items() if v is not None}
    cancelled = Event()
    iterator = registry.stream_chat(
        messages,
        model=req.model,
        effort=resolved_effort,
        usage_out=usage_out,
        cancel_event=cancelled,
        include_reasoning=True,
        **overrides,
    )

    pending = None
    try:
        while True:
            pending = asyncio.create_task(
                asyncio.to_thread(_next_stream_token, iterator)
            )
            while not pending.done():
                done, _ = await asyncio.wait({pending}, timeout=10)
                if not done:
                    yield None
            has_token, token = pending.result()
            if not has_token:
                break
            yield token
    finally:
        cancelled.set()

        def close_iterator(task=None):
            if task is not None and not task.cancelled():
                task.exception()
            iterator.close()

        if pending and not pending.done():
            pending.add_done_callback(close_iterator)
        else:
            close_iterator()


def _generate_response(
    messages: list,
    model_engine: Optional[object],
    model_name: Optional[str] = None,
    effort: Optional[str] = None,
    sampling: Optional[Dict] = None,
    usage_out: Optional[Dict[str, int]] = None,
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
        usage_out: pass a fresh dict to have it populated in place with real
            token counts if the resolved provider captures them — see
            registry.py's chat()/base.py's BaseProvider docstring for why
            this is an explicit per-call param, not shared instance state
            (providers are process-wide singletons reused across concurrent
            requests).

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
            return registry.chat(
                messages,
                model=model_name,
                effort=resolved_effort,
                usage_out=usage_out,
                **overrides,
            )
        except Exception as exc:
            from dabba.platform.provider_gateway import normalize_provider_error

            raise normalize_provider_error(exc, model=model_name) from exc

    # Local dabba model is text-only — flatten any multimodal content to text.
    local_messages = [
        {"role": m["role"], "content": _content_to_text(m["content"])} for m in messages
    ]
    last = local_messages[-1]["content"] if local_messages else ""

    # Do not send a one-word social greeting through the local generation
    # engine.  Small local checkpoints can take a minute to answer and often
    # return tokenizer artifacts (for example repeated ``<unk>`` tokens), which
    # makes the TUI and VS Code look like they never responded.  This fast path
    # keeps chat health checks and first-use conversations responsive while all
    # substantive prompts still use the configured model.
    if isinstance(last, str) and last.strip().casefold() in {
        "hi",
        "hello",
        "hey",
        "hi!",
        "hello!",
        "hey!",
    }:
        return "Hi! How can I help you today?"

    if _has_images(messages):
        # The client should route image requests to a vision model or OCR them
        # client-side; if an image still reaches the local model, say so plainly.
        note = (
            "\n\n[Note: an image was attached but the local dabba model can't "
            "read images. Select a vision model, or the app will OCR it to text.]"
        )
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
        f'I received your message: "{prompt[:100]}". '
        f"This is a placeholder response. To enable actual model responses, "
        f"configure a model engine when starting the server."
    )
