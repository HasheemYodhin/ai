"""Guest chat: a few free prompts for signed-out visitors.

Visitors on the public /try page can send ``GUEST_PROMPT_LIMIT`` prompts
without an account. Replies always come from one fixed model (shown to the
visitor only as "Auto") using the server's own provider key, so the limit is
enforced here, not in the browser:

* per guest id (a random id the browser keeps), ``DABBA_GUEST_PROMPT_LIMIT``
  prompts in total (default 5), and
* per client IP, ``DABBA_GUEST_IP_DAILY_LIMIT`` prompts per rolling 24 hours
  (default 20), so clearing browser storage doesn't reset the allowance.

Guests get plain chat only: no tools, files, images, agents or code execution.
Set ``DABBA_GUEST_CHAT=0`` to turn the feature off.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from dabba.platform.core import PlatformStore, get_platform_store, utc_ms

logger = logging.getLogger(__name__)

GUEST_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
DAY_MS = 24 * 60 * 60 * 1000
GUEST_SYSTEM_PROMPT = (
    "You are Dabba, a helpful AI assistant. Answer clearly and concisely. "
    "The user is trying Dabba without an account."
)


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def guest_prompt_limit() -> int:
    return _int_env("DABBA_GUEST_PROMPT_LIMIT", 5)


def guest_ip_daily_limit() -> int:
    return _int_env("DABBA_GUEST_IP_DAILY_LIMIT", 20)


def guest_chat_enabled() -> bool:
    return os.environ.get("DABBA_GUEST_CHAT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def client_ip(request: Request) -> str:
    """The client's IP, trusting ``DABBA_TRUSTED_PROXY_HOPS`` reverse proxies.

    Proxies such as Render append the address they saw to X-Forwarded-For, so
    the entry ``hops`` places from the right is the real client. Entries
    further left are client-supplied and can't be trusted. Default: 1 hop.
    """
    hops = _int_env("DABBA_TRUSTED_PROXY_HOPS", 1)
    forwarded = [
        part.strip()
        for part in request.headers.get("x-forwarded-for", "").split(",")
        if part.strip()
    ]
    if hops and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "unknown"


class GuestUsage:
    """Atomic check-and-count of guest prompts, stored in the platform DB."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()
        with self.store.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guest_usage (
                    key TEXT PRIMARY KEY,
                    count INTEGER NOT NULL,
                    window_start INTEGER NOT NULL
                )
                """
            )

    @staticmethod
    def _count(conn, key: str, now: int, window_ms: Optional[int]) -> int:
        row = conn.execute(
            "SELECT count, window_start FROM guest_usage WHERE key=?", (key,)
        ).fetchone()
        if not row:
            return 0
        if window_ms is not None and now - row["window_start"] >= window_ms:
            return 0  # rolling window expired
        return row["count"]

    @staticmethod
    def _bump(conn, key: str, now: int, window_ms: Optional[int], delta: int) -> None:
        row = conn.execute(
            "SELECT count, window_start FROM guest_usage WHERE key=?", (key,)
        ).fetchone()
        if row and (window_ms is None or now - row["window_start"] < window_ms):
            conn.execute(
                "UPDATE guest_usage SET count=MAX(0, count + ?) WHERE key=?",
                (delta, key),
            )
        elif delta > 0:
            conn.execute(
                "INSERT OR REPLACE INTO guest_usage (key, count, window_start) VALUES (?, ?, ?)",
                (key, delta, now),
            )

    def remaining(self, guest_id: str, ip: str) -> int:
        now = utc_ms()
        with self.store.transaction() as conn:
            used_guest = self._count(conn, f"guest:{guest_id}", now, None)
            used_ip = self._count(conn, f"ip:{ip}", now, DAY_MS)
        return max(
            0, min(guest_prompt_limit() - used_guest, guest_ip_daily_limit() - used_ip)
        )

    def consume(self, guest_id: str, ip: str) -> Optional[int]:
        """Count one prompt. Returns prompts left after it, or None if over the limit."""
        now = utc_ms()
        with self.store.transaction() as conn:
            used_guest = self._count(conn, f"guest:{guest_id}", now, None)
            used_ip = self._count(conn, f"ip:{ip}", now, DAY_MS)
            if used_guest >= guest_prompt_limit() or used_ip >= guest_ip_daily_limit():
                return None
            self._bump(conn, f"guest:{guest_id}", now, None, 1)
            self._bump(conn, f"ip:{ip}", now, DAY_MS, 1)
        return max(
            0,
            min(
                guest_prompt_limit() - used_guest - 1,
                guest_ip_daily_limit() - used_ip - 1,
            ),
        )

    def refund(self, guest_id: str, ip: str) -> None:
        """Give a prompt back when the model call failed, so errors don't cost a turn."""
        now = utc_ms()
        with self.store.transaction() as conn:
            self._bump(conn, f"guest:{guest_id}", now, None, -1)
            self._bump(conn, f"ip:{ip}", now, DAY_MS, -1)


GUEST_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class GuestMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class GuestChatRequest(BaseModel):
    guestId: str = Field(pattern=GUEST_ID_PATTERN)
    messages: List[GuestMessage] = Field(min_length=1, max_length=20)


def _limit_response() -> JSONResponse:
    return JSONResponse(
        {
            "detail": "You've used your free prompts. Sign up or log in to keep chatting.",
            "code": "guest_limit_reached",
            "remaining": 0,
        },
        status_code=429,
    )


def create_guest_router(
    usage: Optional[GuestUsage] = None, registry_factory=None
) -> APIRouter:
    """``usage`` and ``registry_factory`` are injectable for tests."""
    router = APIRouter(prefix="/v1/guest", tags=["guest"])
    state: Dict[str, Any] = {"usage": usage}

    def get_usage() -> GuestUsage:
        if state["usage"] is None:
            state["usage"] = GuestUsage()
        return state["usage"]

    def get_registry():
        if registry_factory is not None:
            return registry_factory()
        from dabba.api.agent_endpoints import _get_agent_proxy

        return _get_agent_proxy()._get_provider_registry()

    @router.get("/status")
    async def guest_status(request: Request, guestId: str):
        import re

        if not re.fullmatch(GUEST_ID_PATTERN, guestId):
            raise HTTPException(status_code=422, detail="Invalid guest id")
        available = guest_chat_enabled() and bool(
            get_registry().resolve_api_key(GUEST_MODEL)[0]
        )
        remaining = await asyncio.to_thread(
            get_usage().remaining, guestId, client_ip(request)
        )
        return {
            "available": available,
            "remaining": remaining,
            "limit": guest_prompt_limit(),
        }

    @router.post("/chat")
    async def guest_chat(request: Request, body: GuestChatRequest):
        if not guest_chat_enabled():
            raise HTTPException(
                status_code=404, detail="Guest chat is turned off on this server"
            )
        if body.messages[-1].role != "user":
            raise HTTPException(
                status_code=422, detail="The last message must be from the user"
            )

        registry = get_registry()
        if not registry.resolve_api_key(GUEST_MODEL)[0]:
            raise HTTPException(
                status_code=503,
                detail="Free prompts aren't available right now. Sign up or log in to chat.",
            )

        ip = client_ip(request)
        remaining = await asyncio.to_thread(get_usage().consume, body.guestId, ip)
        if remaining is None:
            return _limit_response()

        messages = [{"role": "system", "content": GUEST_SYSTEM_PROMPT}] + [
            {"role": m.role, "content": m.content} for m in body.messages
        ]

        async def event_stream():
            """Stream the reply as it's generated.

            Events: ``{"delta": text}`` for each piece, then
            ``{"done": true, "remaining": n}``, or ``{"error": ..., "remaining": n}``.
            Comment lines keep the connection alive during slow starts.
            """
            from dabba.providers.base import ReasoningDelta

            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            cancel = threading.Event()

            def produce() -> None:
                # The provider stream is blocking, so it runs in a thread and
                # hands pieces to the event loop through the queue.
                try:
                    for piece in registry.stream_chat(
                        messages,
                        model=GUEST_MODEL,
                        effort="medium",
                        max_tokens=2048,
                        thinking=False,  # skip Nemotron's reasoning phase: ~2x faster
                        cancel_event=cancel,
                    ):
                        if isinstance(piece, ReasoningDelta) or not piece:
                            continue
                        loop.call_soon_threadsafe(queue.put_nowait, ("delta", piece))
                    loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
                except Exception as exc:  # noqa: BLE001 - reported to the client below
                    loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))

            threading.Thread(target=produce, daemon=True, name="guest-chat").start()
            sent_text = False
            try:
                while True:
                    try:
                        kind, value = await asyncio.wait_for(queue.get(), timeout=5)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if kind == "delta":
                        sent_text = True
                        yield f"data: {json.dumps({'delta': value})}\n\n"
                    elif kind == "done":
                        yield f"data: {json.dumps({'done': True, 'remaining': remaining})}\n\n"
                        return
                    else:
                        logger.warning("Guest chat failed: %s", value)
                        left = remaining
                        if not sent_text:
                            # Nothing reached the visitor: don't charge the prompt.
                            await asyncio.to_thread(
                                get_usage().refund, body.guestId, ip
                            )
                            left = remaining + 1
                        payload = {
                            "error": "Dabba couldn't answer just now. Try again in a moment.",
                            "remaining": left,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                        return
            finally:
                cancel.set()  # visitor left or reply finished: stop the provider stream

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
