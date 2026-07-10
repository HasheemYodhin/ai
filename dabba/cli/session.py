"""
Interactive session loop for the dabba CLI agent.

Provides a read-eval-print loop (REPL) with multi-turn conversation,
command handling, session persistence, and auto-save.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dabba.cli.agent_proxy import AgentProxy
from dabba.cli.config import CliConfig
from dabba.cli.file_watcher import FileWatcher
from dabba.cli.output_handler import OutputHandler
from dabba.cli.permissions import PermissionManager


def _get_logger():
    """Lazy logger to avoid importing torch through dabba.utils."""
    from dabba.utils.logging import get_logger
    return get_logger("dabba.cli.session")


def _is_likely_command(text: str) -> bool:
    """Heuristic: is this text likely a shell command, not a question/conversation?"""
    if not text or len(text) < 2:
        return False
    stripped = text.strip()
    q_starters = {"what", "why", "how", "when", "where", "who", "whom", "whose", "which",
                  "is", "are", "was", "were", "do", "does", "did", "can", "could",
                  "will", "would", "shall", "should", "may", "might", "must",
                  "has", "have", "had", "explain", "describe", "tell", "show",
                  "define", "list", "find", "search", "summarize"}
    first_word = stripped.split()[0].lower().rstrip("?,.;:!")
    if first_word in q_starters:
        return False
    common_commands = {
        "ls", "df", "du", "ps", "top", "htop", "who", "whoami", "pwd", "id",
        "uname", "date", "cal", "clear", "env", "printenv", "which", "whereis",
        "type", "time", "sleep", "yes", "seq", "shuf", "sort", "uniq", "wc",
        "head", "tail", "cat", "tac", "rev", "cut", "tr", "fmt", "pr", "fold",
        "nl", "od", "base64", "cksum", "sum", "md5sum", "sha1sum", "sha256sum",
        "git", "curl", "wget", "ssh", "scp", "rsync", "tar", "gzip", "gunzip",
        "zip", "unzip", "make", "cmake", "ninja", "meson", "npm", "yarn",
        "pnpm", "pip", "pip3", "cargo", "go", "rustc", "gcc", "g++", "clang",
        "clang++", "python", "python3", "node", "deno", "bun", "ruby", "perl",
        "php", "swift", "kotlin", "docker", "podman", "kubectl", "helm",
        "terraform", "ansible", "vagrant", "chmod", "chown", "cp", "mv", "rm",
        "mkdir", "rmdir", "touch", "ln", "mount", "umount", "dd", "find",
        "locate", "grep", "egrep", "fgrep", "awk", "sed", "xargs", "tee",
        "echo", "printf", "read", "test", "expr", "let", "set", "export",
        "source", ".", "exec", "eval", "trap", "kill", "pkill", "killall",
        "nohup", "disown", "fg", "bg", "jobs", "screen", "tmux", "sudo",
        "doas", "su", "passwd", "useradd", "usermod", "groupadd", "systemctl",
        "journalctl", "service", "iptables", "ufw", "ping", "traceroute",
        "nslookup", "dig", "host", "netstat", "ss", "ip", "ifconfig",
        "nmcli", "nmtui", "iwctl", "bluetoothctl", "alsamixer", "pactl",
        "xrandr", "xset", "xinput", "xdg-open", "open",
    }
    tokens = stripped.split()
    first = tokens[0]
    first_lower = first.lower()
    if first_lower in common_commands:
        return True
    if first_lower == "man" and len(tokens) >= 2:
        return True
    if len(tokens) > 1 and any(t.startswith("-") for t in tokens[1:]):
        return True
    if any(op in stripped for op in ["|", ">", "<", "&", ";", "&&", "||", "$("]):
        return True
    if first.startswith(("./", "/", "~/")):
        return True
    if shutil.which(first_lower):
        return True
    return False


_HELP_TEXT = """
## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show this help |
| `/clear` | Clear conversation history |
| `/exit` | Exit (Ctrl+D also works) |
| `/save [path]` | Save conversation to file |
| `/load <path>` | Load conversation from file |
| `/reset` | Reset agent state |
| `/config` | Show configuration |
| `/config set key=value` | Update a config value |
| `/permissions` | Show permission settings |
| `/mode allow\|deny\|ask` | Set permission mode |
| `/tools` | List available tools |
| `/metrics` | Show session metrics |
| `/history` | Show conversation history |
| `/keys [set/del]` | Manage API keys |
| `/model [name]` | Set or show active model |
| `/effort [level]` | Set reasoning effort |
| `/git <cmd>` | Git operations |
| `/mcp` | MCP server status |
| `/view <path>` | View a file |
| `/run <cmd>` | Run a shell command |

Any other command (like `/search`, `/explain`, `/fix`, `/test`,
`/review`, `/plan`, `/read`, `/find`, `/remember`) is sent to
the agent automatically.

**Tip:** Press `Ctrl+C` to cancel, `↑`/`↓` for input history.
"""


class InteractiveSession:
    """
    Interactive REPL session for the dabba CLI agent.

    Provides a multi-turn conversational interface with command
    handling, session persistence, and auto-save on exit.

    Args:
        agent: AgentProxy instance for LLM interaction.
        output: OutputHandler for rendering.
        config: CLI configuration.
        permissions: PermissionManager instance.
        session_id: Optional session ID (auto-generated if not provided).
        resume_path: Optional path to resume a previous session.
    """

    def __init__(
        self,
        agent: Optional[AgentProxy] = None,
        output: Optional[OutputHandler] = None,
        config: Optional[CliConfig] = None,
        permissions: Optional[PermissionManager] = None,
        session_id: Optional[str] = None,
        resume_path: Optional[str] = None,
    ):
        self.config = config or CliConfig.load()
        self.output = output or OutputHandler(config=self.config)
        self.permissions = permissions or PermissionManager(
            mode=self.config.permission_mode,
        )
        self.agent = agent or AgentProxy(
            cli_config=self.config,
            output=self.output,
            permissions=self.permissions,
        )

        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.session_start = time.time()
        self.history: List[Dict[str, Any]] = []
        self._running = False
        self._auto_save_timer: Optional[float] = None

        self.file_watcher: Optional[FileWatcher] = None
        if self.config.watch_files:
            self.file_watcher = FileWatcher(
                workspace_root=".",
                extensions=set(self.config.watch_extensions),
                auto_read_on_change=True,
            )

        if resume_path:
            self._load_history(resume_path)

        atexit.register(self._auto_save_on_exit)

    def start(self) -> None:
        """Start the interactive session — uses premium TUI when available."""
        # Try to launch the full-screen TUI first
        try:
            from dabba.cli.tui import run_tui
            from dabba import __version__
            run_tui(agent=self.agent, config=self.config, version=__version__)
            return
        except Exception as _tui_err:
            import sys
            print(f"TUI error: {_tui_err}", file=sys.stderr)

        # Classic REPL fallback
        self._running = True
        if self.file_watcher:
            self.file_watcher.start()
        self._setup_signal_handlers()
        self._print_welcome()

        while self._running:
            try:
                user_input = self.output.prompt_input()
            except KeyboardInterrupt:
                self.output.info("Interrupted. Type /exit to quit.")
                continue
            except EOFError:
                self._handle_exit()
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                self._handle_command(user_input)
            else:
                self._handle_message(user_input)

    def _print_welcome(self) -> None:
        """Print the welcome banner."""
        from dabba import __version__
        self.output.welcome(
            version=__version__,
            model=self.config.default_model,
            endpoint=self.config.api_endpoint,
        )

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(sig, frame):
            self.output.write("\n")
            self._handle_exit()

        signal.signal(signal.SIGINT, signal_handler)

    def _handle_command(self, command_line: str) -> None:
        """
        Handle a slash command.

        Args:
            command_line: The full command line (e.g., "/save path").
        """
        parts = command_line.strip().split()
        command = parts[0].lower()
        args = parts[1:]

        command_map = {
            "/help": self._cmd_help,
            "/?": self._cmd_help,
            "/clear": self._cmd_clear,
            "/exit": self._cmd_exit,
            "/quit": self._cmd_exit,
            "/save": self._cmd_save,
            "/load": self._cmd_load,
            "/reset": self._cmd_reset,
            "/config": self._cmd_config,
            "/permissions": self._cmd_permissions,
            "/mode": self._cmd_mode,
            "/tools": self._cmd_tools,
            "/metrics": self._cmd_metrics,
            "/history": self._cmd_history,
            # Extended slash commands — these are handled locally; everything
            # else falls through to the agent which can interpret it naturally.
            "/keys": self._cmd_keys,
            "/model": self._cmd_model,
            "/effort": self._cmd_effort,
            "/git": self._cmd_git,
            "/mcp": self._cmd_mcp,
            "/view": self._cmd_view,
            "/run": self._cmd_run,
            "/save": self._cmd_save,
        }

        handler = command_map.get(command)
        if handler:
            handler(args)
        else:
            # Unknown slash commands are routed to the agent as regular
            # messages instead of being rejected. Commands like /search,
            # /explain, /fix, /test, /review, /plan, /memory, /usage,
            # /compact, /read, /find, /remember, /memories, /forget all
            # work through the agent's natural language understanding.
            self._handle_message(command_line)

    def _cmd_help(self, args: List[str]) -> None:
        """Show help text."""
        self.output.markdown(_HELP_TEXT)

    def _cmd_clear(self, args: List[str]) -> None:
        """Clear the conversation history."""
        self.agent.reset()
        self.history.clear()
        self.output.info("Conversation history cleared.")

    def _cmd_exit(self, args: Optional[List[str]] = None) -> None:
        """Exit the session."""
        self._handle_exit()

    def _cmd_save(self, args: List[str]) -> None:
        """Save conversation history to a file."""
        save_path = args[0] if args else self._default_save_path()
        self._save_history(save_path)

    def _cmd_load(self, args: List[str]) -> None:
        """Load conversation history from a file."""
        if not args:
            self.output.error("Usage: /load <path>")
            return
        self._load_history(args[0])

    def _cmd_reset(self, args: List[str]) -> None:
        """Reset the agent state."""
        self.agent.reset()
        self.output.info("Agent state reset.")

    def _cmd_config(self, args: List[str]) -> None:
        """Show or set configuration."""
        if not args:
            self._show_config()
            return

        if args[0] == "set":
            if len(args) < 2 or "=" not in args[1]:
                self.output.error("Usage: /config set key=value")
                return
            key, value = args[1].split("=", 1)
            try:
                self.config.set(key.strip(), value.strip())
                self.agent.reload_config()
                self.output.info(f"Configuration updated: {key} = {value}")
            except (KeyError, ValueError) as exc:
                self.output.error(str(exc))
        else:
            self._show_config()

    def _cmd_permissions(self, args: List[str]) -> None:
        """Show permission settings."""
        summary = self.permissions.get_summary()
        self.output.table(
            ["Setting", "Value"],
            [
                ["Mode", summary["mode"]],
                ["Session Allowed", ", ".join(summary["session_allowed"]) or "none"],
                ["Session Denied", ", ".join(summary["session_denied"]) or "none"],
                ["Persistent Grants", str(len(summary["persistent_grants"]))],
            ],
        )

    def _cmd_mode(self, args: List[str]) -> None:
        """Set the permission mode."""
        if not args:
            self.output.info(f"Current mode: {self.permissions.mode}")
            return
        try:
            self.permissions.set_mode(args[0])
            self.output.info(f"Permission mode set to '{args[0]}'.")
        except ValueError as exc:
            self.output.error(str(exc))

    def _cmd_tools(self, args: List[str]) -> None:
        """List available tools."""
        tools = self.agent._get_registry().list_tools()
        if not tools:
            self.output.info("No tools registered.")
            return

        rows = []
        for t in tools:
            category = getattr(t, "category", "general")
            rows.append([t.name, category, t.description[:60]])
        self.output.table(["Name", "Category", "Description"], rows)

    def _cmd_metrics(self, args: List[str]) -> None:
        """Show session metrics."""
        metrics = self.agent._get_metrics()
        if not metrics:
            self.output.info("No metrics available yet.")
            return

        duration = time.time() - self.session_start
        rows = [
            ["Session duration", f"{duration:.1f}s"],
            ["Steps used", str(metrics.get("step_count", 0))],
            ["Tool calls", str(metrics.get("tool_call_count", 0))],
            ["Context tokens", str(metrics.get("context_total_tokens", 0))],
            ["Context entries", str(metrics.get("context_entry_count", 0))],
        ]
        self.output.table(["Metric", "Value"], rows)

    def _cmd_history(self, args: List[str]) -> None:
        """Show conversation history summary."""
        if not self.history:
            self.output.info("No conversation history.")
            return

        rows = []
        for i, entry in enumerate(self.history[-20:], 1):
            role = entry.get("role", "?")
            content = entry.get("content", "")
            preview = content[:50].replace("\n", " ")
            rows.append([str(i), role, preview])
        self.output.table(["#", "Role", "Preview"], rows)
        if len(self.history) > 20:
            self.output.info(f"... and {len(self.history) - 20} more entries.")

    def _cmd_keys(self, args: List[str]) -> None:
        """Manage API keys — show, set, or delete."""
        if not args or args[0] in ("show", "list"):
            keys = getattr(self.config, "api_keys", {}) or {}
            providers = ["anthropic", "openai", "google", "nvidia", "huggingface"]
            rows = []
            for p in providers:
                status = "✅ set" if keys.get(p) else "⬜ not set"
                rows.append([p, status])
            self.output.table(["Provider", "Key Status"], rows)
            self.output.info("Usage: /keys set <provider> <key>  or  /keys delete <provider>")
            return

        if args[0] == "set" and len(args) >= 3:
            provider = args[1].lower()
            key_value = args[2]
            valid = {"anthropic", "openai", "google", "nvidia", "huggingface"}
            if provider not in valid:
                self.output.error(f"Unknown provider: {provider}. Valid: {', '.join(sorted(valid))}")
                return
            api_keys = getattr(self.config, "api_keys", {})
            if api_keys is None:
                api_keys = {}
            api_keys[provider] = key_value
            self.config.api_keys = api_keys
            self.config.save()
            self.output.info(f"API key saved for {provider}")
            return

        if args[0] == "delete" and len(args) >= 2:
            provider = args[1].lower()
            api_keys = getattr(self.config, "api_keys", {}) or {}
            if provider in api_keys:
                del api_keys[provider]
                self.config.api_keys = api_keys
                self.config.save()
                self.output.info(f"API key removed for {provider}")
            else:
                self.output.error(f"No key set for {provider}")
            return

        self.output.info("Usage: /keys set <provider> <key>  or  /keys delete <provider>")

    def _cmd_model(self, args: List[str]) -> None:
        """Set or show the active model."""
        if args:
            new_model = args[0]
            self.config.default_model = new_model
            self.config.save()
            self.agent.reload_config()
            self.output.info(f"Model set to: {new_model}")
        else:
            self.output.info(f"Current model: {self.config.default_model}")
            self.output.info("Usage: /model <model_id>")

    def _cmd_effort(self, args: List[str]) -> None:
        """Set or show reasoning effort level."""
        tiers = {"low", "medium", "high", "xhigh", "max"}
        if args and args[0].lower() in tiers:
            self.config.effort = args[0].lower()
            self.config.save()
            self.agent.reload_config()
            self.output.info(f"Reasoning effort set to: {args[0].lower()}")
        else:
            current = getattr(self.config, "effort", "medium")
            self.output.info(f"Current effort: {current}")
            self.output.info("Usage: /effort <low|medium|high|xhigh|max>")

    def _cmd_git(self, args: List[str]) -> None:
        """Run a git command in the workspace."""
        command_line = " ".join(args) if args else "status --short"
        # Treat as a regular message — the agent will execute the git command
        self._handle_message(f"/git {command_line}")

    def _cmd_mcp(self, args: List[str]) -> None:
        """Show MCP server status."""
        try:
            self.agent._get_registry()
            status = self.agent.mcp_manager.status()
            if not status.get("servers"):
                self.output.info("No MCP servers connected.")
                self.output.info("Configure servers in ~/.config/dabba/mcp_servers.json")
                return
            rows = []
            for name in status["servers"]:
                tools = status["tools_by_server"].get(name, [])
                rows.append([name, "connected", ", ".join(tools) or "none"])
            self.output.table(["Server", "Status", "Tools"], rows)
        except Exception as exc:
            self.output.error(f"MCP status failed: {exc}")

    def _cmd_view(self, args: List[str]) -> None:
        """View a file."""
        if not args:
            self.output.info("Usage: /view <path>")
            return
        from pathlib import Path
        path = Path(args[0])
        if not path.exists():
            self.output.error(f"File not found: {path}")
            return
        try:
            content = path.read_text(errors="replace")
            lines = content.splitlines()
            preview = "\n".join(lines[:60])
            if len(lines) > 60:
                preview += f"\n... ({len(lines)} lines total)"
            self.output.code_block(preview, language=path.suffix.lstrip("."))
            self.output.info(f"Showing {path} ({len(lines)} lines)")
        except Exception as exc:
            self.output.error(f"Error reading file: {exc}")

    def _cmd_run(self, args: List[str]) -> None:
        """Run a shell command directly."""
        if not args:
            self.output.info("Usage: /run <command>")
            return
        self._exec_shell(" ".join(args))

    def _exec_shell(self, command: str) -> None:
        """Execute a shell command and display output."""
        self.output.info(f"$ {command}")
        self.history.append({"role": "user", "content": f"$ {command}", "timestamp": time.time()})
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += result.stderr
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            if output.strip():
                self.output.code_block(output.strip(), language="bash")
            else:
                self.output.info(f"Command completed (exit code {result.returncode})")
            self.history.append({
                "role": "assistant",
                "content": output.strip() or f"(exit code {result.returncode})",
                "timestamp": time.time(),
            })
        except subprocess.TimeoutExpired:
            self.output.error("Command timed out (30s limit)")
        except Exception as exc:
            self.output.error(f"Command failed: {exc}")

    def _show_config(self) -> None:
        """Display current configuration."""
        rows = [
            ["api_endpoint", self.config.api_endpoint],
            ["default_model", self.config.default_model],
            ["temperature", str(self.config.default_temperature)],
            ["max_tokens", str(self.config.default_max_tokens)],
            ["stream_output", str(self.config.stream_output)],
            ["permission_mode", self.config.permission_mode],
            ["theme", self.config.theme],
        ]
        self.output.table(["Key", "Value"], rows)

    def _handle_message(self, message: str) -> None:
        """
        Handle a user message through the agent.

        Auto-executes shell commands directly (like `df`, `ls -la`, `git status`)
        instead of sending them to the LLM. Questions and conversation are sent
        to the agent as normal.

        Args:
            message: The user's input message.
        """
        if _is_likely_command(message):
            self._exec_shell(message)
            return

        self.history.append({"role": "user", "content": message, "timestamp": time.time()})
        self.output.user_message(message)

        try:
            if self.config.stream_output:
                response = self.agent.stream_sync(message)
            else:
                with self.output.progress_spinner("Thinking..."):
                    response = self.agent.run(message)
                self.output.assistant_message(response)

            self.history.append({"role": "assistant", "content": response, "timestamp": time.time()})
            self._check_auto_save()

        except Exception as exc:
            self.output.error(f"An error occurred: {exc}")
            _get_logger().error("Session message error: %s", exc)

    def _check_auto_save(self) -> None:
        """Auto-save history at configured intervals."""
        if self.config.auto_save_interval <= 0:
            return

        now = time.time()
        if self._auto_save_timer is None:
            self._auto_save_timer = now
            return

        if now - self._auto_save_timer >= self.config.auto_save_interval:
            save_path = self._default_save_path()
            self._save_history(save_path, quiet=True)
            self._auto_save_timer = now

    def _handle_exit(self) -> None:
        """Handle session exit with auto-save."""
        self._running = False
        self._auto_save_on_exit()

        if self.file_watcher:
            self.file_watcher.stop()

        self.output.info("Goodbye!")
        self.agent.close()

    def _auto_save_on_exit(self) -> None:
        """Auto-save history when the session ends."""
        if not self.history:
            return
        save_path = self._default_save_path()
        self._save_history(save_path, quiet=True)
        self._cleanup_old_history()

    def _default_save_path(self) -> str:
        """
        Get the default save path for this session.

        Returns:
            Path string to the history JSONL file.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        config_path = Path(self.config.history_file)
        parent = config_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        return str(parent / f"session_{self.session_id}_{timestamp}.jsonl")

    def _save_history(self, path: str, quiet: bool = False) -> None:
        """
        Save conversation history to a JSONL file.

        Args:
            path: File path to save to.
            quiet: If True, suppress output messages.
        """
        try:
            path_obj = Path(path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)

            with open(path_obj, "w") as f:
                for entry in self.history:
                    f.write(json.dumps(entry) + "\n")

            if not quiet:
                self.output.info(f"History saved to {path} ({len(self.history)} entries).")
        except OSError as exc:
            self.output.error(f"Failed to save history: {exc}")

    def _load_history(self, path: str) -> None:
        """
        Load conversation history from a JSONL file.

        Args:
            path: Path to the JSONL file.
        """
        path_obj = Path(path)
        if not path_obj.exists():
            self.output.error(f"History file not found: {path}")
            return

        try:
            loaded = []
            with open(path_obj, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        loaded.append(json.loads(line))

            if not loaded:
                self.output.warning("History file is empty.")
                return

            self.history = loaded
            roles = [e.get("role", "?") for e in loaded]
            user_count = roles.count("user")
            assistant_count = roles.count("assistant")
            self.output.info(
                f"Loaded {len(loaded)} entries from {path} "
                f"({user_count} user, {assistant_count} assistant)."
            )
        except (json.JSONDecodeError, OSError) as exc:
            self.output.error(f"Failed to load history: {exc}")

    def _cleanup_old_history(self) -> None:
        """Remove old history files beyond the configured limit."""
        try:
            config_path = Path(self.config.history_file)
            parent = config_path.parent
            if not parent.exists():
                return

            history_files = sorted(
                [f for f in parent.glob("session_*.jsonl")],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )

            for old_file in history_files[self.config.max_history_files:]:
                old_file.unlink()
                _get_logger().info("Removed old history file: %s", old_file)
        except OSError as exc:
            _get_logger().debug("History cleanup failed: %s", exc)
