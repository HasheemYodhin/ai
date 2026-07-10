"""
SSH remote execution tools for the dabba agent.

Shells out to the system `ssh`/`scp` binaries rather than bundling a
paramiko dependency, so it picks up the user's existing ~/.ssh/config,
keys, and known_hosts unmodified.

Remote execution is capability-scoped to an explicit host allowlist
(CliConfig.allowed_ssh_hosts) — unlike local shell_exec, there is no
"sandbox=False, run anything" escape hatch, because a wrong host here
means running commands on a machine that isn't this one.
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry
from dabba.utils.logging import get_logger

logger = get_logger("dabba.tools.ssh_tools")


@dataclass
class SSHPermissionManager:
    """
    Host allowlist for SSH/SCP tools.

    Args:
        allowed_hosts: Hosts (or ~/.ssh/config aliases) permitted to connect
            to. Empty means no host is allowed — must be configured
            explicitly via CliConfig.allowed_ssh_hosts or add_allowed_host.
    """

    allowed_hosts: Set[str] = field(default_factory=set)

    def is_host_allowed(self, host: str) -> bool:
        return host in self.allowed_hosts

    def add_allowed_host(self, host: str) -> None:
        self.allowed_hosts.add(host)

    @classmethod
    def from_cli_config(cls) -> "SSHPermissionManager":
        from dabba.cli.config import CliConfig
        config = CliConfig.load()
        return cls(allowed_hosts=set(getattr(config, "allowed_ssh_hosts", []) or []))


DEFAULT_SSH_PERMISSION_MANAGER = SSHPermissionManager.from_cli_config()


async def _run_argv(argv: List[str], timeout: int) -> Dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "returncode": proc.returncode or 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "timed_out": False,
        }
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"returncode": -1, "stdout": "", "stderr": f"Timed out after {timeout}s", "timed_out": True}


async def ssh_exec(
    host: str,
    command: str,
    user: Optional[str] = None,
    port: int = 22,
    timeout: int = 30,
    permission_manager: Optional[SSHPermissionManager] = None,
) -> Dict[str, object]:
    """
    Execute a command on a remote host over SSH.

    Args:
        host: Hostname or ~/.ssh/config alias. Must be in the allowlist.
        command: Command to run on the remote host.
        user: Remote username (omit to use ssh_config/default).
        port: SSH port.
        timeout: Max execution time in seconds.
        permission_manager: Host allowlist checker.

    Returns:
        Dict with keys: host, command, returncode, stdout, stderr, timed_out.

    Raises:
        PermissionError: If the host is not in the allowlist.
        ValueError: If host or command is empty.
    """
    pm = permission_manager or DEFAULT_SSH_PERMISSION_MANAGER
    if not host or not host.strip():
        raise ValueError("Host cannot be empty")
    if not command or not command.strip():
        raise ValueError("Command cannot be empty")
    if not pm.is_host_allowed(host):
        raise PermissionError(
            f"Host '{host}' is not in the SSH allowlist. "
            "Add it to CliConfig.allowed_ssh_hosts to permit connections."
        )

    target = f"{user}@{host}" if user else host
    argv = [
        "ssh",
        "-p", str(port),
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        target,
        command,
    ]
    logger.info("SSH exec on '%s': %s", target, command[:100])
    result = await _run_argv(argv, timeout)
    return {"host": host, "command": command, **result}


async def scp_copy(
    source: str,
    destination: str,
    host: str,
    user: Optional[str] = None,
    port: int = 22,
    direction: str = "upload",
    timeout: int = 60,
    permission_manager: Optional[SSHPermissionManager] = None,
) -> Dict[str, object]:
    """
    Copy a file to or from a remote host over SCP.

    Args:
        source: Local path (upload) or remote path (download).
        destination: Remote path (upload) or local path (download).
        host: Hostname or ~/.ssh/config alias. Must be in the allowlist.
        user: Remote username.
        port: SSH port.
        direction: "upload" (local -> remote) or "download" (remote -> local).
        timeout: Max execution time in seconds.
        permission_manager: Host allowlist checker.

    Returns:
        Dict with keys: host, direction, returncode, stdout, stderr, timed_out.

    Raises:
        PermissionError: If the host is not in the allowlist.
        ValueError: If direction is invalid.
    """
    pm = permission_manager or DEFAULT_SSH_PERMISSION_MANAGER
    if direction not in ("upload", "download"):
        raise ValueError("direction must be 'upload' or 'download'")
    if not pm.is_host_allowed(host):
        raise PermissionError(f"Host '{host}' is not in the SSH allowlist.")

    target = f"{user}@{host}" if user else host
    if direction == "upload":
        argv = ["scp", "-P", str(port), "-o", "StrictHostKeyChecking=accept-new", source, f"{target}:{destination}"]
    else:
        argv = ["scp", "-P", str(port), "-o", "StrictHostKeyChecking=accept-new", f"{target}:{source}", destination]

    logger.info("SCP %s: %s -> %s", direction, source, destination)
    result = await _run_argv(argv, timeout)
    return {"host": host, "direction": direction, **result}


def register_ssh_tools(registry: ToolRegistry) -> None:
    """
    Register SSH remote execution tools with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
    """
    registry.register(
        ToolDefinition(
            name="ssh_exec",
            description="Execute a command on a remote host over SSH. Host must be pre-approved in the allowlist.",
            parameters=[
                ToolParameter(name="host", type="string", description="Hostname or SSH config alias."),
                ToolParameter(name="command", type="string", description="Command to run remotely."),
                ToolParameter(name="user", type="string", description="Remote username.", required=False, default=None),
                ToolParameter(name="port", type="integer", description="SSH port.", required=False, default=22),
                ToolParameter(name="timeout", type="integer", description="Max execution time in seconds.", required=False, default=30),
            ],
            handler=ssh_exec,
            handler_sync=False,
            category="remote",
        )
    )
    registry.register(
        ToolDefinition(
            name="scp_copy",
            description="Copy a file to/from a remote host over SCP. Host must be pre-approved in the allowlist.",
            parameters=[
                ToolParameter(name="source", type="string", description="Local path (upload) or remote path (download)."),
                ToolParameter(name="destination", type="string", description="Remote path (upload) or local path (download)."),
                ToolParameter(name="host", type="string", description="Hostname or SSH config alias."),
                ToolParameter(name="user", type="string", description="Remote username.", required=False, default=None),
                ToolParameter(name="port", type="integer", description="SSH port.", required=False, default=22),
                ToolParameter(name="direction", type="string", description="'upload' or 'download'.", required=False, default="upload"),
                ToolParameter(name="timeout", type="integer", description="Max execution time in seconds.", required=False, default=60),
            ],
            handler=scp_copy,
            handler_sync=False,
            category="remote",
        )
    )
