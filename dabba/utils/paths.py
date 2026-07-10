"""
Cross-platform app-data directory for dabba's persisted config/state.

Every call site that used to hardcode `Path.home() / ".config" / "dabba"`
now goes through get_dabba_config_dir() instead. On Linux with no
XDG_CONFIG_HOME set, this resolves to the exact same path as before — no
behavior change for existing installs. On Windows/macOS it now resolves
to a location that actually makes sense on those platforms, instead of a
POSIX-only path that silently never existed there.

The VS Code extension (vscode-extension/src/chatViewProvider.ts,
_mcpConfigPath) mirrors this exact same OS-detection logic in TypeScript —
keep the two in sync, since both read/write dabba/agent/mcp_client.py's
mcp_servers.json.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_dabba_config_dir() -> Path:
    """
    Return the OS-appropriate directory for dabba's config/state files.

    - Windows: %APPDATA%\\dabba (falls back to ~/AppData/Roaming/dabba)
    - macOS: ~/Library/Application Support/dabba
    - Linux/other: $XDG_CONFIG_HOME/dabba, falling back to ~/.config/dabba
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"

    return root / "dabba"
