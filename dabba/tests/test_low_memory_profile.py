import asyncio
from unittest.mock import Mock

import httpx
from fastapi.routing import APIRoute

from dabba.api import create_app
from dabba.platform import core
from dabba.platform.services import IdentityService


def test_constrained_server_serializes_account_generation_and_rejects_large_uploads(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DABBA_LOW_MEMORY", "true")
    monkeypatch.setattr(core, "_default_store", None)

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    monkeypatch.setattr(
        IdentityService,
        "authenticate",
        lambda self, token: {"id": token, "role": "member"},
    )

    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        app = create_app(model_engine=Mock())

        async def slow_generation():
            entered.set()
            await release.wait()
            return {"ok": True}

        chat = "/v1/chat/completions"
        app.router.routes.insert(0, APIRoute(chat, slow_generation, methods=["POST"]))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            base_url="http://test", transport=transport
        ) as client:
            headers = {"Authorization": "Bearer test-account"}
            first = asyncio.create_task(client.post(chat, headers=headers))
            try:
                await asyncio.wait_for(entered.wait(), timeout=3)
                second = await client.post(chat, headers=headers)
                assert (
                    second.status_code == 429 and second.headers["Retry-After"] == "3"
                )
                assert (await client.get("/ready")).status_code == 200
                oversized = await client.post(
                    "/v1/transcribe", headers={**headers, "Content-Length": "10000000"}
                )
                assert oversized.status_code == 413
            finally:
                release.set()
            assert (await first).status_code == 200
            assert (await client.post(chat, headers=headers)).status_code == 200

    asyncio.run(check())
