"""
Shell command execution tools for the dabba agent.

Provides secure command execution with allow/block lists,
permission management, timeout handling, and streaming output.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shlex
import shutil
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry
from dabba.config.agent_config import AgentConfig
from dabba.utils.logging import get_logger

logger = get_logger("dabba.tools.shell_tools")

# Commands whose arguments can destroy or alter data outside the working
# directory. These are additionally path-scoped: if any path argument
# resolves outside `cwd`, the call is rejected regardless of the allow list.
PATH_SCOPED_COMMANDS: Set[str] = {"rm", "mv", "chmod", "chown", "cp"}


@dataclass
class ShellPermissionManager:
    """
    Manages allowed and blocked commands for shell execution.

    Args:
        allowed_commands: Set of commands allowed to run.
        blocked_commands: Set of commands banned from running.
        sandbox: If True, only explicitly allowed commands may run.
    """

    allowed_commands: Set[str] = field(default_factory=lambda: {
        "ls", "cat", "head", "tail", "echo", "grep", "find",
        "python", "python3", "node", "npm", "npx", "git", "curl", "wget",
        "mkdir", "cp", "mv", "rm", "touch", "chmod", "pip", "pwd",
        "sort", "wc", "uniq", "diff", "tee", "which", "file",
        "tar", "gzip", "gunzip", "zip", "unzip",
        "make", "cmake", "gcc", "g++", "clang", "rustc", "cargo",
        "deno", "bun", "yarn", "pnpm",
        "ps", "df", "du", "free", "uptime", "env",
        "uvicorn", "gunicorn", "flask", "django-admin", "pytest",
        "bash", "sh", "zsh",
    })
    blocked_commands: Set[str] = field(default_factory=lambda: {
        "sudo", "su", "chown", "passwd", "kill", "pkill",
        "shutdown", "reboot", "init", "systemctl",
        "dd", "mkfs", "fdisk", "mount", "umount",
        "iptables", "ufw", "ss", "netstat",
        "nc", "ncat", "socat",
        "nmap", "masscan",
        "wireshark", "tshark",
        "cryptsetup", "openssl",
        "docker", "podman", "containerd",
    })
    sandbox: bool = True

    def is_command_allowed(self, command: str) -> bool:
        """
        Check if a command is allowed to execute.

        Extracts the base command (first word, handling pipes) and
        checks against the allow/block lists.

        Args:
            command: Full command string.

        Returns:
            True if the command is permitted.
        """
        base_cmd = self._extract_base_command(command)
        if not base_cmd:
            return False

        if base_cmd in self.blocked_commands:
            return False

        if self.sandbox and base_cmd not in self.allowed_commands:
            # If command starts with relative path (e.g. ./start.sh) allow it.
            try:
                parts = shlex.split(command)
                if parts and (parts[0].startswith("./") or parts[0].startswith("../") or parts[0].startswith("/")):
                    return True
            except Exception:
                pass
            return False

        return True

    def check_paths_scoped(self, command: str, cwd: Optional[str] = None) -> Optional[str]:
        """
        For destructive commands (rm/mv/chmod/chown/cp), verify every path-like
        argument resolves inside `cwd` (defaults to the process cwd).

        Args:
            command: Full command string.
            cwd: Directory paths must stay within. Defaults to os.getcwd().

        Returns:
            None if safe (or not a path-scoped command); otherwise an error
            message describing the out-of-scope path.
        """
        base_cmd = self._extract_base_command(command)
        if base_cmd not in PATH_SCOPED_COMMANDS:
            return None

        root = Path(cwd or os.getcwd()).expanduser().resolve()
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return f"Could not parse command for path scoping: {exc}"

        for token in parts[1:]:
            if token.startswith("-") or "=" in token:
                continue
            candidate = Path(token).expanduser()
            resolved = candidate if candidate.is_absolute() else (root / candidate)
            resolved = resolved.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                return (
                    f"'{base_cmd}' targets '{resolved}', which is outside the "
                    f"working directory '{root}'. Refusing to run."
                )
        return None

    def add_allowed(self, command: str) -> None:
        """Add a command to the allowed list."""
        self.allowed_commands.add(command)

    def add_blocked(self, command: str) -> None:
        """Add a command to the blocked list."""
        self.blocked_commands.add(command)

    @staticmethod
    def _extract_base_command(command: str) -> str:
        """
        Extract the base executable name from a command string.

        Handles pipes, redirects, env vars, and path prefixes.

        Args:
            command: Full command string.

        Returns:
            Base command name or empty string.
        """
        parts = shlex.split(command)
        if not parts:
            return ""

        cmd = parts[0]

        cmd = os.path.basename(cmd)

        return cmd

    @classmethod
    def from_config(cls, config: AgentConfig) -> ShellPermissionManager:
        """
        Create a permission manager from an AgentConfig.

        Args:
            config: Agent configuration.

        Returns:
            Configured ShellPermissionManager.
        """
        return cls(
            allowed_commands=set(config.allowed_commands),
            blocked_commands=set(config.blocked_commands),
            sandbox=config.sandbox_shell,
        )


DEFAULT_PERMISSION_MANAGER = ShellPermissionManager()


async def execute_command(
    command: str,
    timeout: int = 30,
    stream: bool = False,
    cwd: Optional[str] = None,
    shell_type: str = "auto",
    permission_manager: Optional[ShellPermissionManager] = None,
) -> Dict[str, object]:
    """
    Execute a shell command with security checks and timeout.

    Args:
        command: Shell command to execute.
        timeout: Maximum execution time in seconds.
        stream: If True, stream stdout as it arrives (included in output).
        cwd: Working directory to run in and scope destructive commands to.
            Defaults to the current process directory.
        shell_type: "auto" (OS default: sh/bash on POSIX, cmd.exe on
            Windows), "bash", or "powershell" (uses pwsh/powershell.exe).
        permission_manager: Permission manager for security checks.
            Uses DEFAULT_PERMISSION_MANAGER if not provided.

    Returns:
        Dict with keys: command, returncode, stdout, stderr, timed_out.

    Raises:
        PermissionError: If the command is not allowed, or a destructive
            command targets a path outside `cwd`.
        ValueError: If the command is empty.
    """
    pm = permission_manager or DEFAULT_PERMISSION_MANAGER
    if not command or not command.strip():
        raise ValueError("Command cannot be empty")

    if not pm.is_command_allowed(command):
        raise PermissionError(
            f"Command '{command}' is not in the allowed list. "
            "To allow it, add it to ShellPermissionManager.allowed_commands."
        )

    scope_error = pm.check_paths_scoped(command, cwd=cwd)
    if scope_error:
        raise PermissionError(scope_error)

    try:
        if stream:
            result = await _run_command_streaming(command, timeout, cwd=cwd, shell_type=shell_type)
        else:
            result = await _run_command_blocking(command, timeout, cwd=cwd, shell_type=shell_type)
    except asyncio.CancelledError:
        logger.warning("Command was cancelled: %s", command[:100])
        return {
            "command": command,
            "returncode": -1,
            "stdout": "",
            "stderr": "Command was cancelled",
            "timed_out": False,
        }

    logger.info(
        "Command '%s' returned exit code %d (%.1fs)",
        command[:100],
        result["returncode"],
        result.get("_duration", 0),
    )

    result.pop("_duration", None)

    return {
        "command": command,
        "returncode": result.get("returncode", -1),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "timed_out": result.get("timed_out", False),
    }


def _resolve_shell(shell_type: str) -> Optional[List[str]]:
    """
    Resolve the executable + leading args for the requested shell_type.

    Args:
        shell_type: "auto" (use the OS default shell), "bash", or
            "powershell" (pwsh on POSIX, powershell.exe on Windows).

    Returns:
        None to use asyncio's default shell (create_subprocess_shell), or a
        list of argv tokens to exec directly (the command is appended as the
        final argument).

    Raises:
        FileNotFoundError: If an explicitly requested shell isn't installed.
    """
    if shell_type == "auto":
        return None

    if shell_type == "bash":
        bash_path = shutil.which("bash") or "/bin/bash"
        return [bash_path, "-c"]

    if shell_type == "powershell":
        exe = shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")
        if not exe:
            raise FileNotFoundError(
                "PowerShell not found. Install PowerShell Core (pwsh) — "
                "see https://learn.microsoft.com/powershell/scripting/install/installing-powershell"
            )
        return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]

    raise ValueError(f"Unknown shell_type: '{shell_type}'. Use 'auto', 'bash', or 'powershell'.")


def _preexec_ignore_sigpipe():
    """POSIX-only preexec_fn; must never be passed on Windows."""
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


async def _spawn(command: str, cwd: Optional[str], shell_type: str):
    """Create the subprocess for `command`, honoring cwd and shell_type."""
    shell_argv = _resolve_shell(shell_type)
    kwargs = dict(
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    if platform.system() != "Windows":
        kwargs["preexec_fn"] = _preexec_ignore_sigpipe

    if shell_argv is None:
        return await asyncio.create_subprocess_shell(command, **kwargs)
    return await asyncio.create_subprocess_exec(*shell_argv, command, **kwargs)


async def _run_command_blocking(
    command: str,
    timeout: int,
    cwd: Optional[str] = None,
    shell_type: str = "auto",
) -> Dict[str, object]:
    """
    Run a command and capture output after completion.

    Args:
        command: The command to run.
        timeout: Timeout in seconds.
        cwd: Working directory for the subprocess.
        shell_type: "auto", "bash", or "powershell" — see _resolve_shell.

    Returns:
        Dict with stdout, stderr, returncode, timed_out, _duration.
    """
    import time
    start = time.monotonic()

    try:
        proc = await asyncio.wait_for(
            _spawn(command, cwd, shell_type),
            timeout=timeout,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        return {
            "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
            "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
            "returncode": proc.returncode or 0,
            "timed_out": False,
            "_duration": elapsed,
        }
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "returncode": -1,
            "timed_out": True,
            "_duration": elapsed,
        }


async def _run_command_streaming(
    command: str,
    timeout: int,
    cwd: Optional[str] = None,
    shell_type: str = "auto",
) -> Dict[str, object]:
    """
    Run a command and stream output in near real-time.

    Args:
        command: The command to run.
        timeout: Timeout in seconds.
        cwd: Working directory for the subprocess.
        shell_type: "auto", "bash", or "powershell" — see _resolve_shell.

    Returns:
        Dict with combined stdout, stderr, returncode, timed_out, _duration.
    """
    import time
    start = time.monotonic()
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []

    try:
        proc = await asyncio.wait_for(
            _spawn(command, cwd, shell_type),
            timeout=timeout,
        )

        async def _read_stream(
            stream: asyncio.StreamReader,
            chunks: List[str],
        ) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                chunks.append(line.decode("utf-8", errors="replace"))

        if proc.stdout:
            await _read_stream(proc.stdout, stdout_chunks)
        if proc.stderr:
            await _read_stream(proc.stderr, stderr_chunks)

        await proc.wait()
        elapsed = time.monotonic() - start
        return {
            "stdout": "".join(stdout_chunks),
            "stderr": "".join(stderr_chunks),
            "returncode": proc.returncode or 0,
            "timed_out": False,
            "_duration": elapsed,
        }
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        return {
            "stdout": "".join(stdout_chunks),
            "stderr": "Command timed out after {timeout} seconds",
            "returncode": -1,
            "timed_out": True,
            "_duration": elapsed,
        }


async def execute_powershell(
    command: str,
    timeout: int = 30,
    cwd: Optional[str] = None,
    permission_manager: Optional[ShellPermissionManager] = None,
) -> Dict[str, object]:
    """
    Execute a command via PowerShell (pwsh on POSIX, powershell.exe on
    Windows) regardless of the host OS's default shell.

    Args:
        command: PowerShell command/script to execute.
        timeout: Maximum execution time in seconds.
        cwd: Working directory to run in.
        permission_manager: Permission manager for security checks.

    Returns:
        Dict with keys: command, returncode, stdout, stderr, timed_out.
    """
    return await execute_command(
        command,
        timeout=timeout,
        cwd=cwd,
        shell_type="powershell",
        permission_manager=permission_manager,
    )


def register_shell_tools(registry: ToolRegistry) -> None:
    """
    Register all shell execution tools with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
    """
    registry.register(
        ToolDefinition(
            name="shell_exec",
            description=(
                "Execute a shell command with timeout and security checks. "
                "Uses the OS default shell unless shell_type overrides it."
            ),
            parameters=[
                ToolParameter(name="command", type="string", description="Shell command to execute."),
                ToolParameter(name="timeout", type="integer", description="Max execution time in seconds.", required=False, default=30),
                ToolParameter(name="stream", type="boolean", description="Stream output as it arrives.", required=False, default=False),
                ToolParameter(name="cwd", type="string", description="Working directory to run in.", required=False, default=None),
                ToolParameter(
                    name="shell_type", type="string",
                    description="'auto' (OS default), 'bash', or 'powershell'.",
                    required=False, default="auto",
                ),
            ],
            handler=execute_command,
            handler_sync=False,
            category="shell",
        )
    )
    registry.register(
        ToolDefinition(
            name="powershell_exec",
            description="Execute a command via PowerShell (pwsh/powershell.exe), independent of the host OS's default shell.",
            parameters=[
                ToolParameter(name="command", type="string", description="PowerShell command or script to execute."),
                ToolParameter(name="timeout", type="integer", description="Max execution time in seconds.", required=False, default=30),
                ToolParameter(name="cwd", type="string", description="Working directory to run in.", required=False, default=None),
            ],
            handler=execute_powershell,
            handler_sync=False,
            category="shell",
        )
    )
