"""
Background/long-running process tools for the dabba agent.

Lets the agent start a process (e.g. a dev server), keep it running after
the tool call returns, poll its buffered output, and stop it later — unlike
shell_exec, which blocks for a single command's lifetime.

Process state lives in a module-level registry (mirroring the
_pending_approvals pattern in dabba/api/agent_endpoints.py) since neither
AgentProxy nor ToolRegistry keep long-lived state for tools themselves.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry
from dabba.tools.shell_tools import DEFAULT_PERMISSION_MANAGER, ShellPermissionManager, _spawn
from dabba.utils.logging import get_logger

logger = get_logger("dabba.tools.process_tools")

MAX_LOG_LINES = 2000


@dataclass
class ManagedProcess:
    """Tracks one background process and its buffered output."""

    process_id: str
    command: str
    proc: asyncio.subprocess.Process
    started_at: float = field(default_factory=time.monotonic)
    stdout_lines: deque = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    stderr_lines: deque = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    _readers: List[asyncio.Task] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.proc.returncode is None:
            return "running"
        return "exited" if self.proc.returncode == 0 else "failed"


# process_id -> ManagedProcess, one registry per interpreter process.
_PROCESSES: Dict[str, ManagedProcess] = {}


async def _pump(stream: asyncio.StreamReader, sink: deque) -> None:
    """Continuously read lines from a stream into a bounded buffer."""
    while True:
        line = await stream.readline()
        if not line:
            break
        sink.append(line.decode("utf-8", errors="replace").rstrip("\n"))


async def start_process(
    command: str,
    name: Optional[str] = None,
    cwd: Optional[str] = None,
    permission_manager: Optional[ShellPermissionManager] = None,
) -> Dict[str, object]:
    """
    Start a command as a background process and return immediately.

    Args:
        command: Shell command to run (e.g. a dev server).
        name: Optional friendly label; a process_id is always generated.
        cwd: Working directory to run in.
        permission_manager: Permission manager for security checks.

    Returns:
        Dict with keys: process_id, name, command, pid, status.

    Raises:
        PermissionError: If the command is not allowed.
        ValueError: If the command is empty.
    """
    pm = permission_manager or DEFAULT_PERMISSION_MANAGER
    if not command or not command.strip():
        raise ValueError("Command cannot be empty")
    if not pm.is_command_allowed(command):
        raise PermissionError(f"Command '{command}' is not in the allowed list.")
    scope_error = pm.check_paths_scoped(command, cwd=cwd)
    if scope_error:
        raise PermissionError(scope_error)

    proc = await _spawn(command, cwd, "auto")
    process_id = uuid.uuid4().hex[:12]
    managed = ManagedProcess(process_id=process_id, command=command, proc=proc)
    if proc.stdout:
        managed._readers.append(asyncio.ensure_future(_pump(proc.stdout, managed.stdout_lines)))
    if proc.stderr:
        managed._readers.append(asyncio.ensure_future(_pump(proc.stderr, managed.stderr_lines)))

    _PROCESSES[process_id] = managed
    logger.info("Started background process '%s' (pid=%s): %s", process_id, proc.pid, command[:100])

    return {
        "process_id": process_id,
        "name": name or process_id,
        "command": command,
        "pid": proc.pid,
        "status": managed.status,
    }


def list_processes() -> List[Dict[str, object]]:
    """
    List all background processes started this session.

    Returns:
        List of dicts with process_id, command, pid, status, uptime_seconds.
    """
    result = []
    for p in _PROCESSES.values():
        result.append({
            "process_id": p.process_id,
            "command": p.command,
            "pid": p.proc.pid,
            "status": p.status,
            "uptime_seconds": round(time.monotonic() - p.started_at, 1),
        })
    return result


def get_process_output(process_id: str, tail: int = 200) -> Dict[str, object]:
    """
    Get buffered stdout/stderr for a background process.

    Args:
        process_id: ID returned by start_process.
        tail: Max number of most-recent lines to return per stream.

    Returns:
        Dict with process_id, status, stdout (str), stderr (str).

    Raises:
        KeyError: If process_id is unknown.
    """
    managed = _PROCESSES.get(process_id)
    if managed is None:
        raise KeyError(f"Unknown process_id: '{process_id}'")

    return {
        "process_id": process_id,
        "status": managed.status,
        "returncode": managed.proc.returncode,
        "stdout": "\n".join(list(managed.stdout_lines)[-tail:]),
        "stderr": "\n".join(list(managed.stderr_lines)[-tail:]),
    }


async def stop_process(process_id: str, force: bool = False) -> Dict[str, object]:
    """
    Stop a background process.

    Args:
        process_id: ID returned by start_process.
        force: Send SIGKILL instead of SIGTERM.

    Returns:
        Dict with process_id and final status.

    Raises:
        KeyError: If process_id is unknown.
    """
    managed = _PROCESSES.get(process_id)
    if managed is None:
        raise KeyError(f"Unknown process_id: '{process_id}'")

    if managed.proc.returncode is None:
        if force:
            managed.proc.kill()
        else:
            managed.proc.terminate()
        try:
            await asyncio.wait_for(managed.proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            managed.proc.kill()
            await managed.proc.wait()

    for reader in managed._readers:
        reader.cancel()

    logger.info("Stopped background process '%s' (status=%s)", process_id, managed.status)
    return {"process_id": process_id, "status": managed.status}


def register_process_tools(registry: ToolRegistry) -> None:
    """
    Register background process tools with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
    """
    registry.register(
        ToolDefinition(
            name="process_start",
            description=(
                "Start a long-running command (e.g. a dev server) in the "
                "background and return immediately. Use process_output to "
                "poll its logs and process_stop to end it."
            ),
            parameters=[
                ToolParameter(name="command", type="string", description="Command to run in the background."),
                ToolParameter(name="name", type="string", description="Friendly label for the process.", required=False, default=None),
                ToolParameter(name="cwd", type="string", description="Working directory to run in.", required=False, default=None),
            ],
            handler=start_process,
            handler_sync=False,
            category="process",
        )
    )
    registry.register(
        ToolDefinition(
            name="process_list",
            description="List all background processes started this session.",
            parameters=[],
            handler=list_processes,
            handler_sync=True,
            category="process",
        )
    )
    registry.register(
        ToolDefinition(
            name="process_output",
            description="Get buffered stdout/stderr from a background process.",
            parameters=[
                ToolParameter(name="process_id", type="string", description="ID returned by process_start."),
                ToolParameter(name="tail", type="integer", description="Max lines to return per stream.", required=False, default=200),
            ],
            handler=get_process_output,
            handler_sync=True,
            category="process",
        )
    )
    registry.register(
        ToolDefinition(
            name="process_stop",
            description="Stop a background process started with process_start.",
            parameters=[
                ToolParameter(name="process_id", type="string", description="ID returned by process_start."),
                ToolParameter(name="force", type="boolean", description="Send SIGKILL instead of SIGTERM.", required=False, default=False),
            ],
            handler=stop_process,
            handler_sync=False,
            category="process",
        )
    )
