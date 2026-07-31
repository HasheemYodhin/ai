"""
Permission system for the dabba CLI agent.

Manages allow/deny/ask modes for tool execution, command approval
prompts, session-wide grants, and persistent permission settings.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from dabba.utils.paths import get_dabba_config_dir

PERMISSIONS_FILE = get_dabba_config_dir() / "permissions.json"


DANGEROUS_COMMANDS: Set[str] = {
    "sudo",
    "su",
    "chown",
    "chmod",
    "passwd",
    "kill",
    "pkill",
    "shutdown",
    "reboot",
    "init",
    "systemctl",
    "journalctl",
    "dd",
    "mkfs",
    "fdisk",
    "mount",
    "umount",
    "rm -rf",
    "rm -r /",
    "> /dev",
    "> /etc",
    "| sudo",
    "| su",
}

DANGEROUS_TOOLS: Set[str] = {
    "shell_exec",
    "file_write",
    "file_edit",
    "execute_command",
    "powershell_exec",
    "process_start",
    "process_stop",
    "ssh_exec",
    "scp_copy",
    "docker_exec",
    "docker_run",
    "markdown_to_pdf",
    "markdown_to_docx",
}

# Shell tools whose "command" argument is actually run — the only ones a git
# safety check can meaningfully inspect.
_SHELL_TOOLS = {"shell_exec", "powershell_exec", "execute_command"}
PROTECTED_BRANCHES: Set[str] = {"main", "master", "develop", "dev"}
_FORCE_PUSH_RE = re.compile(r"\bgit\s+push\b.*(--force(?!-with-lease)|(?<!-)-f\b)")
_COMMIT_LIKE_RE = re.compile(r"\bgit\s+(commit|push|merge|rebase)\b")


class PermissionManager:
    """
    Manages permissions for tool and command execution.

    Supports three modes:
        - "allow": Automatically approve all actions.
        - "deny": Automatically reject all actions.
        - "ask": Prompt the user for each action.

    Permissions can be granted per-session or persisted to disk.

    Args:
        mode: Initial permission mode ("allow", "deny", or "ask").
        dangerous_tools: Set of tool names considered dangerous.
        dangerous_commands: Set of command substrings considered dangerous.
        persistent: Whether to save permission grants to disk.
    """

    def __init__(
        self,
        mode: str = "ask",
        dangerous_tools: Optional[Set[str]] = None,
        dangerous_commands: Optional[Set[str]] = None,
        persistent: bool = True,
        confirm_fn: Optional[Callable[[str, Optional[Dict[str, Any]]], bool]] = None,
    ):
        self.mode = mode
        self.dangerous_tools = dangerous_tools or DANGEROUS_TOOLS
        self.dangerous_commands = dangerous_commands or DANGEROUS_COMMANDS
        self.persistent = persistent
        # Called as confirm_fn(tool_name, arguments) -> bool to render a real
        # y/n prompt. Without one, "ask" mode has nothing to ask through and
        # falls back to auto-deny for dangerous tools (fail closed, not open).
        self.confirm_fn = confirm_fn

        self._session_allowed: Set[str] = set()
        self._session_denied: Set[str] = set()
        self._persistent_allowed: Dict[str, List[str]] = {}
        self._last_denial_reason: Optional[str] = None
        self._load_persistent()

    def get_last_denial_reason(self) -> Optional[str]:
        """Human-readable reason for the most recent git-safety denial/prompt, if any."""
        return self._last_denial_reason

    @staticmethod
    def _current_git_branch(cwd: Optional[str]) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=cwd or os.getcwd(),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except Exception:
            pass
        return None

    def classify_git_command(
        self, command: str, cwd: Optional[str] = None
    ) -> Optional[Tuple[bool, str]]:
        """
        Inspect a shell command for git safety issues, mirroring the
        protected-branch / force-push rules a human operator should follow.

        Returns (hard_block, reason) when risky, else None:
          hard_block=True  — check_tool always denies; no mode/grant overrides it.
          hard_block=False — requires an explicit confirmation prompt even in
                              "allow" mode or with an existing session/persistent grant.
        """
        lowered = command.lower()
        if "git" not in lowered:
            return None

        if _FORCE_PUSH_RE.search(lowered):
            branch = self._current_git_branch(cwd)
            if branch and branch in PROTECTED_BRANCHES:
                return (
                    True,
                    f"Force-push to protected branch '{branch}' is never allowed.",
                )
            return (
                False,
                "Force-push requires explicit confirmation — it can overwrite remote history.",
            )

        if re.search(r"\bgit\s+commit\b", lowered):
            branch = self._current_git_branch(cwd)
            if branch and branch in PROTECTED_BRANCHES:
                return True, (
                    f"Direct commits to protected branch '{branch}' are not allowed. "
                    "Create a feature branch and open a PR instead."
                )
            return None

        if re.search(r"\bgit\s+push\b", lowered):
            branch = self._current_git_branch(cwd)
            if branch and branch in PROTECTED_BRANCHES:
                return (
                    False,
                    f"Pushing to protected branch '{branch}' requires confirmation.",
                )
            return None

        return None

    def _git_risk(
        self, tool_name: str, arguments: Optional[Dict[str, Any]]
    ) -> Optional[Tuple[bool, str]]:
        if tool_name not in _SHELL_TOOLS or not arguments:
            return None
        command = str(arguments.get("command") or "")
        if not command:
            return None
        return self.classify_git_command(command, arguments.get("cwd"))

    def _load_persistent(self) -> None:
        """Load persistent permissions from disk."""
        if not self.persistent:
            return
        if PERMISSIONS_FILE.exists():
            try:
                with open(PERMISSIONS_FILE, "r") as f:
                    self._persistent_allowed = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._persistent_allowed = {}

    def _save_persistent(self) -> None:
        """Save persistent permissions to disk."""
        if not self.persistent:
            return
        PERMISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PERMISSIONS_FILE, "w") as f:
            json.dump(self._persistent_allowed, f, indent=2)

    def set_mode(self, mode: str) -> None:
        """
        Set the permission mode.

        Args:
            mode: One of "allow", "deny", or "ask".

        Raises:
            ValueError: If the mode is not recognized.
        """
        if mode not in ("allow", "deny", "ask"):
            raise ValueError(
                f"Unknown permission mode: '{mode}'. Use 'allow', 'deny', or 'ask'."
            )
        self.mode = mode

    def is_dangerous_command(self, command: str) -> bool:
        """
        Check if a command string contains dangerous patterns.

        Args:
            command: The command string to check.

        Returns:
            True if the command matches dangerous patterns.
        """
        cmd_lower = command.lower().strip()
        for pattern in self.dangerous_commands:
            if pattern.lower() in cmd_lower:
                return True
        return False

    def is_dangerous_tool(self, tool_name: str) -> bool:
        """
        Check if a tool is considered dangerous.

        Every "mcp__<server>__<tool>" tool is treated as dangerous
        regardless of the static dangerous_tools list — it's arbitrary
        third-party code the user pointed dabba at via mcp_servers.json,
        not a built-in tool that's been reviewed, so it defaults to
        requiring approval the same as shell_exec/file_write.

        Args:
            tool_name: The tool name.

        Returns:
            True if the tool is in the dangerous set, or is an MCP tool.
        """
        return tool_name in self.dangerous_tools or tool_name.startswith("mcp__")

    def check_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Check whether a tool call should be allowed.

        Args:
            tool_name: Name of the tool being called.
            arguments: Tool arguments (used for command checking).

        Returns:
            True if the tool call is permitted, False otherwise.
        """
        self._last_denial_reason = None
        git_risk = self._git_risk(tool_name, arguments)
        if git_risk is not None:
            hard_block, reason = git_risk
            self._last_denial_reason = reason
            if hard_block:
                return False
            # Bypasses mode/session/persistent grants below on purpose — a
            # standing "allow" grant for shell_exec must not silently cover
            # a force-push or a protected-branch push too.
            return self._prompt_user(tool_name, arguments)

        if tool_name in self._session_denied:
            return False
        if tool_name in self._session_allowed:
            return True

        if tool_name in self._persistent_allowed:
            allowed_args = self._persistent_allowed.get(tool_name, [])
            if not allowed_args or not arguments:
                return True
            tool_key = self._tool_key(tool_name, arguments)
            if tool_key in allowed_args:
                return True

        if self.mode == "allow":
            return True
        if self.mode == "deny":
            return False

        return self._prompt_user(tool_name, arguments)

    def _tool_key(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Generate a stable key for a tool call with arguments."""
        sorted_args = json.dumps(arguments, sort_keys=True)
        return f"{tool_name}:{sorted_args}"

    def _prompt_user(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Prompt the user to approve or deny a tool call.

        Delegates to confirm_fn (wired to OutputHandler.confirm by the CLI)
        for the actual blocking y/n prompt. If no confirm_fn is set, fail
        closed for dangerous tools rather than silently allowing everything.

        Returns:
            True if permitted, False otherwise.
        """
        if self.confirm_fn is not None:
            return bool(self.confirm_fn(tool_name, arguments))
        return not self.is_dangerous_tool(tool_name)

    def grant_session(self, tool_name: str) -> None:
        """
        Grant permission for a tool for the current session.

        Args:
            tool_name: Tool to allow.
        """
        self._session_allowed.add(tool_name)
        if tool_name in self._session_denied:
            self._session_denied.discard(tool_name)

    def deny_session(self, tool_name: str) -> None:
        """
        Deny permission for a tool for the current session.

        Args:
            tool_name: Tool to deny.
        """
        self._session_denied.add(tool_name)
        if tool_name in self._session_allowed:
            self._session_allowed.discard(tool_name)

    def grant_persistent(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Grant persistent permission for a tool.

        Args:
            tool_name: Tool to allow persistently.
            arguments: Optional specific arguments to allow.
        """
        if tool_name not in self._persistent_allowed:
            self._persistent_allowed[tool_name] = []
        if arguments:
            key = self._tool_key(tool_name, arguments)
            if key not in self._persistent_allowed[tool_name]:
                self._persistent_allowed[tool_name].append(key)
        self._save_persistent()

    def revoke_persistent(self, tool_name: str) -> None:
        """
        Revoke persistent permission for a tool.

        Args:
            tool_name: Tool to revoke.
        """
        self._persistent_allowed.pop(tool_name, None)
        self._save_persistent()

    def clear_session(self) -> None:
        """Clear all session-level permissions."""
        self._session_allowed.clear()
        self._session_denied.clear()

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the current permission state.

        Returns:
            Dictionary with mode, session grants, and persistent grants.
        """
        return {
            "mode": self.mode,
            "session_allowed": sorted(self._session_allowed),
            "session_denied": sorted(self._session_denied),
            "persistent_grants": {
                k: len(v) for k, v in self._persistent_allowed.items()
            },
        }
