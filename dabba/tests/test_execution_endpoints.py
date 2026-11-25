import asyncio
import shutil
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from dabba.api.execution_endpoints import (
    ExecutionRequest,
    create_execution_router,
    execute_code,
    normalize_language,
)


@pytest.mark.parametrize(
    ("enabled", "host", "reason"),
    [
        (False, "127.0.0.1", "API code execution is disabled"),
        (True, "192.0.2.1", "Code execution is restricted to local clients"),
        (True, "::1", None),
    ],
)
def test_execution_availability_matches_execute_endpoint(enabled, host, reason):
    app = FastAPI()
    app.state.config = SimpleNamespace(enable_local_code_execution=enabled)
    app.include_router(create_execution_router())

    async def check():
        transport = httpx.ASGITransport(app=app, client=(host, 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            availability = await client.get("/v1/code/languages")
            assert availability.status_code == 200
            assert availability.json()["unavailableReason"] == reason

            if reason:
                response = await client.post(
                    "/v1/code/execute", json={"language": "python", "code": "print(1)"}
                )
                assert response.status_code == 403
                assert response.json()["detail"] == reason

    asyncio.run(check())


def test_language_aliases_are_normalized():
    assert normalize_language("py") == "python"
    assert normalize_language("js") == "javascript"
    assert normalize_language("c++") == "cpp"


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError, match="Unsupported language"):
        normalize_language("brainfuck")


@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 not installed")
def test_python_execution_captures_stdin_and_stdout():
    result = execute_code(
        ExecutionRequest(
            language="python",
            code="name = input()\nprint(f'Hello, {name}!')",
            stdin="Dabba\n",
        )
    )

    assert result["exitCode"] == 0
    assert result["stdout"] == "Hello, Dabba!\n"
    assert result["stderr"] == ""


@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 not installed")
def test_execution_timeout_is_reported():
    result = execute_code(
        ExecutionRequest(
            language="python",
            code="while True: pass",
            timeout=1,
        )
    )

    assert result["timedOut"] is True
    assert result["exitCode"] is None


@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc not installed")
def test_compiled_c_execution():
    result = execute_code(
        ExecutionRequest(
            language="c",
            code='#include <stdio.h>\nint main(void) { puts("compiled"); return 0; }',
        )
    )

    assert result["exitCode"] == 0
    assert result["stdout"] == "compiled\n"
