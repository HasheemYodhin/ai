"""Allowlisted, resource-bounded code execution for frontend code blocks."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from dabba.api.auth import ApiKeyAuth
from dabba.api.rate_limiter import RateLimiter


MAX_CODE_BYTES = 100_000
MAX_STDIN_BYTES = 32_000
MAX_OUTPUT_BYTES = 64_000
MAX_TIMEOUT_SECONDS = 10


class ExecutionRequest(BaseModel):
    language: str
    code: str = Field(min_length=1)
    stdin: str = ""
    timeout: int = Field(default=5, ge=1, le=MAX_TIMEOUT_SECONDS)


@dataclass(frozen=True)
class LanguageSpec:
    aliases: tuple[str, ...]
    extension: str
    runtime: tuple[str, ...]
    compile: Optional[tuple[str, ...]] = None


LANGUAGES: Dict[str, LanguageSpec] = {
    "python": LanguageSpec(("py", "python3"), ".py", ("python3", "{source}")),
    "javascript": LanguageSpec(("js", "node"), ".js", ("node", "{source}")),
    "typescript": LanguageSpec(("ts", "tsx"), ".ts", ("tsx", "{source}")),
    "java": LanguageSpec((), ".java", ("java", "-cp", "{dir}", "{class}"), ("javac", "{source}")),
    "c": LanguageSpec((), ".c", ("{binary}",), ("gcc", "{source}", "-O0", "-o", "{binary}")),
    "cpp": LanguageSpec(("c++", "cc"), ".cpp", ("{binary}",), ("g++", "{source}", "-O0", "-o", "{binary}")),
    "go": LanguageSpec(("golang",), ".go", ("go", "run", "{source}")),
    "rust": LanguageSpec(("rs",), ".rs", ("{binary}",), ("rustc", "{source}", "-o", "{binary}")),
    "ruby": LanguageSpec(("rb",), ".rb", ("ruby", "{source}")),
    "php": LanguageSpec((), ".php", ("php", "{source}")),
    "bash": LanguageSpec(("sh", "shell", "zsh"), ".sh", ("bash", "--noprofile", "--norc", "{source}")),
    "kotlin": LanguageSpec(("kt",), ".kt", ("java", "-jar", "{jar}"), ("kotlinc", "{source}", "-include-runtime", "-d", "{jar}")),
    "swift": LanguageSpec((), ".swift", ("swift", "{source}")),
}


def normalize_language(value: str) -> str:
    value = value.lower().strip()
    for name, spec in LANGUAGES.items():
        if value == name or value in spec.aliases:
            return name
    raise ValueError(f"Unsupported language '{value}'")


def _tool_available(command: str) -> bool:
    return command.startswith("{") or shutil.which(command) is not None


def available_languages() -> List[dict]:
    result = []
    for name, spec in LANGUAGES.items():
        commands = [spec.runtime[0]] + ([spec.compile[0]] if spec.compile else [])
        result.append({"id": name, "available": all(_tool_available(c) for c in commands)})
    return result


def _limit_process() -> None:
    """Apply conservative POSIX limits inside the child before exec."""
    if os.name != "posix":
        return
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _expand(parts: tuple[str, ...], values: Dict[str, str]) -> List[str]:
    return [values.get(part[1:-1], part) if part.startswith("{") and part.endswith("}") else part for part in parts]


def _trim_output(value: str) -> tuple[str, bool]:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return value, False
    return encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") + "\n… output truncated", True


def execute_code(req: ExecutionRequest) -> dict:
    if len(req.code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError("Code is too large (100 KB maximum)")
    if len(req.stdin.encode("utf-8")) > MAX_STDIN_BYTES:
        raise ValueError("Standard input is too large (32 KB maximum)")

    language = normalize_language(req.language)
    spec = LANGUAGES[language]
    commands = [spec.runtime[0]] + ([spec.compile[0]] if spec.compile else [])
    missing = [c for c in commands if not _tool_available(c)]
    if missing:
        raise RuntimeError(f"Runtime not installed: {', '.join(missing)}")

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="dabba-run-") as tmp:
        tmp_path = Path(tmp)
        class_name = "Main"
        if language == "java":
            match = re.search(r"public\s+class\s+([A-Za-z_$][\w$]*)", req.code)
            if match:
                class_name = match.group(1)
        source = tmp_path / f"{class_name if language == 'java' else 'main'}{spec.extension}"
        binary = tmp_path / "program"
        jar = tmp_path / "program.jar"
        source.write_text(req.code, encoding="utf-8")
        values = {"source": str(source), "dir": str(tmp_path), "binary": str(binary), "jar": str(jar), "class": class_name}
        run_kwargs = {
            "cwd": str(tmp_path), "capture_output": True, "text": True,
            "timeout": req.timeout, "preexec_fn": _limit_process if os.name == "posix" else None,
        }

        if spec.compile:
            try:
                compiled = subprocess.run(_expand(spec.compile, values), **run_kwargs)
            except subprocess.TimeoutExpired:
                return {"exitCode": None, "stdout": "", "stderr": "Compilation timed out", "timedOut": True, "durationMs": int((time.monotonic() - started) * 1000), "language": language}
            if compiled.returncode != 0:
                stderr, truncated = _trim_output(compiled.stderr or compiled.stdout)
                return {"exitCode": compiled.returncode, "stdout": "", "stderr": stderr, "timedOut": False, "truncated": truncated, "durationMs": int((time.monotonic() - started) * 1000), "language": language, "phase": "compile"}

        try:
            completed = subprocess.run(_expand(spec.runtime, values), input=req.stdin, **run_kwargs)
            stdout, out_truncated = _trim_output(completed.stdout)
            stderr, err_truncated = _trim_output(completed.stderr)
            return {"exitCode": completed.returncode, "stdout": stdout, "stderr": stderr, "timedOut": False, "truncated": out_truncated or err_truncated, "durationMs": int((time.monotonic() - started) * 1000), "language": language, "phase": "run"}
        except subprocess.TimeoutExpired as exc:
            stdout, _ = _trim_output((exc.stdout or "") if isinstance(exc.stdout, str) else "")
            stderr, _ = _trim_output((exc.stderr or "") if isinstance(exc.stderr, str) else "")
            return {"exitCode": None, "stdout": stdout, "stderr": stderr or f"Execution timed out after {req.timeout}s", "timedOut": True, "durationMs": int((time.monotonic() - started) * 1000), "language": language, "phase": "run"}


def create_execution_router(auth: Optional[ApiKeyAuth] = None, rate_limiter: Optional[RateLimiter] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/code", tags=["code-execution"])

    async def authorize(request: Request) -> Optional[str]:
        return await auth(request) if auth else None

    @router.get("/languages")
    async def languages(_: Optional[str] = Depends(authorize)):
        return {"languages": available_languages()}

    @router.post("/execute")
    async def execute(req: ExecutionRequest, request: Request, api_key: Optional[str] = Depends(authorize)):
        if rate_limiter:
            await rate_limiter.check_request(request, api_key)
        try:
            return await __import__("asyncio").to_thread(execute_code, req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
