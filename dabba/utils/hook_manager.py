"""
User-configurable event hooks for the dabba agent.

Lets a user register shell commands that run automatically at specific
points in the agent loop (session start/end, a user prompt being submitted,
before/after a tool call). Modeled on Claude Code's hooks: a pre_tool_call
hook that exits non-zero *blocks* that tool call from running, which gives
users a way to enforce custom policy (e.g. "never allow a push to main even
if the dangerous-tool prompt is answered yes") without touching agent code.
Every other event is fire-and-forget — useful for logging, notifications,
or side effects, but it can't stop the agent.

Storage: ~/.config/dabba/hooks.json  (Linux/Mac)
         %APPDATA%/dabba/hooks.json   (Windows)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dabba.utils.logging import get_logger

logger = get_logger("dabba.utils.hook_manager")

VALID_EVENTS = {
    "session_start",
    "session_end",
    "user_prompt_submit",
    "pre_tool_call",
    "post_tool_call",
}

# Only these events can block; every other event is a fire-and-forget notification.
BLOCKING_EVENTS = {"pre_tool_call"}

DEFAULT_TIMEOUT_SECONDS = 30
MAX_RUNS_LOGGED = 200


def _default_hooks_path() -> Path:
    """Return the platform-appropriate path for hooks.json."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "dabba" / "hooks.json"


@dataclass
class HookRunResult:
    hook_id: str
    event: str
    exit_code: Optional[int]
    stdout: str
    stderr: str
    blocked: bool
    duration_ms: float
    error: str = ""


class HookManager:
    """
    Loads/persists hook definitions and runs them against agent events.

    Each hook is a plain dict:
        {
            "id": str,
            "event": one of VALID_EVENTS,
            "matcher": "",  # comma-separated tool names; empty matches every tool
            "command": str,  # shell command, run via the system shell
            "timeout": int,  # seconds
            "enabled": bool,
            "created_at": float,
        }

    The command receives the event context as JSON on stdin, and in the
    DABBA_HOOK_EVENT / DABBA_HOOK_CONTEXT environment variables.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else _default_hooks_path()
        self._hooks: List[Dict[str, Any]] = []
        self._recent_runs: List[Dict[str, Any]] = []
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._hooks = [
                        h
                        for h in data
                        if isinstance(h, dict)
                        and h.get("event") in VALID_EVENTS
                        and h.get("id")
                    ]
                    logger.info("Loaded %d hooks from %s", len(self._hooks), self._path)
        except Exception as exc:
            logger.warning("Could not load hooks from %s: %s", self._path, exc)
            self._hooks = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._hooks, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Could not save hooks to %s: %s", self._path, exc)

    # ── CRUD ─────────────────────────────────────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        return list(self._hooks)

    def create(
        self,
        event: str,
        command: str,
        matcher: str = "",
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        if event not in VALID_EVENTS:
            raise ValueError(
                f"Unknown hook event: {event!r}. Must be one of {sorted(VALID_EVENTS)}"
            )
        if not command.strip():
            raise ValueError("Hook command cannot be empty.")
        hook = {
            "id": uuid.uuid4().hex[:12],
            "event": event,
            "matcher": matcher.strip(),
            "command": command,
            "timeout": max(1, int(timeout)),
            "enabled": bool(enabled),
            "created_at": time.time(),
        }
        self._hooks.append(hook)
        self._save()
        logger.info("Hook created: %s on %s", hook["id"], event)
        return hook

    def update(self, hook_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        for hook in self._hooks:
            if hook["id"] == hook_id:
                if "event" in changes and changes["event"] not in VALID_EVENTS:
                    raise ValueError(f"Unknown hook event: {changes['event']!r}")
                for key in ("event", "matcher", "command", "timeout", "enabled"):
                    if key in changes:
                        hook[key] = changes[key]
                self._save()
                return hook
        raise KeyError(f"Unknown hook id: {hook_id}")

    def delete(self, hook_id: str) -> bool:
        before = len(self._hooks)
        self._hooks = [h for h in self._hooks if h["id"] != hook_id]
        if len(self._hooks) != before:
            self._save()
            return True
        return False

    def recent_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._recent_runs[-limit:]

    # ── Execution ────────────────────────────────────────────────────────

    @staticmethod
    def _matches(hook: Dict[str, Any], tool_name: str) -> bool:
        matcher = str(hook.get("matcher") or "").strip()
        if not matcher:
            return True
        return any(part.strip() == tool_name for part in matcher.split(","))

    async def run(self, event: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run all enabled hooks registered for *event*, in registration order.

        Returns {"blocked": bool, "reason": str}. Only pre_tool_call hooks
        can set blocked=True (a non-zero exit code); every other event
        always reports blocked=False regardless of exit code, since there's
        nothing in the loop for it to stop. Stops at the first hook that
        blocks rather than running the rest.
        """
        tool_name = str(context.get("tool_name") or "")
        matching = [
            h
            for h in self._hooks
            if h.get("enabled", True)
            and h.get("event") == event
            and self._matches(h, tool_name)
        ]
        if not matching:
            return {"blocked": False, "reason": ""}

        payload = json.dumps(context, default=str)
        for hook in matching:
            result = await self._run_one(hook, event, payload)
            self._recent_runs.append(
                {
                    "hook_id": hook["id"],
                    "event": event,
                    "tool": tool_name,
                    "exit_code": result.exit_code,
                    "blocked": result.blocked,
                    "stdout": result.stdout[:2000],
                    "stderr": result.stderr[:2000],
                    "error": result.error,
                    "duration_ms": round(result.duration_ms, 1),
                    "timestamp": time.time(),
                }
            )
            del self._recent_runs[:-MAX_RUNS_LOGGED]
            if result.blocked:
                reason = (
                    result.stderr or result.stdout or f"Hook exited {result.exit_code}"
                ).strip()
                logger.info("Hook %s blocked %s: %s", hook["id"], event, reason[:200])
                return {"blocked": True, "reason": reason[:500]}
        return {"blocked": False, "reason": ""}

    async def _run_one(
        self, hook: Dict[str, Any], event: str, payload: str
    ) -> HookRunResult:
        start = time.monotonic()
        env = {**os.environ, "DABBA_HOOK_EVENT": event, "DABBA_HOOK_CONTEXT": payload}
        try:
            proc = await asyncio.create_subprocess_shell(
                hook["command"],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(payload.encode("utf-8", errors="replace")),
                    timeout=hook.get("timeout", DEFAULT_TIMEOUT_SECONDS),
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                duration = (time.monotonic() - start) * 1000
                return HookRunResult(
                    hook["id"],
                    event,
                    None,
                    "",
                    "",
                    False,
                    duration,
                    error="Hook timed out",
                )

            duration = (time.monotonic() - start) * 1000
            exit_code = proc.returncode
            blocked = event in BLOCKING_EVENTS and exit_code not in (0, None)
            return HookRunResult(
                hook["id"],
                event,
                exit_code,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
                blocked,
                duration,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.warning("Hook %s failed to run: %s", hook["id"], exc)
            return HookRunResult(
                hook["id"], event, None, "", "", False, duration, error=str(exc)
            )


# Module-level singleton — one shared instance for the whole server process.
_instance: Optional[HookManager] = None


def get_hook_manager() -> HookManager:
    """Return (or create) the shared HookManager singleton."""
    global _instance
    if _instance is None:
        _instance = HookManager()
    return _instance
