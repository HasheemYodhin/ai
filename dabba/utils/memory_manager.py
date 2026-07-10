"""
Persistent memory manager for the dabba agent.

Stores user-defined facts (memories) across sessions and workspaces.
Memories are saved to disk and automatically injected into every agent
prompt so the AI always has access to your preferences and project context.

Storage: ~/.config/dabba/memories.json  (Linux/Mac)
         %APPDATA%/dabba/memories.json   (Windows)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from dabba.utils.logging import get_logger

logger = get_logger("dabba.utils.memory_manager")


def _default_memory_path() -> Path:
    """Return the platform-appropriate path for memories.json."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "dabba" / "memories.json"


class MemoryManager:
    """
    Manages a list of persistent facts (memories) for the dabba agent.

    Each memory is a dict:
        {
            "fact":       str,    # the stored fact
            "created_at": float,  # Unix timestamp
        }

    Args:
        path: Path to the JSON file. Defaults to the platform config dir.
    """

    MAX_MEMORIES = 50  # hard cap so the context block stays sane

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else _default_memory_path()
        self._memories: List[Dict[str, object]] = []
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load memories from disk. Silently starts fresh on any error."""
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, list):
                    self._memories = [
                        m for m in data
                        if isinstance(m, dict) and "fact" in m
                    ]
                    logger.info("Loaded %d memories from %s", len(self._memories), self._path)
        except Exception as exc:
            logger.warning("Could not load memories from %s: %s", self._path, exc)
            self._memories = []

    def _save(self) -> None:
        """Persist memories to disk. Silently ignores write errors."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._memories, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Could not save memories to %s: %s", self._path, exc)

    # ── Public API ───────────────────────────────────────────────────────────

    def add(self, fact: str) -> Dict[str, object]:
        """
        Add a new memory.

        Args:
            fact: The fact to remember (must be non-empty).

        Returns:
            The created memory dict.

        Raises:
            ValueError: If fact is empty or duplicate.
        """
        fact = fact.strip()
        if not fact:
            raise ValueError("Memory fact cannot be empty.")

        # Deduplicate — ignore case and minor whitespace differences
        normalized = fact.lower()
        for m in self._memories:
            if str(m.get("fact", "")).lower() == normalized:
                raise ValueError(f"Already remembered: '{fact}'")

        if len(self._memories) >= self.MAX_MEMORIES:
            # Drop the oldest to make room
            self._memories.pop(0)

        entry: Dict[str, object] = {
            "fact": fact,
            "created_at": time.time(),
        }
        self._memories.append(entry)
        self._save()
        logger.info("Memory added: %s", fact[:60])
        return entry

    def list(self) -> List[Dict[str, object]]:
        """Return all stored memories (most-recently added last)."""
        return list(self._memories)

    def remove_by_index(self, index: int) -> Optional[str]:
        """
        Remove a memory by its 1-based display index.

        Args:
            index: 1-based position in the list() output.

        Returns:
            The removed fact string, or None if index is out of range.
        """
        zero_based = index - 1
        if 0 <= zero_based < len(self._memories):
            removed = self._memories.pop(zero_based)
            self._save()
            fact = str(removed.get("fact", ""))
            logger.info("Memory removed by index %d: %s", index, fact[:60])
            return fact
        return None

    def remove_by_text(self, text: str) -> Optional[str]:
        """
        Remove the first memory whose fact contains *text* (case-insensitive).

        Args:
            text: Substring to search for.

        Returns:
            The removed fact string, or None if not found.
        """
        text_lower = text.strip().lower()
        for i, m in enumerate(self._memories):
            if text_lower in str(m.get("fact", "")).lower():
                removed = self._memories.pop(i)
                self._save()
                fact = str(removed.get("fact", ""))
                logger.info("Memory removed by text '%s': %s", text[:30], fact[:60])
                return fact
        return None

    def clear(self) -> int:
        """
        Remove all memories.

        Returns:
            The number of memories that were cleared.
        """
        count = len(self._memories)
        self._memories = []
        self._save()
        logger.info("All %d memories cleared", count)
        return count

    def get_context_string(self) -> str:
        """
        Build the memory context block for injection into agent prompts.

        Returns an empty string when there are no memories so callers can
        use a simple ``if block:`` guard without special-casing None.
        """
        if not self._memories:
            return ""

        lines = ["[Memories — facts you asked dabba to remember:]"]
        for i, m in enumerate(self._memories, 1):
            lines.append(f"  {i}. {m['fact']}")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._memories)

    def __repr__(self) -> str:
        return f"MemoryManager(path={self._path!r}, count={len(self._memories)})"


# Module-level singleton — one shared instance for the whole server process.
_instance: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Return (or create) the shared MemoryManager singleton."""
    global _instance
    if _instance is None:
        _instance = MemoryManager()
    return _instance
