"""
CLI module for the dabba terminal agent.

Provides an interactive terminal interface (Claude Code clone) with
rich output, session management, file watching, permission control,
and agent orchestration for the dabba framework.

Components:
    - main: CLI entry point with argparse subcommands (chat, run, session, config)
    - session: Interactive REPL session with multi-turn conversation
    - agent_proxy: Wraps AgentLoop for CLI consumption
    - output_handler: Rich terminal output with markdown rendering
    - file_watcher: File change monitoring (watchdog with polling fallback)
    - permissions: Tool execution permission management
    - config: CLI-specific configuration management
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dabba.cli.main import main
    from dabba.cli.session import InteractiveSession
    from dabba.cli.agent_proxy import AgentProxy
    from dabba.cli.output_handler import OutputHandler
    from dabba.cli.file_watcher import FileWatcher
    from dabba.cli.permissions import PermissionManager
    from dabba.cli.config import CliConfig


def __getattr__(name: str):
    import importlib
    module_map = {
        "main": "dabba.cli.main",
        "InteractiveSession": "dabba.cli.session",
        "AgentProxy": "dabba.cli.agent_proxy",
        "OutputHandler": "dabba.cli.output_handler",
        "FileWatcher": "dabba.cli.file_watcher",
        "PermissionManager": "dabba.cli.permissions",
        "CliConfig": "dabba.cli.config",
    }
    if name in module_map:
        module = importlib.import_module(module_map[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "main",
    "InteractiveSession",
    "AgentProxy",
    "OutputHandler",
    "FileWatcher",
    "PermissionManager",
    "CliConfig",
]
