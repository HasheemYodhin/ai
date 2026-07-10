"""
File change monitoring for the dabba CLI agent.

Watches workspace files for changes, auto-reads files when mentioned,
and gathers context. Uses watchdog for efficient monitoring with a
polling fallback.
"""

from __future__ import annotations

import os
import time
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set


def _get_logger():
    """Lazy logger to avoid importing torch through dabba.utils."""
    from dabba.utils.logging import get_logger
    return get_logger("dabba.cli.file_watcher")


_HAS_WATCHDOG = False
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent

    _HAS_WATCHDOG = True
except ImportError:
    pass


class FileWatcher:
    """
    Monitors files in the workspace for changes and triggers callbacks.

    Uses watchdog when available for efficient file system monitoring,
    with a polling-based fallback for environments without watchdog.

    Args:
        workspace_root: Root directory to watch.
        extensions: File extensions to monitor (e.g., {".py", ".md"}).
        callback: Optional callable invoked as callback(path, event_type).
        poll_interval: Polling interval in seconds (fallback only).
        auto_read_on_change: If True, read file content when it changes.
    """

    def __init__(
        self,
        workspace_root: str = ".",
        extensions: Optional[Set[str]] = None,
        callback: Optional[Callable[[str, str], None]] = None,
        poll_interval: float = 1.0,
        auto_read_on_change: bool = False,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.extensions = extensions or {
            ".py", ".js", ".ts", ".rs", ".go", ".md", ".txt",
            ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini",
            ".html", ".css", ".scss", ".less", ".vue", ".svelte",
            ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".swift",
        }
        self.callback = callback
        self.poll_interval = poll_interval
        self.auto_read_on_change = auto_read_on_change

        self._observer: Optional[object] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._running = False
        self._file_snapshots: Dict[str, float] = {}
        self._watched_paths: Set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start watching files. Uses watchdog or polling fallback."""
        if self._running:
            return
        self._running = True

        if _HAS_WATCHDOG:
            self._start_watchdog()
            _get_logger().info("File watcher started (watchdog)")
        else:
            self._start_polling()
            _get_logger().info("File watcher started (polling fallback)")

    def _start_watchdog(self) -> None:
        """Start watchdog-based file monitoring."""

        class ChangeHandler(FileSystemEventHandler):
            def __init__(self, watcher: FileWatcher):
                self.watcher = watcher

            def on_modified(self, event: FileModifiedEvent):
                if not event.is_directory:
                    path = Path(event.src_path)
                    if path.suffix in self.watcher.extensions:
                        self.watcher._notify(str(path), "modified")

        self._observer = Observer()
        self._observer.schedule(
            ChangeHandler(self),
            str(self.workspace_root),
            recursive=True,
        )
        self._observer.start()

    def _start_polling(self) -> None:
        """Start polling-based file monitoring."""
        self._take_snapshot()

        def poll_loop():
            while self._running:
                self._check_changes()
                time.sleep(self.poll_interval)

        self._poll_thread = threading.Thread(target=poll_loop, daemon=True)
        self._poll_thread.start()

    def _take_snapshot(self) -> None:
        """Record current modification times for watched files."""
        self._file_snapshots.clear()
        for path in self.workspace_root.rglob("*"):
            if path.is_file() and path.suffix in self.extensions:
                try:
                    self._file_snapshots[str(path)] = path.stat().st_mtime
                except OSError:
                    continue

    def _check_changes(self) -> None:
        """Poll for file changes by comparing modification times."""
        try:
            for path in self.workspace_root.rglob("*"):
                if not path.is_file() or path.suffix not in self.extensions:
                    continue
                str_path = str(path)
                try:
                    current_mtime = path.stat().st_mtime
                    prev_mtime = self._file_snapshots.get(str_path)
                    if prev_mtime is not None and current_mtime > prev_mtime:
                        self._file_snapshots[str_path] = current_mtime
                        self._notify(str_path, "modified")
                    elif prev_mtime is None:
                        self._file_snapshots[str_path] = current_mtime
                except OSError:
                    continue
        except Exception as exc:
            _get_logger().debug("Polling check error: %s", exc)

    def _notify(self, path: str, event_type: str) -> None:
        """
        Notify the callback of a file change.

        Args:
            path: Path to the changed file.
            event_type: Type of event ("modified", "created", "deleted").
        """
        with self._lock:
            self._watched_paths.add(path)
        if self.callback:
            try:
                self.callback(path, event_type)
            except Exception as exc:
                _get_logger().error("File watcher callback error: %s", exc)

    def watch_path(self, path: str) -> None:
        """
        Explicitly add a path for monitoring.

        Args:
            path: File path to watch.
        """
        with self._lock:
            self._watched_paths.add(path)

    def unwatch_path(self, path: str) -> None:
        """
        Remove a path from monitoring.

        Args:
            path: File path to stop watching.
        """
        with self._lock:
            self._watched_paths.discard(path)

    def get_changed_files(self) -> List[str]:
        """
        Get list of files that have changed since last check.

        Returns:
            List of changed file paths.
        """
        with self._lock:
            changed = list(self._watched_paths)
            self._watched_paths.clear()
        return changed

    def read_file_content(self, path: str) -> Optional[str]:
        """
        Read the content of a file.

        Args:
            path: File path to read.

        Returns:
            File content as string, or None if unreadable.
        """
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError as exc:
            _get_logger().warning("Cannot read file '%s': %s", path, exc)
            return None

    def gather_context(self, max_files: int = 20, max_size: int = 4096) -> str:
        """
        Gather context from workspace files.

        Reads recently changed or relevant files to build context
        for the agent.

        Args:
            max_files: Maximum number of files to include.
            max_size: Maximum characters per file.

        Returns:
            Concatenated file contents with headers.
        """
        context_parts = []
        count = 0

        for path in self.workspace_root.rglob("*"):
            if not path.is_file() or path.suffix not in self.extensions:
                continue
            if count >= max_files:
                break
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:max_size]
                rel_path = path.relative_to(self.workspace_root)
                context_parts.append(f"# File: {rel_path}\n```\n{content}\n```\n")
                count += 1
            except OSError:
                continue

        return "\n".join(context_parts)

    def stop(self) -> None:
        """Stop file monitoring."""
        self._running = False
        if self._observer is not None and _HAS_WATCHDOG:
            self._observer.stop()
            self._observer.join()
        self._observer = None
        self._poll_thread = None
        _get_logger().info("File watcher stopped")
