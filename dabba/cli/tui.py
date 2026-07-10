"""
Premium full-screen TUI for Dabba.
Supports multi-provider models, effort levels, slash autocomplete, and code ops.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Label, Static, Markdown as TUIMarkdown, ListView, ListItem, Button
from textual import on, work

if TYPE_CHECKING:
    from dabba.cli.agent_proxy import AgentProxy
    from dabba.cli.config import CliConfig


# ── Shell command detection ───────────────────────────────────────────────────

def _is_likely_command(text: str) -> bool:
    """Heuristic: is this text likely a shell command, not a question/conversation?"""
    if not text or len(text) < 2:
        return False
    stripped = text.strip()
    q_starters = {"what", "why", "how", "when", "where", "who", "whom", "whose",
                  "which", "is", "are", "was", "were", "do", "does", "did",
                  "can", "could", "will", "would", "shall", "should", "may",
                  "might", "must", "has", "have", "had", "explain", "describe",
                  "tell", "show", "define", "list", "find", "search", "summarize"}
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


# ── Slash commands ─────────────────────────────────────────────────────────────

SLASH_COMMANDS: List[tuple[str, str]] = [
    ("/help",       "Show all commands"),
    ("/clear",      "Clear conversation history"),
    ("/exit",       "Exit Dabba"),
    ("/save",       "Save session to file"),
    ("/history",    "Show conversation history"),
    ("/reset",      "Reset agent state"),
    ("/model",      "Switch model (Claude, GPT, Gemini, Nvidia, Ollama…)"),
    ("/effort",     "Set effort level: low medium high xhigh max"),
    ("/keys",       "Manage API keys: /keys set <provider> <key>"),
    ("/upload",     "Attach a file to the conversation: /upload <path>"),
    ("/tools",      "List available tools"),
    ("/mcp",        "Manage MCP servers — view status, add, remove"),
    ("/mode",       "Set permission mode: allow deny ask"),
    ("/permissions","Show permission settings"),
    ("/metrics",    "Session time and message count"),
    ("/git",        "Git ops: status diff log commit push"),
    ("/view",       "View a file: /view <path>"),
    ("/create",     "Create a file: /create <path>"),
    ("/run",        "Run a shell command: /run <cmd>"),
    ("/powershell", "Run a command via PowerShell: /powershell <cmd>"),
    ("/ps",         "Background processes: /ps [list|start <cmd>|output <id>|stop <id>]"),
    ("/ssh",        "Run a remote command: /ssh <host> <cmd>"),
    ("/docker",     "Docker ops: /docker ps|exec <container> <cmd>|run <image> <cmd>"),
]

EFFORT_OPTIONS = [
    ("low",    "Fast, concise — max 1k tokens"),
    ("medium", "Balanced — max 4k tokens"),
    ("high",   "Thorough — max 8k tokens, thinking on"),
    ("xhigh",  "Extended reasoning — max 16k tokens"),
    ("max",    "Maximum effort — max 32k tokens, full thinking"),
]

PROVIDER_ORDER = ["dabba", "anthropic", "openai", "google", "nvidia", "huggingface", "ollama"]
PROVIDER_LABELS = {
    "dabba":        "⬡  DABBA (own model)",
    "anthropic":    "◆  ANTHROPIC",
    "openai":       "◈  OPENAI",
    "google":       "◉  GOOGLE",
    "nvidia":       "▶  NVIDIA NIM",
    "huggingface":  "🤗 HUGGING FACE",
    "ollama":       "○  LOCAL (Ollama)",
}
TIER_COLOR = {
    "low": "dim", "medium": "cyan", "high": "green", "xhigh": "yellow", "max": "red"
}


# ── CSS ────────────────────────────────────────────────────────────────────────

_CSS = """
Screen { background: #0b0b12; layers: base suggestions; }

#app-header {
    dock: top; height: 3; background: #10101f;
    border-bottom: solid #1d1d35; padding: 0 3;
    layout: horizontal; content-align: left middle;
}
#header-logo  { color: #00e5ff; text-style: bold; width: auto; height: 3; padding: 1 0; content-align: left middle; }
#header-model { color: #40c4ff; width: auto; height: 3; padding: 1 1; content-align: left middle; }
#header-effort{ color: #888800; width: auto; height: 3; padding: 1 0; content-align: left middle; }
#header-meta  { color: #333355; width: 1fr; height: 3; content-align: right middle; }
#header-status{ color: #00e676; width: auto; height: 3; padding: 1 2; content-align: right middle; }

#chat-scroll {
    height: 1fr; background: #0b0b12;
    padding: 0 3 1 3;
    scrollbar-color: #1d1d35 #0b0b12; scrollbar-size: 1 1;
}
#chat-spacer { height: 1fr; background: #0b0b12; }

.msg-block  { margin: 0 0 1 0; layout: vertical; height: auto; }
.msg-label  { height: 1; }
.msg-label-you    { color: #40c4ff; text-style: bold; }
.msg-label-dabba  { color: #00e676; text-style: bold; }
.msg-label-system { color: #333355; text-style: italic; }

.msg-content-you {
    background: #0d1e2e; border: round #1a3a5a;
    color: #b3e5fc; padding: 1 2; height: auto;
}
.msg-content-dabba {
    background: #0a1a10; border: round #1a3a1a;
    color: #c8e6c9; padding: 1 2; height: auto;
}
.msg-content-system { color: #333355; padding: 0 1; height: auto; }
.msg-content-error  {
    background: #1a0a0a; border: round #440000;
    color: #ff5252; padding: 1 2; height: auto;
}
.msg-content-code {
    background: #0d1520; border: round #1a2a3a;
    color: #90caf9; padding: 1 2; height: auto;
}

.msg-content-dabba Markdown       { background: #0a1a10; color: #c8e6c9; padding: 0; margin: 0; }
.msg-content-dabba MarkdownFence  { background: #0d2010; border: round #1a4a1a; margin: 1 0; }
.msg-content-dabba MarkdownH1,
.msg-content-dabba MarkdownH2,
.msg-content-dabba MarkdownH3     { color: #00e676; text-style: bold; }

#thinking {
    background: #0a1a10; border: round #1a3a1a; color: #00e676;
    padding: 1 2; margin: 0 0 1 0; height: auto; display: none;
}
#thinking.visible { display: block; }

/* Slash suggestions */
#suggestions {
    layer: suggestions; dock: bottom; offset-y: -5; margin: 0 3;
    background: #14142a; border: round #2a2a55;
    height: auto; max-height: 20; display: none; padding: 0;
}
#suggestions.visible { display: block; }
.suggestion-item        { height: 1; padding: 0 2; layout: horizontal; }
.suggestion-item.--highlight { background: #1e1e3f; }
.suggestion-cmd  { color: #00e676; width: 16; text-style: bold; }
.suggestion-desc { color: #555577; width: 1fr; }

/* Input bar */
#input-container {
    dock: bottom; height: 5; background: #10101f;
    border-top: solid #1d1d35; padding: 1 3;
    layout: horizontal; content-align: left middle;
}
#input-prompt { color: #00e676; text-style: bold; width: auto; content-align: left middle; padding: 0 1 0 0; }
#user-input   {
    background: #10101f; border: none; border-bottom: solid #2a2a4a;
    color: #e0e0ff; width: 1fr; height: 3; padding: 0 1;
}
#user-input:focus { border-bottom: solid #00e676; }

/* Footer */
#app-footer {
    dock: bottom; height: 1; background: #0d0d1f;
    border-top: solid #1a1a35; padding: 0 3; layout: horizontal;
}
#footer-shortcuts { color: #2a2a44; width: 1fr; content-align: left middle; }
#footer-session   { color: #2a2a44; width: auto; content-align: right middle; }

/* ── Model picker modal ── */
ModelPicker {
    align: center middle;
}
#model-dialog {
    width: 72; height: auto; max-height: 38;
    background: #10101f; border: round #2a2a55;
    padding: 1 2;
}
#model-title  { color: #00e676; text-style: bold; height: 1; margin-bottom: 1; }
#model-list   { height: auto; max-height: 28; overflow-y: auto; }
.model-group  { color: #444466; text-style: bold; height: 1; margin: 1 0 0 0; }
.model-row    { height: 1; layout: horizontal; padding: 0 1; }
.model-row.--highlight { background: #1e1e3f; }
.model-dot    { width: 3; color: #00e676; }
.model-name   { width: 24; color: #e0e0ff; }
.model-tier   { width: 10; }
.model-desc   { color: #444466; width: 1fr; }
#model-hint   { color: #333355; height: 1; margin-top: 1; }

/* ── Effort picker modal ── */
EffortPicker { align: center middle; }
#effort-dialog {
    width: 58; height: auto;
    background: #10101f; border: round #2a2a55;
    padding: 1 2;
}
#effort-title  { color: #00e676; text-style: bold; height: 1; margin-bottom: 1; }
.effort-row    { height: 1; layout: horizontal; padding: 0 1; }
.effort-row.--highlight { background: #1e1e3f; }
.effort-dot    { width: 3; }
.effort-name   { width: 10; text-style: bold; }
.effort-desc   { color: #444466; width: 1fr; }
#effort-hint   { color: #333355; height: 1; margin-top: 1; }

/* Upload modal */
UploadModal { align: center middle; }
#upload-dialog {
    width: 68; height: auto;
    background: #10101f; border: round #2a2a55; padding: 1 2;
}
#upload-title  { color: #00e676; text-style: bold; height: 1; margin-bottom: 1; }
#upload-input  {
    background: #0b0b1f; border: none; border-bottom: solid #2a2a4a;
    color: #e0e0ff; width: 1fr; height: 3;
}
#upload-input:focus { border-bottom: solid #00e676; }
.upload-recent { height: 1; layout: horizontal; padding: 0 1; }
.upload-recent.--highlight { background: #1e1e3f; }
.upload-icon { width: 3; color: #40c4ff; }
.upload-name { width: 28; color: #e0e0ff; }
.upload-size { color: #444466; width: 1fr; }
#upload-hint   { color: #333355; height: 1; margin-top: 1; }
#upload-attach { color: #444466; height: 1; }

/* Keys dashboard modal */
KeysModal { align: center middle; }
#keys-dialog {
    width: 64; height: auto;
    background: #10101f; border: round #2a2a55; padding: 1 2;
}
#keys-title  { color: #00e676; text-style: bold; height: 1; margin-bottom: 1; }
.keys-row    { height: 1; layout: horizontal; padding: 0 1; }
.keys-row.--highlight { background: #1a1a3a; }
.keys-provider { width: 26; color: #40c4ff; }
.keys-status   { width: 1fr; }
#keys-hint     { color: #333355; height: 1; margin-top: 1; }

/* Set key modal */
SetKeyModal { align: center middle; }
#setkey-dialog {
    width: 66; height: auto;
    background: #10101f; border: round #2a2a55; padding: 1 2;
}
#setkey-title    { color: #00e676; text-style: bold; height: 1; margin-bottom: 1; }
#setkey-provider { color: #40c4ff; height: 1; margin-bottom: 1; padding: 0 1; }
#setkey-label    { color: #888888; height: 1; padding: 0 1; }
#setkey-input    {
    background: #0b0b1f; border: none; border-bottom: solid #2a2a4a;
    color: #e0e0ff; width: 1fr; height: 3; margin: 0 0 1 0;
}
#setkey-input:focus { border-bottom: solid #00e676; }
#setkey-masked { color: #444466; height: 1; padding: 0 1; }
.setkey-btn-row  { height: 3; layout: horizontal; margin-top: 1; }
#setkey-save     { background: #0a2a0a; border: round #00e676; color: #00e676; width: 12; height: 3; }
#setkey-save:hover { background: #0e3a0e; }
#setkey-delete   { background: #1a0a0a; border: round #440000; color: #ff5252; width: 12; height: 3; margin-left: 2; }
#setkey-delete:hover { background: #2a0a0a; }
#setkey-cancel   { background: #10101f; border: round #333355; color: #555577; width: 12; height: 3; margin-left: 2; }
#setkey-cancel:hover { background: #1a1a3a; }
#setkey-hint     { color: #333355; height: 1; margin-top: 1; }

/* MCP servers dashboard modal */
McpModal { align: center middle; }
#mcp-dialog {
    width: 70; height: auto; max-height: 30;
    background: #10101f; border: round #2a2a55; padding: 1 2;
}
#mcp-title   { color: #00e676; text-style: bold; height: 1; margin-bottom: 1; }
.mcp-row     { height: auto; layout: vertical; padding: 0 1; margin-bottom: 1; }
.mcp-row.--highlight { background: #1a1a3a; }
.mcp-row-head   { height: 1; layout: horizontal; }
.mcp-row-name   { width: 1fr; color: #40c4ff; }
.mcp-row-status { width: 20; }
.mcp-row-cmd    { color: #444466; height: 1; padding-left: 1; }
.mcp-row-tools  { color: #333355; height: 1; padding-left: 1; }
#mcp-empty      { color: #444466; height: 1; padding: 0 1; margin-bottom: 1; }
#mcp-hint       { color: #333355; height: 1; margin-top: 1; }

/* Add MCP server modal */
AddMcpModal { align: center middle; }
#addmcp-dialog {
    width: 66; height: auto;
    background: #10101f; border: round #2a2a55; padding: 1 2;
}
#addmcp-title  { color: #00e676; text-style: bold; height: 1; margin-bottom: 1; }
.addmcp-label  { color: #888888; height: 1; padding: 0 1; margin-top: 1; }
.addmcp-input  {
    background: #0b0b1f; border: none; border-bottom: solid #2a2a4a;
    color: #e0e0ff; width: 1fr; height: 3;
}
.addmcp-input:focus { border-bottom: solid #00e676; }
#addmcp-error  { color: #ff5252; height: 1; padding: 0 1; margin-top: 1; }
.addmcp-btn-row { height: 3; layout: horizontal; margin-top: 1; }
#addmcp-save   { background: #0a2a0a; border: round #00e676; color: #00e676; width: 14; height: 3; }
#addmcp-save:hover { background: #0e3a0e; }
#addmcp-cancel { background: #10101f; border: round #333355; color: #555577; width: 14; height: 3; margin-left: 2; }
#addmcp-cancel:hover { background: #1a1a3a; }
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

class ChatSpacer(Widget):
    DEFAULT_CSS = "ChatSpacer { height: 1fr; background: #0b0b12; }"
    def render(self): return ""


class ChatMessage(Widget):
    def __init__(self, role: str, content: str, model_label: str = "", timestamp: str = "") -> None:
        super().__init__(classes="msg-block")
        self.role = role
        self.content = content
        self.model_label = model_label
        self.ts = timestamp or datetime.now().strftime("%H:%M")

    def compose(self) -> ComposeResult:
        ts_dim = f"  [dim]{self.ts}[/dim]"
        lbl = self.model_label or self.role
        if self.role == "you":
            yield Label(f"  you{ts_dim}", classes="msg-label msg-label-you")
            yield Static(self.content, classes="msg-content-you", markup=False)
        elif self.role == "dabba":
            yield Label(f"  {lbl}{ts_dim}", classes="msg-label msg-label-dabba")
            yield TUIMarkdown(self.content, classes="msg-content-dabba")
        elif self.role == "error":
            yield Label(f"  error{ts_dim}", classes="msg-label msg-label-system")
            yield Static(self.content, classes="msg-content-error", markup=False)
        elif self.role == "code":
            yield Label(f"  output{ts_dim}", classes="msg-label msg-label-system")
            yield Static(self.content, classes="msg-content-code", markup=False)
        else:
            yield Static(f"  [dim]{self.content}[/dim]", classes="msg-content-system")


class ThinkingWidget(Widget):
    _frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    _idx: reactive[int] = reactive(0)
    _timer = None

    def __init__(self) -> None:
        super().__init__(id="thinking")

    def render(self):
        from rich.text import Text
        t = Text()
        t.append("  dabba  ", style="bold green")
        t.append(f"{self._frames[self._idx % len(self._frames)]} thinking...", style="dim")
        return t

    def start(self) -> None:
        self.add_class("visible")
        if self._timer is None:
            self._timer = self.set_interval(0.08, self._tick)

    def stop(self) -> None:
        self.remove_class("visible")
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._idx += 1


class SuggestionItem(Widget):
    def __init__(self, cmd: str, desc: str, index: int = 0, highlighted: bool = False) -> None:
        super().__init__(classes="suggestion-item" + (" --highlight" if highlighted else ""))
        self.cmd = cmd
        self.desc = desc
        self.index = index

    def compose(self) -> ComposeResult:
        yield Label(self.cmd, classes="suggestion-cmd")
        yield Label(self.desc, classes="suggestion-desc")

    def on_enter(self, event) -> None:
        """Mouse hover — move the highlight to this row."""
        event.stop()
        panel = self.parent
        if isinstance(panel, SuggestionsPanel):
            panel.select_index(self.index)

    def on_click(self, event) -> None:
        """Mouse click — select this command, same as pressing Tab on it."""
        event.stop()
        panel = self.parent
        if isinstance(panel, SuggestionsPanel):
            panel.select_index(self.index)
        self.app.action_suggest_tab()


class SuggestionsPanel(Widget):
    _matches: reactive[list] = reactive([], recompose=True)
    # recompose=True lets Textual schedule the (now-async) recompose itself;
    # calling self.recompose() directly no-ops since Textual 8's recompose()
    # became a coroutine and was never awaited here.
    _selected: reactive[int] = reactive(0, recompose=True)

    def __init__(self) -> None:
        super().__init__(id="suggestions")

    def compose(self) -> ComposeResult:
        for i, (cmd, desc) in enumerate(self._matches):
            yield SuggestionItem(cmd, desc, index=i, highlighted=(i == self._selected))

    def update(self, text: str) -> None:
        if not text.startswith("/"):
            self._matches = []
            self.remove_class("visible")
            return
        q = text.lower()
        self._matches = [(c, d) for c, d in SLASH_COMMANDS if c.startswith(q)]
        self._selected = 0
        self.add_class("visible") if self._matches else self.remove_class("visible")

    def move_up(self) -> None:
        if self._matches:
            self._selected = (self._selected - 1) % len(self._matches)

    def move_down(self) -> None:
        if self._matches:
            self._selected = (self._selected + 1) % len(self._matches)

    def select_index(self, index: int) -> None:
        """Move the highlight to `index` (used by mouse hover/click)."""
        if self._matches and 0 <= index < len(self._matches) and index != self._selected:
            self._selected = index

    def get_selected(self) -> Optional[str]:
        if self._matches and 0 <= self._selected < len(self._matches):
            return self._matches[self._selected][0]
        return None

    def clear(self) -> None:
        self._matches = []
        self.remove_class("visible")


# ── Modal screens ──────────────────────────────────────────────────────────────

class ModelRow(Widget):
    def __init__(self, model_id: str, name: str, tier: str, desc: str, active: bool, highlighted: bool) -> None:
        super().__init__(classes="model-row" + (" --highlight" if highlighted else ""))
        self.model_id = model_id
        self._name = name
        self._tier = tier
        self._desc = desc
        self._active = active

    def compose(self) -> ComposeResult:
        dot = "●" if self._active else "○"
        color = TIER_COLOR.get(self._tier, "dim")
        yield Label(dot, classes="model-dot")
        yield Label(self._name, classes="model-name")
        yield Label(f"[{color}]{self._tier}[/{color}]", classes="model-tier")
        yield Label(self._desc[:40], classes="model-desc")


class ModelPicker(ModalScreen):
    """Full-screen model selector modal."""

    BINDINGS = [
        Binding("up",     "move_up",   "", show=False),
        Binding("down",   "move_down", "", show=False),
        Binding("enter",  "select",    "", show=False),
        Binding("escape", "dismiss",   "", show=False),
    ]

    def __init__(self, current_model: str, config) -> None:
        super().__init__()
        self._current = current_model
        self._config = config
        self._all_models = []
        self._flat: list = []
        self._idx = 0
        self._load_models()

    def _load_models(self):
        from dabba.providers.registry import ProviderRegistry
        reg = ProviderRegistry(self._config)
        models = reg.list_all_models()
        by_provider: dict = {}
        for m in models:
            by_provider.setdefault(m.provider, []).append(m)
        # Build flat list of (type, data) for cursor navigation
        flat = []
        for p in PROVIDER_ORDER:
            ms = by_provider.get(p, [])
            if not ms:
                continue
            flat.append(("header", p, PROVIDER_LABELS.get(p, p.upper())))
            for m in ms:
                flat.append(("model", m))
        self._flat = flat
        # Set initial cursor to current model
        for i, item in enumerate(flat):
            if item[0] == "model" and item[1].id == self._current:
                self._idx = i
                break

    def compose(self) -> ComposeResult:
        with Container(id="model-dialog"):
            yield Label("  Select Model   ↑↓ navigate  Enter select  Esc cancel", id="model-title")
            with Vertical(id="model-list"):
                self._render_rows()

    def _render_rows(self):
        # Called on mount + on cursor change via recompose
        pass

    def on_mount(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        ml = self.query_one("#model-list")
        ml.remove_children()
        for i, item in enumerate(self._flat):
            if item[0] == "header":
                ml.mount(Static(f"  {item[2]}", classes="model-group"))
            else:
                m = item[1]
                ml.mount(ModelRow(
                    m.id, m.name, m.tier, m.description,
                    active=(m.id == self._current),
                    highlighted=(i == self._idx),
                ))

    def action_move_up(self) -> None:
        self._idx = max(0, self._idx - 1)
        while self._idx > 0 and self._flat[self._idx][0] == "header":
            self._idx -= 1
        self._rebuild()

    def action_move_down(self) -> None:
        self._idx = min(len(self._flat) - 1, self._idx + 1)
        while self._idx < len(self._flat) - 1 and self._flat[self._idx][0] == "header":
            self._idx += 1
        self._rebuild()

    def action_select(self) -> None:
        item = self._flat[self._idx] if self._idx < len(self._flat) else None
        if item and item[0] == "model":
            self.dismiss(item[1].id)
        else:
            self.dismiss(None)

    def action_dismiss(self) -> None:
        self.dismiss(None)


class EffortPicker(ModalScreen):
    """Effort level selector modal."""

    BINDINGS = [
        Binding("up",     "move_up",   "", show=False),
        Binding("down",   "move_down", "", show=False),
        Binding("enter",  "select",    "", show=False),
        Binding("escape", "dismiss",   "", show=False),
    ]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current
        self._idx = next((i for i, (k, _) in enumerate(EFFORT_OPTIONS) if k == current), 1)

    def compose(self) -> ComposeResult:
        with Container(id="effort-dialog"):
            yield Label("  Select Effort   ↑↓  Enter  Esc", id="effort-title")
            with Vertical():
                for i, (key, desc) in enumerate(EFFORT_OPTIONS):
                    dot = "●" if key == self._current else "○"
                    color = TIER_COLOR.get(key, "dim")
                    row_classes = "effort-row" + (" --highlight" if i == self._idx else "")
                    with Container(classes=row_classes):
                        yield Label(dot, classes="effort-dot")
                        yield Label(f"[{color}]{key}[/{color}]", classes="effort-name")
                        yield Label(desc, classes="effort-desc")
            yield Label("  Affects token budget and thinking depth", id="effort-hint")

    def action_move_up(self) -> None:
        if self._idx > 0:
            self._idx -= 1
            self._refresh_rows()

    def action_move_down(self) -> None:
        if self._idx < len(EFFORT_OPTIONS) - 1:
            self._idx += 1
            self._refresh_rows()

    def _refresh_rows(self) -> None:
        try:
            rows = self.query(".effort-row")
            for i, row in enumerate(rows):
                if i == self._idx:
                    row.add_class("--highlight")
                else:
                    row.remove_class("--highlight")
        except Exception:
            pass

    def action_select(self) -> None:
        self.dismiss(EFFORT_OPTIONS[self._idx][0])

    def action_dismiss(self) -> None:
        self.dismiss(None)


class UploadModal(ModalScreen):
    """File upload / attach modal. Enter a path or pick from recents."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "", show=False),
        Binding("enter",  "confirm",       "", show=False),
        Binding("up",     "move_up",       "", show=False),
        Binding("down",   "move_down",     "", show=False),
        Binding("tab",    "complete_tab",  "", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._recent = self._find_recent_files()
        self._idx = -1  # -1 = input box is active

    def _find_recent_files(self) -> list:
        """Find recently modified files in cwd for quick pick."""
        import os
        from pathlib import Path
        try:
            cwd = Path.cwd()
            files = sorted(
                [f for f in cwd.rglob("*") if f.is_file() and not any(p.startswith(".") for p in f.parts[-3:])],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )[:8]
            return files
        except Exception:
            return []

    def compose(self) -> ComposeResult:
        with Container(id="upload-dialog"):
            yield Label("  Attach File   Enter confirm  ↑↓ pick recent  Esc cancel", id="upload-title")
            yield Input(placeholder="/path/to/file  or  filename.py", id="upload-input")
            if self._recent:
                yield Label("  Recent files:", id="upload-attach")
                with Vertical():
                    for i, f in enumerate(self._recent):
                        size = f.stat().st_size
                        size_str = f"{size // 1024}KB" if size > 1024 else f"{size}B"
                        hl = " --highlight" if i == self._idx else ""
                        with Container(classes=f"upload-recent{hl}", id=f"urow-{i}"):
                            yield Label("📄", classes="upload-icon")
                            yield Label(f.name, classes="upload-name")
                            yield Label(f"{f.parent.name}/{size_str}", classes="upload-size")
            yield Label("  Ctrl+V to paste a path  ·  Tab to autocomplete", id="upload-hint")

    def on_mount(self) -> None:
        self.query_one("#upload-input", Input).focus()

    def action_move_up(self) -> None:
        if self._recent:
            self._idx = max(-1, self._idx - 1)
            self._refresh_rows()
            if self._idx >= 0:
                self.query_one("#upload-input", Input).value = str(self._recent[self._idx])

    def action_move_down(self) -> None:
        if self._recent:
            self._idx = min(len(self._recent) - 1, self._idx + 1)
            self._refresh_rows()
            if self._idx >= 0:
                self.query_one("#upload-input", Input).value = str(self._recent[self._idx])

    def action_complete_tab(self) -> None:
        """Tab = autocomplete path."""
        import glob
        inp = self.query_one("#upload-input", Input)
        val = inp.value
        matches = glob.glob(val + "*")
        if len(matches) == 1:
            inp.value = matches[0]
            inp.cursor_position = len(matches[0])
        elif matches:
            common = matches[0]
            for m in matches[1:]:
                for j, (a, b) in enumerate(zip(common, m)):
                    if a != b:
                        common = common[:j]; break
            inp.value = common
            inp.cursor_position = len(common)

    def _refresh_rows(self) -> None:
        for i in range(len(self._recent)):
            try:
                row = self.query_one(f"#urow-{i}")
                if i == self._idx:
                    row.add_class("--highlight")
                else:
                    row.remove_class("--highlight")
            except Exception:
                pass

    def action_confirm(self) -> None:
        val = self.query_one("#upload-input", Input).value.strip()
        self.dismiss(val if val else None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


_PROVIDERS = [
    ("anthropic",    "Claude (Anthropic)",       "sk-ant-…"),
    ("openai",       "GPT / o-series (OpenAI)",  "sk-…"),
    ("google",       "Gemini (Google)",           "AIza…"),
    ("nvidia",       "NVIDIA NIM",               "nvapi-…"),
    ("huggingface",  "Hugging Face",             "hf_…"),
]


class SetKeyModal(ModalScreen):
    """Full-screen modal to paste an API key for a specific provider."""

    BINDINGS = [
        Binding("escape", "cancel", "", show=False),
        Binding("ctrl+s", "save",   "", show=False),
    ]

    def __init__(self, provider_id: str, provider_label: str, placeholder: str, current_key: str, config) -> None:
        super().__init__()
        self._pid = provider_id
        self._plabel = provider_label
        self._placeholder = placeholder
        self._current = current_key
        self._config = config

    def compose(self) -> ComposeResult:
        masked = (self._current[:8] + "…" + self._current[-4:]) if len(self._current) > 12 else (self._current[:4] + "…" if self._current else "")
        with Container(id="setkey-dialog"):
            yield Label(f"  Set API Key", id="setkey-title")
            yield Label(f"  Provider: {self._plabel}", id="setkey-provider")
            yield Label(f"  Paste your key below  (Ctrl+Shift+V to paste)", id="setkey-label")
            yield Input(
                placeholder=self._placeholder,
                password=False,
                id="setkey-input",
            )
            if masked:
                yield Label(f"  Current: {masked}", id="setkey-masked")
            else:
                yield Label("  No key set yet", id="setkey-masked")
            with Container(classes="setkey-btn-row"):
                yield Button("  Save", id="setkey-save", variant="success")
                if self._current:
                    yield Button("  Delete", id="setkey-delete", variant="error")
                yield Button("  Cancel", id="setkey-cancel")
            yield Label("  Ctrl+S to save  ·  Esc to cancel  ·  key is stored in ~/.config/dabba/cli_config.yaml", id="setkey-hint")

    def on_mount(self) -> None:
        self.query_one("#setkey-input", Input).focus()

    @on(Button.Pressed, "#setkey-save")
    def on_save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#setkey-delete")
    def on_delete(self) -> None:
        if not hasattr(self._config, "api_keys") or self._config.api_keys is None:
            self._config.api_keys = {}
        self._config.api_keys.pop(self._pid, None)
        self._config.save()
        self.dismiss(("deleted", self._pid))

    @on(Button.Pressed, "#setkey-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        key = self.query_one("#setkey-input", Input).value.strip()
        if not key:
            self.query_one("#setkey-masked", Label).update("  [red]Key cannot be empty[/red]")
            return
        if not hasattr(self._config, "api_keys") or self._config.api_keys is None:
            self._config.api_keys = {}
        self._config.api_keys[self._pid] = key
        self._config.save()
        self.dismiss(("saved", self._pid, key))

    def action_cancel(self) -> None:
        self.dismiss(None)


class KeysModal(ModalScreen):
    """API key dashboard — shows all providers, click one to set/edit its key."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "", show=False),
        Binding("up",     "move_up",       "", show=False),
        Binding("down",   "move_down",     "", show=False),
        Binding("enter",  "select",        "", show=False),
    ]

    def __init__(self, config) -> None:
        super().__init__()
        self._config = config
        self._idx = 0

    def compose(self) -> ComposeResult:
        keys = getattr(self._config, "api_keys", {}) or {}
        with Container(id="keys-dialog"):
            yield Label("  API Keys   ↑↓ navigate  Enter edit  Esc close", id="keys-title")
            with Vertical(id="keys-list"):
                for i, (pid, plabel, _ph) in enumerate(_PROVIDERS):
                    key = keys.get(pid, "")
                    if key:
                        status = f"[green]● {key[:8]}…[/green]"
                    else:
                        status = "[dim]○ not set — click to add[/dim]"
                    hl = " --highlight" if i == self._idx else ""
                    with Container(classes=f"keys-row{hl}", id=f"krow-{i}"):
                        yield Label(f"  {plabel}", classes="keys-provider")
                        yield Label(status, classes="keys-status")
            yield Label("  Enter or click a provider to paste its key", id="keys-hint")

    def action_move_up(self) -> None:
        self._idx = max(0, self._idx - 1)
        self._refresh()

    def action_move_down(self) -> None:
        self._idx = min(len(_PROVIDERS) - 1, self._idx + 1)
        self._refresh()

    def _refresh(self) -> None:
        for i in range(len(_PROVIDERS)):
            try:
                row = self.query_one(f"#krow-{i}")
                if i == self._idx:
                    row.add_class("--highlight")
                else:
                    row.remove_class("--highlight")
            except Exception:
                pass

    def action_select(self) -> None:
        self._open_set_key(self._idx)

    def on_click(self, event) -> None:
        # Find which row was clicked
        for i in range(len(_PROVIDERS)):
            try:
                row = self.query_one(f"#krow-{i}")
                if row.region.contains(event.screen_x, event.screen_y):
                    self._idx = i
                    self._refresh()
                    self._open_set_key(i)
                    return
            except Exception:
                pass

    def _open_set_key(self, idx: int) -> None:
        pid, plabel, placeholder = _PROVIDERS[idx]
        keys = getattr(self._config, "api_keys", {}) or {}
        current = keys.get(pid, "")

        def _on_result(result) -> None:
            if result is None:
                return
            action = result[0]
            # Refresh the row status
            keys2 = getattr(self._config, "api_keys", {}) or {}
            k = keys2.get(pid, "")
            status_label = f"[green]● {k[:8]}…[/green]" if k else "[dim]○ not set — click to add[/dim]"
            try:
                row = self.query_one(f"#krow-{idx}")
                row.query_one(".keys-status", Label).update(status_label)
            except Exception:
                pass

        self.app.push_screen(
            SetKeyModal(pid, plabel, placeholder, current, self._config),
            _on_result,
        )

    def action_dismiss_modal(self) -> None:
        self.dismiss()


class AddMcpModal(ModalScreen):
    """Form to add one MCP server entry to mcp_servers.json."""

    BINDINGS = [
        Binding("escape", "cancel", "", show=False),
        Binding("ctrl+s", "save",   "", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="addmcp-dialog"):
            yield Label("  Add MCP Server", id="addmcp-title")
            yield Label("  Name", classes="addmcp-label")
            yield Input(placeholder="filesystem", id="addmcp-name", classes="addmcp-input")
            yield Label("  Command", classes="addmcp-label")
            yield Input(placeholder="npx", id="addmcp-command", classes="addmcp-input")
            yield Label("  Args (space-separated)", classes="addmcp-label")
            yield Input(placeholder="-y @modelcontextprotocol/server-filesystem /path", id="addmcp-args", classes="addmcp-input")
            yield Label("  Env (optional, KEY=value KEY2=value2)", classes="addmcp-label")
            yield Input(placeholder="API_KEY=...", id="addmcp-env", classes="addmcp-input")
            yield Label("", id="addmcp-error")
            with Container(classes="addmcp-btn-row"):
                yield Button("  Save & Connect", id="addmcp-save", variant="success")
                yield Button("  Cancel", id="addmcp-cancel")

    def on_mount(self) -> None:
        self.query_one("#addmcp-name", Input).focus()

    @on(Button.Pressed, "#addmcp-save")
    def on_save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#addmcp-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        name = self.query_one("#addmcp-name", Input).value.strip()
        command = self.query_one("#addmcp-command", Input).value.strip()
        args_text = self.query_one("#addmcp-args", Input).value.strip()
        env_text = self.query_one("#addmcp-env", Input).value.strip()

        if not name or not command:
            self.query_one("#addmcp-error", Label).update("  [red]Name and command are required[/red]")
            return

        from dabba.agent.mcp_client import McpServerConfig, load_mcp_config, save_mcp_config

        args = args_text.split() if args_text else []
        env = {}
        for pair in env_text.split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                env[k] = v

        configs = load_mcp_config()
        configs[name] = McpServerConfig(name=name, command=command, args=args, env=env)
        try:
            save_mcp_config(configs)
        except OSError as exc:
            self.query_one("#addmcp-error", Label).update(f"  [red]Could not save: {exc}[/red]")
            return

        self.dismiss(("saved", name))

    def action_cancel(self) -> None:
        self.dismiss(None)


class McpModal(ModalScreen):
    """
    MCP servers dashboard — list configured servers with live connection
    status, add new ones, remove existing ones.

    Adding connects immediately (mirrors POST /v1/mcp/reload in
    dabba/api/agent_endpoints.py, just called in-process instead of over
    HTTP since the TUI holds the same AgentProxy directly). Removing only
    edits the config file — a server already connected this session stays
    connected until the TUI restarts, same limitation as the VSCode panel.
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal",  "", show=False),
        Binding("up",     "move_up",        "", show=False),
        Binding("down",   "move_down",      "", show=False),
        Binding("a",      "add_server",     "", show=False),
        Binding("d",      "delete_server",  "", show=False),
        Binding("r",      "refresh_status", "", show=False),
    ]

    def __init__(self, agent) -> None:
        super().__init__()
        self.agent = agent
        self._idx = 0
        self._names: List[str] = []

    def compose(self) -> ComposeResult:
        with Container(id="mcp-dialog"):
            yield Label("  MCP Servers   ↑↓ navigate  a add  d remove  r refresh  Esc close", id="mcp-title")
            yield Vertical(id="mcp-list")
            yield Label("  Config: ~/.config/dabba/mcp_servers.json", id="mcp-hint")

    async def on_mount(self) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        # remove_children()/mount() are both async in Textual — awaiting them
        # is required, not optional: firing mount() before the prior
        # remove_children() has actually completed leaves the old widgets'
        # ids still registered and the new ones collide (DuplicateIds).
        from dabba.agent.mcp_client import load_mcp_config

        configs = load_mcp_config()
        self._names = list(configs.keys())
        try:
            live = self.agent.mcp_manager.status()
        except Exception:
            live = {"servers": [], "tools_by_server": {}}

        container = self.query_one("#mcp-list", Vertical)
        await container.remove_children()

        if not self._names:
            await container.mount(Label("  No MCP servers configured yet — press 'a' to add one", id="mcp-empty"))
            return

        rows = []
        for i, name in enumerate(self._names):
            cfg = configs[name]
            connected = name in live["servers"]
            tools = live["tools_by_server"].get(name, [])
            status = "[green]● connected[/green]" if connected else "[dim]○ not connected[/dim]"
            hl = " --highlight" if i == self._idx else ""
            cmd_line = f"{cfg.command} {' '.join(cfg.args)}"
            tools_line = f"tools: {', '.join(tools)}" if tools else "tools: (none yet — press r to refresh)"
            text = f"  {name}   {status}\n  [dim]{cmd_line}[/dim]\n  [dim]{tools_line}[/dim]"
            rows.append(Label(text, id=f"mcprow-{i}", classes=f"mcp-row{hl}"))
        await container.mount(*rows)

    async def action_move_up(self) -> None:
        if self._names:
            self._idx = max(0, self._idx - 1)
        await self._refresh()

    async def action_move_down(self) -> None:
        if self._names:
            self._idx = min(len(self._names) - 1, self._idx + 1)
        await self._refresh()

    def action_add_server(self) -> None:
        async def _on_result(result) -> None:
            if result is not None:
                await self._reconnect_and_refresh()
        self.app.push_screen(AddMcpModal(), _on_result)

    async def action_delete_server(self) -> None:
        if not self._names:
            return
        name = self._names[self._idx]
        from dabba.agent.mcp_client import load_mcp_config, save_mcp_config

        configs = load_mcp_config()
        configs.pop(name, None)
        save_mcp_config(configs)
        self._idx = max(0, self._idx - 1)
        await self._refresh()

    async def action_refresh_status(self) -> None:
        await self._reconnect_and_refresh()

    async def _reconnect_and_refresh(self) -> None:
        """Connect any servers in the config the manager hasn't seen yet, then redraw."""
        from dabba.agent.mcp_client import load_mcp_config, register_mcp_tools

        try:
            configs = load_mcp_config()
            self.agent.mcp_manager.connect(configs)
            register_mcp_tools(self.agent._get_registry(), self.agent.mcp_manager)
        except Exception:
            pass  # best-effort — _refresh() below still shows whatever did connect
        await self._refresh()

    def action_dismiss_modal(self) -> None:
        self.dismiss()


# ── Messages ───────────────────────────────────────────────────────────────────

class AgentResponse(Message):
    def __init__(self, text: str) -> None:
        super().__init__(); self.text = text

class AgentError(Message):
    def __init__(self, error: str) -> None:
        super().__init__(); self.error = error

class ModelChanged(Message):
    def __init__(self, model_id: str) -> None:
        super().__init__(); self.model_id = model_id

class EffortChanged(Message):
    def __init__(self, effort: str) -> None:
        super().__init__(); self.effort = effort


# ── Main App ───────────────────────────────────────────────────────────────────

class DabbaTUI(App[None]):
    CSS = _CSS
    ENABLE_MOUSE = True

    BINDINGS = [
        # Use ctrl+q to quit so ctrl+c is free for copy in terminal
        Binding("ctrl+q",  "quit",                "Quit",   show=True),
        Binding("ctrl+l",  "clear_chat",           "Clear",  show=True),
        Binding("f1",      "show_help",            "Help",   show=True),
        Binding("f2",      "open_model_picker",    "Model",  show=True),
        Binding("f3",      "open_effort_picker",   "Effort", show=True),
        Binding("f4",      "open_upload",          "Upload", show=True),
        # Suggestion navigation (only fires when input focused)
        Binding("up",      "suggest_up",           "",       show=False),
        Binding("down",    "suggest_down",          "",       show=False),
        Binding("tab",     "suggest_tab",           "",       show=False),
        Binding("escape",  "dismiss_suggestions",   "",       show=False),
    ]

    def __init__(self, agent: "AgentProxy", config: "CliConfig", version: str = "1.0") -> None:
        super().__init__()
        self.agent = agent
        self.config = config
        self.version = version
        self._message_count = 0
        self._session_start = time.time()
        self._busy = False
        self._pending_attachment: Optional[dict] = None

    def compose(self) -> ComposeResult:
        effort = getattr(self.config, "effort", "medium")
        with Container(id="app-header"):
            yield Label("  ⌘  dabba", id="header-logo")
            yield Label(f"  {self.config.default_model}", id="header-model")
            yield Label(f"[{TIER_COLOR.get(effort,'dim')}]{effort}[/{TIER_COLOR.get(effort,'dim')}]", id="header-effort")
            yield Label(f"v{self.version}", id="header-meta")
            yield Label("● ready", id="header-status")

        with ScrollableContainer(id="chat-scroll"):
            yield ChatSpacer()
            yield ThinkingWidget()

        yield SuggestionsPanel()

        with Container(id="input-container"):
            yield Label("❯", id="input-prompt")
            yield Input(placeholder="Message dabba…  (F2 model · F3 effort · F4 upload · /help)", id="user-input")

        with Container(id="app-footer"):
            yield Label("  F2 model · F3 effort · F4 upload · /keys · /git · /view · /run · Ctrl+Q exit", id="footer-shortcuts")
            yield Label("", id="footer-session")

    def on_mount(self) -> None:
        self._post_system("Type a message and press Enter  ·  F2 to switch model  ·  /help for all commands")
        self.query_one("#user-input", Input).focus()
        self._update_footer()

    # ── Input ──────────────────────────────────────────────────────────────────

    @on(Input.Changed, "#user-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one(SuggestionsPanel).update(event.value)

    @on(Input.Submitted, "#user-input")
    def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        suggestions = self.query_one(SuggestionsPanel)
        if "visible" in suggestions.classes and text.startswith("/") and " " not in text:
            selected = suggestions.get_selected()
            if selected and selected != text:
                event.input.value = selected + " "
                event.input.cursor_position = len(selected) + 1
                suggestions.clear()
                return
        suggestions.clear()
        event.input.clear()
        if text.startswith("/"):
            self._handle_command(text)
        elif self._busy:
            self._post_system("Still thinking, please wait…")
        elif _is_likely_command(text):
            self._run_shell_command(text)
        else:
            # Prepend any pending file attachment to the message
            actual_input = text
            if self._pending_attachment:
                att = self._pending_attachment
                actual_input = (
                    f"[Attached file: {att['path']}]\n"
                    f"```{att['ext']}\n{att['content']}\n```\n\n"
                    f"{text}"
                )
                self._pending_attachment = None
            self._add_message("you", text)
            self._run_agent(actual_input)

    # ── Suggestion actions ─────────────────────────────────────────────────────

    def action_suggest_up(self) -> None:
        self.query_one(SuggestionsPanel).move_up()

    def action_suggest_down(self) -> None:
        self.query_one(SuggestionsPanel).move_down()

    def action_suggest_tab(self) -> None:
        s = self.query_one(SuggestionsPanel)
        if "visible" in s.classes:
            selected = s.get_selected()
            if selected:
                inp = self.query_one("#user-input", Input)
                inp.value = selected + " "
                inp.cursor_position = len(selected) + 1
                s.clear()

    def action_dismiss_suggestions(self) -> None:
        self.query_one(SuggestionsPanel).clear()

    # ── Model / Effort pickers ─────────────────────────────────────────────────

    def action_open_model_picker(self) -> None:
        def _on_result(model_id: Optional[str]) -> None:
            if not model_id:
                return
            # Check if this model's provider needs a key that isn't set yet
            from dabba.providers.registry import _MODEL_MAP
            info = _MODEL_MAP.get(model_id)
            if info and info.requires_key:
                keys = getattr(self.config, "api_keys", {}) or {}
                if not keys.get(info.provider, ""):
                    # Find provider label + placeholder for the modal
                    entry = next(((p, l, ph) for p, l, ph in _PROVIDERS if p == info.provider), None)
                    if entry:
                        p, label, ph = entry
                        def _on_key_result(result) -> None:
                            if result and result[0] == "saved":
                                self._apply_model(model_id)
                            else:
                                self._post_system(f"Key not saved — still using {self.config.default_model}")
                        self.push_screen(SetKeyModal(p, label, ph, "", self.config), _on_key_result)
                        return
            self._apply_model(model_id)

        self.push_screen(ModelPicker(self.config.default_model, self.config), _on_result)

    def _apply_model(self, model_id: str) -> None:
        self.config.default_model = model_id
        self.config.save()
        self._update_header_model(model_id)
        self._post_system(f"Model → {model_id}")
        if hasattr(self.agent, "_provider_registry"):
            self.agent._provider_registry = None

    def action_open_effort_picker(self) -> None:
        def _on_result(effort: Optional[str]) -> None:
            if effort:
                self.config.effort = effort
                self.config.save()
                self._update_header_effort(effort)
                self._post_system(f"Effort → {effort}")

        self.push_screen(EffortPicker(getattr(self.config, "effort", "medium")), _on_result)

    def action_open_upload(self) -> None:
        def _on_result(path: Optional[str]) -> None:
            if path:
                self._attach_file(path)

        self.push_screen(UploadModal(), _on_result)

    # ── Commands ──────────────────────────────────────────────────────────────

    def _handle_command(self, cmd: str) -> None:
        parts = cmd.strip().split()
        c = parts[0].lower()
        handlers = {
            "/exit":        lambda a: self.action_quit(),
            "/quit":        lambda a: self.action_quit(),
            "/help":        lambda a: self._cmd_help(),
            "/?":           lambda a: self._cmd_help(),
            "/clear":       lambda a: self.action_clear_chat(),
            "/save":        self._cmd_save,
            "/history":     lambda a: self._post_system(f"{self._message_count} messages this session."),
            "/reset":       lambda a: (self.agent.reset(), self._post_system("Conversation reset.")),
            "/metrics":     lambda a: self._cmd_metrics(),
            "/model":       lambda a: self.action_open_model_picker(),
            "/effort":      lambda a: self._cmd_effort(a),
            "/keys":        self._cmd_keys,
            "/tools":       lambda a: self._cmd_tools(),
            "/mcp":         lambda a: self._cmd_mcp(),
            "/mode":        self._cmd_mode,
            "/permissions": lambda a: self._cmd_permissions(),
            "/git":         self._cmd_git,
            "/view":        self._cmd_view,
            "/create":      self._cmd_create,
            "/run":         self._cmd_run,
            "/upload":      self._cmd_upload,
            "/powershell":  self._cmd_powershell,
            "/ps":          self._cmd_ps,
            "/ssh":         self._cmd_ssh,
            "/docker":      self._cmd_docker,
        }
        h = handlers.get(c)
        if h:
            h(parts[1:])
        else:
            self._post_system(f"Unknown command: {c}  — type /help")

    def _cmd_help(self):
        lines = ["**Dabba Commands**\n"]
        lines.append("| Command | Description |")
        lines.append("|---------|-------------|")
        for cmd, desc in SLASH_COMMANDS:
            lines.append(f"| `{cmd}` | {desc} |")
        lines.append("\n**Shortcuts:** F2 switch model · F3 effort · Tab autocomplete · ↑↓ suggestions · Ctrl+L clear · Ctrl+C exit")
        self._add_message("dabba", "\n".join(lines))

    def _cmd_save(self, args):
        import json; from pathlib import Path
        path = args[0] if args else None
        default = Path(self.config.history_file).parent / f"session_{int(time.time())}.jsonl"
        save_path = Path(path) if path else default
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            history = []
            if self.agent._agent_loop:
                ctx = self.agent._agent_loop.context
                if hasattr(ctx, "messages"):
                    history = ctx.messages
            with open(save_path, "w") as f:
                for e in history:
                    f.write(json.dumps(e) + "\n")
            self._post_system(f"Saved → {save_path}")
        except Exception as exc:
            self._post_system(f"Save failed: {exc}")

    def _cmd_metrics(self):
        elapsed = int(time.time() - self._session_start)
        m, s = divmod(elapsed, 60)
        model = self.config.default_model
        effort = getattr(self.config, "effort", "medium")
        self._add_message("dabba", f"**Session stats**\n- Time: {m}m {s}s\n- Messages: {self._message_count}\n- Model: `{model}`\n- Effort: `{effort}`")

    def _cmd_effort(self, args):
        if args and args[0] in [k for k, _ in EFFORT_OPTIONS]:
            self.config.effort = args[0]
            self.config.save()
            self._update_header_effort(args[0])
            self._post_system(f"Effort → {args[0]}")
        else:
            self.action_open_effort_picker()

    def _cmd_keys(self, args):
        # /keys            → open dashboard
        # /keys set <p>    → open set-key modal for that provider directly
        # /keys delete <p> → delete without UI
        if not args or args[0] in ("show", "list"):
            self._open_keys_modal()
            return
        if args[0] == "set":
            if len(args) >= 2:
                # Jump directly to the provider's entry screen
                pid = args[1].lower()
                entry = next(((p, l, ph) for p, l, ph in _PROVIDERS if p == pid), None)
                if not entry:
                    self._post_system(f"Unknown provider: {pid}  — valid: anthropic openai google nvidia huggingface")
                    return
                p, label, ph = entry
                keys = getattr(self.config, "api_keys", {}) or {}
                def _on_result(result) -> None:
                    if result and result[0] == "saved":
                        if hasattr(self.agent, "_provider_registry"):
                            self.agent._provider_registry = None
                        self._post_system(f"Key saved for {result[1]}")
                self.push_screen(SetKeyModal(p, label, ph, keys.get(p, ""), self.config), _on_result)
            else:
                self._open_keys_modal()
            return
        if args[0] == "delete" and len(args) >= 2:
            provider = args[1].lower()
            if hasattr(self.config, "api_keys") and provider in (self.config.api_keys or {}):
                del self.config.api_keys[provider]
                self.config.save()
                if hasattr(self.agent, "_provider_registry"):
                    self.agent._provider_registry = None
                self._post_system(f"Key removed for {provider}")
            else:
                self._post_system(f"No key set for {provider}")
            return
        # Unknown sub-command → open dashboard
        self._open_keys_modal()

    def _open_keys_modal(self) -> None:
        def _on_done(result) -> None:
            if hasattr(self.agent, "_provider_registry"):
                self.agent._provider_registry = None
        self.push_screen(KeysModal(self.config), _on_done)

    def _cmd_tools(self):
        try:
            tools = self.agent._get_registry().list_tools()
            if not tools:
                self._post_system("No tools registered.")
                return
            lines = ["**Available tools**\n"]
            for t in tools:
                lines.append(f"- `{t.name}` — {t.description[:60]}")
            self._add_message("dabba", "\n".join(lines))
        except Exception as e:
            self._post_system(f"Could not list tools: {e}")

    def _cmd_mcp(self):
        """Open the MCP servers dashboard — view status, add, and remove servers."""
        try:
            self.agent._get_registry()  # ensures connect() has run at least once
        except Exception:
            pass
        self.push_screen(McpModal(self.agent))

    def _cmd_mode(self, args):
        if not args:
            self._post_system(f"Permission mode: {self.agent.permissions.mode}")
            return
        try:
            self.agent.permissions.set_mode(args[0])
            self._post_system(f"Permission mode → {args[0]}")
        except Exception as e:
            self._post_system(f"Error: {e}")

    def _cmd_permissions(self):
        try:
            s = self.agent.permissions.get_summary()
            self._add_message("dabba", f"**Permissions**\n- Mode: `{s['mode']}`\n- Allowed: {', '.join(s['session_allowed']) or 'none'}\n- Denied: {', '.join(s['session_denied']) or 'none'}")
        except Exception as e:
            self._post_system(f"Error: {e}")

    def _cmd_git(self, args):
        """Git operations: status diff log commit push."""
        if not args:
            self._post_system("Usage: /git status|diff|log|commit '<msg>'|push|branch")
            return
        subcmd = args[0].lower()
        import subprocess
        cmds = {
            "status": ["git", "status", "--short"],
            "diff":   ["git", "diff", "--stat"],
            "log":    ["git", "log", "--oneline", "-10"],
            "branch": ["git", "branch"],
            "push":   ["git", "push"],
        }
        if subcmd == "commit":
            msg = " ".join(args[1:]) if len(args) > 1 else "update"
            git_cmd = ["git", "commit", "-am", msg]
        else:
            git_cmd = cmds.get(subcmd)
            if not git_cmd:
                self._post_system(f"Unknown git subcommand: {subcmd}")
                return

        self._run_shell_cmd(git_cmd, label=f"git {subcmd}")

    def _cmd_view(self, args):
        if not args:
            self._post_system("Usage: /view <path>")
            return
        from pathlib import Path
        path = Path(args[0])
        try:
            if not path.exists():
                self._post_system(f"File not found: {path}")
                return
            content = path.read_text(errors="replace")
            lines = content.splitlines()
            preview = "\n".join(lines[:60])
            if len(lines) > 60:
                preview += f"\n… ({len(lines)} lines total)"
            ext = path.suffix.lstrip(".")
            self._add_message("dabba", f"**{path}** ({len(lines)} lines)\n\n```{ext}\n{preview}\n```")
        except Exception as e:
            self._post_system(f"Error: {e}")

    def _cmd_create(self, args):
        if not args:
            self._post_system("Usage: /create <path>")
            return
        from pathlib import Path
        path = Path(args[0])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                self._post_system(f"File already exists: {path}")
                return
            path.write_text("")
            self._post_system(f"Created: {path}")
        except Exception as e:
            self._post_system(f"Error: {e}")

    def _cmd_run(self, args):
        if not args:
            self._post_system("Usage: /run <command>")
            return
        self._run_shell_cmd(args, label=" ".join(args))

    def _cmd_upload(self, args):
        if not args:
            self.action_open_upload()
            return
        self._attach_file(" ".join(args))

    def _cmd_powershell(self, args):
        if not args:
            self._post_system("Usage: /powershell <command>")
            return
        from dabba.tools.shell_tools import execute_powershell
        command = " ".join(args)
        self._run_tool_cmd(
            lambda: execute_powershell(command),
            label=f"powershell {command}",
            render=lambda r: (r.get("stdout", "") + r.get("stderr", "")).strip() or "(no output)",
        )

    def _cmd_ps(self, args):
        from dabba.tools import process_tools

        if not args or args[0] == "list":
            procs = process_tools.list_processes()
            if not procs:
                self._post_system("No background processes.")
                return
            lines = ["**Background processes**\n"]
            for p in procs:
                lines.append(f"- `{p['process_id']}` [{p['status']}] pid={p['pid']} up={p['uptime_seconds']}s — {p['command'][:60]}")
            self._add_message("dabba", "\n".join(lines))
            return

        sub = args[0]
        if sub == "start" and len(args) > 1:
            self._run_tool_cmd(
                lambda: process_tools.start_process(" ".join(args[1:])),
                label=f"process start {' '.join(args[1:])}",
                render=lambda r: f"Started `{r['process_id']}` (pid={r['pid']}, status={r['status']})",
            )
        elif sub == "output" and len(args) > 1:
            try:
                out = process_tools.get_process_output(args[1])
                self._add_message("dabba", f"**{args[1]}** [{out['status']}]\n```\n{out['stdout']}\n{out['stderr']}\n```")
            except KeyError as e:
                self._post_system(str(e))
        elif sub == "stop" and len(args) > 1:
            self._run_tool_cmd(
                lambda: process_tools.stop_process(args[1]),
                label=f"process stop {args[1]}",
                render=lambda r: f"Stopped `{r['process_id']}` ({r['status']})",
            )
        else:
            self._post_system("Usage: /ps [list|start <cmd>|output <id>|stop <id>]")

    def _cmd_ssh(self, args):
        if len(args) < 2:
            self._post_system("Usage: /ssh <host> <command>")
            return
        host, command = args[0], " ".join(args[1:])
        from dabba.tools import ssh_tools
        self._run_tool_cmd(
            lambda: ssh_tools.ssh_exec(host, command),
            label=f"ssh {host} {command}",
            render=lambda r: (r.get("stdout", "") + r.get("stderr", "")).strip() or "(no output)",
        )

    def _cmd_docker(self, args):
        if not args:
            self._post_system("Usage: /docker ps|exec <container> <cmd>|run <image> <cmd>")
            return
        from dabba.tools import docker_tools
        sub = args[0]
        if sub == "ps":
            self._run_tool_cmd(
                lambda: docker_tools.docker_list_containers(),
                label="docker ps",
                render=lambda r: (r.get("stdout", "") + r.get("stderr", "")).strip() or "(no output)",
            )
        elif sub == "exec" and len(args) > 2:
            container, command = args[1], " ".join(args[2:])
            self._run_tool_cmd(
                lambda: docker_tools.docker_exec(container, command),
                label=f"docker exec {container} {command}",
                render=lambda r: (r.get("stdout", "") + r.get("stderr", "")).strip() or "(no output)",
            )
        elif sub == "run" and len(args) > 2:
            image, command = args[1], " ".join(args[2:])
            self._run_tool_cmd(
                lambda: docker_tools.docker_run(image, command),
                label=f"docker run {image} {command}",
                render=lambda r: (r.get("stdout", "") + r.get("stderr", "")).strip() or "(no output)",
            )
        else:
            self._post_system("Usage: /docker ps|exec <container> <cmd>|run <image> <cmd>")

    def _attach_file(self, path_str: str) -> None:
        from pathlib import Path
        path = Path(path_str.strip())
        if not path.exists():
            self._post_system(f"File not found: {path}")
            return
        if path.stat().st_size > 2 * 1024 * 1024:
            self._post_system(f"File too large (>2MB): {path}")
            return
        try:
            content = path.read_text(errors="replace")
            ext = path.suffix.lstrip(".") or "text"
            lines = content.splitlines()
            preview = "\n".join(lines[:8]) + ("\n…" if len(lines) > 8 else "")
            # Store attachment for next message
            self._pending_attachment = {"path": str(path), "content": content, "ext": ext}
            self._post_system(f"Attached: {path.name} ({len(lines)} lines) — will be included in your next message")
            # Show preview
            self._add_message("dabba", f"**{path.name}** ({len(lines)} lines)\n```{ext}\n{preview}\n```")
        except Exception as e:
            self._post_system(f"Error reading file: {e}")

    @work(thread=True)
    def _run_shell_cmd(self, cmd: list, label: str = "") -> None:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = (result.stdout + result.stderr).strip() or "(no output)"
            self.call_from_thread(self._add_message, "code", f"$ {label}\n{output}")
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._post_system, "Command timed out.")
        except FileNotFoundError:
            self.call_from_thread(self._post_system, f"Command not found: {cmd[0]}")
        except Exception as e:
            self.call_from_thread(self._post_system, f"Error: {e}")

    def _run_shell_command(self, command: str) -> None:
        """Auto-execute a detected shell command."""
        self._add_message("code", f"$ {command}")
        self._run_shell_cmd(command.split(), label=command)

    @work(thread=True)
    def _run_tool_cmd(self, coro_factory, label: str = "", render=None) -> None:
        """
        Run an async tool call (process/ssh/docker/powershell) on a fresh
        event loop in a worker thread, then post its result to the chat.

        Args:
            coro_factory: Zero-arg callable returning the coroutine to run.
            label: Shown as the "$ <label>" header of the result message.
            render: Optional callable(result_dict) -> str for custom
                formatting; defaults to pretty-printing the dict.
        """
        import json as _json
        try:
            result = asyncio.run(coro_factory())
            if render:
                output = render(result)
            else:
                output = _json.dumps(result, indent=2, default=str)
            self.call_from_thread(self._add_message, "code", f"$ {label}\n{output}")
        except PermissionError as e:
            self.call_from_thread(self._post_system, f"Denied: {e}")
        except (ValueError, KeyError, FileNotFoundError) as e:
            self.call_from_thread(self._post_system, f"Error: {e}")
        except Exception as e:
            self.call_from_thread(self._post_system, f"Unexpected error: {e}")

    # ── Agent execution ────────────────────────────────────────────────────────

    @work(thread=True)
    def _run_agent(self, user_input: str) -> None:
        self._busy = True
        self.call_from_thread(self._set_thinking, True)
        try:
            async def stream_and_collect():
                collected = ""
                first = True
                async for chunk in self.agent.stream(user_input):
                    ctype = chunk.get("type", "")
                    content = chunk.get("content", "")

                    if ctype == "text" and isinstance(content, str):
                        collected += content
                        if first:
                            self.call_from_thread(self._start_stream, collected)
                            first = False
                        else:
                            self.call_from_thread(self._update_stream, collected)
                    elif ctype == "tool_call":
                        tool_name = content.get("name", "") if isinstance(content, dict) else ""
                        self.call_from_thread(self._post_system, f"🔧 {tool_name}()")
                    elif ctype == "error":
                        self.call_from_thread(self._post_system, f"Error: {content}")

                return collected

            try:
                response = asyncio.run(stream_and_collect())
            except RuntimeError:
                ev_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(ev_loop)
                response = ev_loop.run_until_complete(stream_and_collect())

            diffs = getattr(self.agent, "_pending_diffs", None)
            if diffs:
                for d in diffs:
                    self.call_from_thread(
                        self._post_system, f"Changed `{d['path']}` — see diff above"
                    )
                diffs.clear()

            self.call_from_thread(self._finalize_stream, response or "(no response)")
        except Exception as exc:
            self.call_from_thread(self._post_system, f"Error: {exc}")
        finally:
            self._busy = False
            self.call_from_thread(self._set_thinking, False)

    def _start_stream(self, text: str) -> None:
        """Mount a streaming message placeholder."""
        try:
            scroll = self.query_one("#chat-scroll", ScrollableContainer)
            thinking = self.query_one("#thinking", ThinkingWidget)
            model = self.config.default_model
            ts = datetime.now().strftime("%H:%M")
            container = Container(classes="msg-block")
            container.id = "stream-msg"
            container.mount(Label(f"  {model}  {ts}", classes="msg-label msg-label-dabba"))
            sw = Static(text, markup=False, classes="msg-content-dabba")
            sw.id = "stream-content"
            container.mount(sw)
            scroll.mount(container, before=thinking)
            self.call_after_refresh(scroll.scroll_end, animate=True)
        except Exception:
            pass

    def _update_stream(self, text: str) -> None:
        """Update the streaming message content."""
        try:
            sw = self.query_one("#stream-content", Static)
            sw.update(text)
            self.call_after_refresh(
                self.query_one("#chat-scroll", ScrollableContainer).scroll_end, animate=True
            )
        except NoMatches:
            pass

    def _finalize_stream(self, text: str) -> None:
        """Finalize streaming."""
        try:
            sw = self.query_one("#stream-content", Static)
            sw.update(text)
        except NoMatches:
            pass
        self._set_thinking(False)
        self._update_header_status("● ready")

    # ── UI helpers ─────────────────────────────────────────────────────────────

    def _add_message(self, role: str, content: str, model_label: str = "") -> None:
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        thinking = self.query_one("#thinking", ThinkingWidget)
        scroll.mount(ChatMessage(role, content, model_label=model_label), before=thinking)
        self._message_count += 1
        self.call_after_refresh(scroll.scroll_end, animate=True)
        self._update_footer()

    def _post_system(self, text: str) -> None:
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        thinking = self.query_one("#thinking", ThinkingWidget)
        scroll.mount(Static(f"  [dim]{text}[/dim]", classes="msg-content-system"), before=thinking)
        self.call_after_refresh(scroll.scroll_end, animate=False)

    def _set_thinking(self, active: bool) -> None:
        thinking = self.query_one("#thinking", ThinkingWidget)
        if active:
            thinking.start()
            self._update_header_status("● thinking...")
        else:
            thinking.stop()
        self.call_after_refresh(
            self.query_one("#chat-scroll", ScrollableContainer).scroll_end, animate=False
        )

    def _update_header_status(self, text: str) -> None:
        try:
            self.query_one("#header-status", Label).update(text)
        except NoMatches:
            pass

    def _update_header_model(self, model_id: str) -> None:
        try:
            self.query_one("#header-model", Label).update(f"  {model_id}")
        except NoMatches:
            pass

    def _update_header_effort(self, effort: str) -> None:
        color = TIER_COLOR.get(effort, "dim")
        try:
            self.query_one("#header-effort", Label).update(f"[{color}]{effort}[/{color}]")
        except NoMatches:
            pass

    def _update_footer(self) -> None:
        elapsed = int(time.time() - self._session_start)
        m, s = divmod(elapsed, 60)
        try:
            self.query_one("#footer-session", Label).update(f"{self._message_count} msg  ·  {m}m {s}s ")
        except NoMatches:
            pass

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_quit(self) -> None:
        try:
            self.agent.close()
        except Exception:
            pass
        self.exit()

    def action_clear_chat(self) -> None:
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        thinking = self.query_one("#thinking", ThinkingWidget)
        spacer = self.query_one(ChatSpacer)
        for child in list(scroll.children):
            if child is not thinking and child is not spacer:
                child.remove()
        self.agent.reset()
        self._message_count = 0
        self._post_system("Chat cleared.")
        self._update_footer()

    def action_show_help(self) -> None:
        self._cmd_help()


# ── Entry point ────────────────────────────────────────────────────────────────

def run_tui(agent: "AgentProxy", config: "CliConfig", version: str = "1.0") -> None:
    DabbaTUI(agent=agent, config=config, version=version).run()
