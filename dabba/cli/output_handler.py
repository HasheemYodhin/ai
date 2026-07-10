"""
Rich terminal output handler for the dabba CLI agent.

Clean, Claude-style UI: minimal labels, proper markdown rendering,
subtle colors, smooth spinner, and syntax-highlighted code blocks.
"""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, List, Optional, TextIO

from dabba.cli.config import CliConfig


try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.live import Live
    from rich.text import Text
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.columns import Columns
    from rich.padding import Padding
    import rich.box as box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style as PTStyle
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False


# Color palette
_C_USER     = "bold cyan"
_C_DABBA    = "bold green"
_C_SYSTEM   = "dim white"
_C_ERROR    = "bold red"
_C_WARNING  = "bold yellow"
_C_INFO     = "dim"
_C_TOOL     = "bold blue"
_C_BORDER   = "bright_black"


@dataclass
class OutputHandler:
    """
    Handles all terminal output for the dabba CLI.

    Renders a clean, Claude-style interface using rich and prompt_toolkit.

    Args:
        config: CLI configuration.
        stream: Output stream (defaults to stdout).
        no_color: Disable colored output.
    """

    config: CliConfig = field(default_factory=CliConfig)
    stream: TextIO = field(default_factory=lambda: sys.stdout)
    no_color: bool = False
    _console: Any = field(default=None, init=False)
    _prompt_session: Any = field(default=None, init=False)
    _streaming: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if RICH_AVAILABLE and not self.no_color:
            self._console = Console(
                file=self.stream,
                highlight=False,
                markup=True,
                emoji=True,
            )
        if PROMPT_TOOLKIT_AVAILABLE and not self.no_color:
            self._prompt_session = PromptSession(
                history=InMemoryHistory(),
                style=PTStyle.from_dict({
                    "prompt": "bold ansicyan",
                    "": "ansiwhite",
                }),
                multiline=False,
                wrap_lines=True,
            )

    # ── Core print ─────────────────────────────────────────────────────────

    def _print(self, *args, **kwargs) -> None:
        if RICH_AVAILABLE and self._console:
            self._console.print(*args, **kwargs)
        else:
            print(*args, file=self.stream, **kwargs)

    def _write_plain(self, text: str, end: str = "\n") -> None:
        self.stream.write(text + end)
        self.stream.flush()

    def print(self, *args: Any, **kwargs: Any) -> None:
        self._print(*args, **kwargs)

    def write(self, text: str, style: Optional[str] = None, end: str = "\n") -> None:
        if RICH_AVAILABLE and self._console:
            if style:
                self._console.print(text, style=style, end=end)
            else:
                self._console.print(text, end=end)
        else:
            self._write_plain(text, end=end)

    # ── Welcome banner ─────────────────────────────────────────────────────

    def welcome(self, version: str = "", model: str = "", endpoint: str = "") -> None:
        if not RICH_AVAILABLE or not self._console:
            self._write_plain("Dabba AI  — type /help for commands")
            return

        self._console.print()
        # Logo row
        logo = Text()
        logo.append("  ⌘  ", style="bold cyan")
        logo.append("dabba", style="bold white")
        if version:
            logo.append(f"  v{version}", style="dim")
        self._console.print(logo)

        # Subtitle row
        sub = Text("  Your personal AI assistant", style="dim")
        self._console.print(sub)

        if model or endpoint:
            meta = Text()
            meta.append("  ")
            if model:
                meta.append(model, style="dim cyan")
            if model and endpoint:
                meta.append("  ·  ", style="dim")
            if endpoint:
                meta.append(endpoint, style="dim")
            self._console.print(meta)

        self._console.print()
        hint = Text()
        hint.append("  ", style="")
        hint.append("/help", style="dim cyan")
        hint.append(" for commands  ·  ", style="dim")
        hint.append("Ctrl+C", style="dim cyan")
        hint.append(" or ", style="dim")
        hint.append("/exit", style="dim cyan")
        hint.append(" to quit", style="dim")
        self._console.print(hint)
        self._console.print()
        self._console.print(Rule(style="bright_black"))
        self._console.print()

    # ── Message display ────────────────────────────────────────────────────

    def user_message(self, message: str) -> None:
        """Display the user's message with a subtle label."""
        if not RICH_AVAILABLE or not self._console:
            self._write_plain(f"\nyou  {message}")
            return

        self._console.print()
        label = Text()
        label.append("  you  ", style="bold cyan")
        label.append(message, style="white")
        self._console.print(label)
        self._console.print()

    def assistant_message(self, message: str) -> None:
        """Display the assistant response with markdown rendering."""
        if not RICH_AVAILABLE or not self._console:
            self._write_plain(f"\ndabba  {message}\n")
            return

        self._console.print()
        # Label
        label = Text()
        label.append("  dabba  ", style="bold green")
        self._console.print(label)
        # Render content indented
        self._render_response(message)
        self._console.print()

    def _render_response(self, text: str) -> None:
        """Render response text with markdown, indented under the label."""
        if not RICH_AVAILABLE or not self._console:
            self._write_plain(text)
            return
        # Indent each line by 2 spaces to align under the label
        md = Markdown(
            text,
            code_theme=getattr(self.config, "syntax_theme", "monokai"),
            inline_code_lexer="text",
            inline_code_theme=getattr(self.config, "syntax_theme", "monokai"),
        )
        self._console.print(Padding(md, (0, 0, 0, 2)))

    # ── Streaming ──────────────────────────────────────────────────────────

    def stream_start(self) -> None:
        """Print the 'dabba' label before streaming begins."""
        if not RICH_AVAILABLE or not self._console:
            return
        self._console.print()
        label = Text()
        label.append("  dabba  ", style="bold green")
        self._console.print(label)
        self._console.print("  ", end="")
        self._streaming = True

    def stream_token(self, token: str) -> None:
        """Print a single streaming token."""
        if RICH_AVAILABLE and self._console:
            self._console.print(token, end="", markup=False)
        else:
            self.stream.write(token)
        self.stream.flush()

    def stream_end(self) -> None:
        """Finalize streaming with a newline."""
        self._streaming = False
        self._write_plain("")
        if RICH_AVAILABLE and self._console:
            self._console.print()

    # ── Spinner ────────────────────────────────────────────────────────────

    @contextmanager
    def progress_spinner(self, message: str = "thinking..."):
        """Show a clean thinking indicator using Rich Live, cleared when done."""
        if not RICH_AVAILABLE or not self._console:
            self._write_plain(f"  dabba  {message}")
            yield
            return

        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

        def _make_spinner(i: int) -> Text:
            t = Text()
            t.append("  dabba  ", style="bold green")
            t.append(f"{frames[i % len(frames)]} {message}", style="dim")
            return t

        with Live(
            _make_spinner(0),
            console=self._console,
            transient=True,      # erased from screen when done
            refresh_per_second=12,
        ) as live:
            stop_event = threading.Event()
            idx = [0]

            def _tick():
                while not stop_event.is_set():
                    idx[0] += 1
                    live.update(_make_spinner(idx[0]))
                    time.sleep(0.08)

            t = threading.Thread(target=_tick, daemon=True)
            t.start()
            try:
                yield
            finally:
                stop_event.set()
                t.join(timeout=0.5)

    def progress_bar(self, description: str = "Progress", total: int = 100):
        """Yield a simple progress context (unused in typical chat flow)."""
        yield

    # ── Prompt input ───────────────────────────────────────────────────────

    def prompt_input(self, prompt_text: str = "> ") -> str:
        """
        Get user input with a styled prompt.

        Uses prompt_toolkit when available for history and editing.
        """
        if PROMPT_TOOLKIT_AVAILABLE and self._prompt_session and not self.no_color:
            try:
                result = self._prompt_session.prompt(
                    HTML("<bold><ansicyan>  ❯ </ansicyan></bold>"),
                )
                return result.strip()
            except (KeyboardInterrupt, EOFError):
                raise
        elif RICH_AVAILABLE and self._console:
            try:
                self._console.print("  [bold cyan]❯[/bold cyan] ", end="")
                return input()
            except (KeyboardInterrupt, EOFError):
                raise
        else:
            try:
                return input("  ❯ ")
            except (KeyboardInterrupt, EOFError):
                raise

    def confirm(self, message: str, default: bool = False) -> bool:
        """Ask for yes/no confirmation."""
        if RICH_AVAILABLE and self._console:
            default_str = "Y/n" if default else "y/N"
            self._console.print(f"  [dim]{message} [{default_str}][/dim] ", end="")
            try:
                result = input().strip().lower()
                if not result:
                    return default
                return result in ("y", "yes")
            except (KeyboardInterrupt, EOFError):
                return False
        else:
            try:
                result = input(f"  {message} [y/N]: ").strip().lower()
                return result in ("y", "yes")
            except (KeyboardInterrupt, EOFError):
                return False

    # ── Status messages ────────────────────────────────────────────────────

    def error(self, message: str) -> None:
        if RICH_AVAILABLE and self._console:
            self._console.print(f"  [bold red]✗[/bold red]  {message}")
        else:
            self._write_plain(f"  ✗  {message}")

    def warning(self, message: str) -> None:
        if RICH_AVAILABLE and self._console:
            self._console.print(f"  [bold yellow]![/bold yellow]  {message}", style="yellow")
        else:
            self._write_plain(f"  !  {message}")

    def info(self, message: str) -> None:
        if RICH_AVAILABLE and self._console:
            self._console.print(f"  [dim]{message}[/dim]")
        else:
            self._write_plain(f"  {message}")

    def system_message(self, message: str) -> None:
        if RICH_AVAILABLE and self._console:
            self._console.print(f"  [dim italic]{message}[/dim italic]")
        else:
            self._write_plain(f"  {message}")

    # ── Tool calls ─────────────────────────────────────────────────────────

    def tool_message(self, tool_name: str, status: str, detail: str = "") -> None:
        if not RICH_AVAILABLE or not self._console:
            self._write_plain(f"  [{tool_name}] {detail}")
            return
        icons = {"start": "⟳", "success": "✓", "error": "✗"}
        styles = {"start": "dim blue", "success": "dim green", "error": "dim red"}
        icon = icons.get(status, "·")
        style = styles.get(status, "dim")
        detail_str = f"  {detail[:80]}" if detail else ""
        self._console.print(
            f"  [dim]↳[/dim] [{style}]{icon} {tool_name}[/{style}][dim]{detail_str}[/dim]"
        )

    # ── Utility ────────────────────────────────────────────────────────────

    def markdown(self, text: str) -> None:
        """Render markdown text."""
        if RICH_AVAILABLE and self._console:
            md = Markdown(text, code_theme=getattr(self.config, "syntax_theme", "monokai"))
            self._console.print(Padding(md, (0, 0, 0, 2)))
        else:
            self._write_plain(text)

    def code_block(self, code: str, language: str = "", title: Optional[str] = None) -> None:
        if RICH_AVAILABLE and self._console:
            try:
                syntax = Syntax(
                    code,
                    language or "text",
                    theme=getattr(self.config, "syntax_theme", "monokai"),
                    line_numbers=True,
                    padding=1,
                )
                if title:
                    self._console.print(Panel(syntax, title=title, border_style="bright_black"))
                else:
                    self._console.print(Panel(syntax, border_style="bright_black"))
            except Exception:
                self._write_plain(f"```{language}\n{code}\n```")
        else:
            self._write_plain(f"```{language}\n{code}\n```")

    def table(self, headers: List[str], rows: List[List[str]]) -> None:
        if RICH_AVAILABLE and self._console:
            t = Table(
                show_header=True,
                header_style="bold dim",
                border_style="bright_black",
                box=box.SIMPLE,
                padding=(0, 1),
            )
            for h in headers:
                t.add_column(h)
            for row in rows:
                t.add_row(*[str(c) for c in row])
            self._console.print(Padding(t, (0, 0, 0, 2)))
        else:
            col_w = [max(len(h), max((len(str(r[i])) for r in rows), default=0)) for i, h in enumerate(headers)]
            self._write_plain("  " + " │ ".join(h.ljust(w) for h, w in zip(headers, col_w)))
            self._write_plain("  " + "─┼─".join("─" * w for w in col_w))
            for row in rows:
                self._write_plain("  " + " │ ".join(str(c).ljust(w) for c, w in zip(row, col_w)))

    def divider(self, char: str = "─", length: int = 60) -> None:
        if RICH_AVAILABLE and self._console:
            self._console.print(Rule(style="bright_black"))
        else:
            self._write_plain(char * length)

    def token_usage(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost: Optional[float] = None,
    ) -> None:
        if total_tokens:
            if RICH_AVAILABLE and self._console:
                self._console.print(f"  [dim]{total_tokens} tokens[/dim]")
            else:
                self._write_plain(f"  {total_tokens} tokens")

    def diff_display(self, diff_text: str) -> None:
        if not RICH_AVAILABLE or not self._console:
            self._write_plain(diff_text)
            return
        for line in diff_text.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                self._console.print(f"  {line}", style="green")
            elif line.startswith("-") and not line.startswith("---"):
                self._console.print(f"  {line}", style="red")
            elif line.startswith("@@"):
                self._console.print(f"  {line}", style="cyan")
            else:
                self._console.print(f"  {line}", style="dim")
