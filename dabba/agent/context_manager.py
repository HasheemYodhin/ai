"""
Context window management for the dabba agent system.

Tracks token usage in the context window, manages conversation history,
and applies truncation strategies to stay within limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from dabba.utils.logging import get_logger

logger = get_logger("dabba.agent.context_manager")


TokenCounterFn = Callable[[str], int]


@dataclass
class ConversationEntry:
    """
    A single entry in the conversation history.

    Args:
        role: One of "system", "user", "assistant", "tool".
        content: Text content of the message.
        token_count: Estimated or actual token count.
        metadata: Optional additional data (tool calls, timestamps, etc.).
    """

    role: str
    content: str
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContextManager:
    """
    Manages the conversation context window for an LLM agent.

    Tracks token usage, provides truncation strategies, and
    maintains conversation history.

    Args:
        max_context_length: Maximum total tokens allowed in context.
        truncation_strategy: One of "summarize", "drop_oldest", or "drop_system".
        token_counter: Optional callable that returns token count for a string.
            Defaults to a simple whitespace split estimator.
    """

    def __init__(
        self,
        max_context_length: int = 128_000,
        truncation_strategy: str = "summarize",
        token_counter: Optional[TokenCounterFn] = None,
        max_history: Optional[int] = None,
        system_prompt: Optional[str] = None,
        token_limit: Optional[int] = None,
    ):
        self.max_context_length = max_context_length
        self.truncation_strategy = truncation_strategy
        self._token_counter = token_counter or self._default_token_counter
        self._entries: List[ConversationEntry] = []
        self._system_prompt: Optional[str] = system_prompt
        self._system_token_count: int = 0
        self._total_tokens: int = 0
        self._truncation_count: int = 0
        self.max_history = max_history
        self.token_limit = token_limit

    @staticmethod
    def _default_token_counter(text: str) -> int:
        """
        Estimate token count by splitting on whitespace.

        This is a rough approximation (~1.3 tokens per word).
        For production, use a proper tokenizer.

        Args:
            text: Text to count tokens for.

        Returns:
            Estimated token count.
        """
        return max(1, int(len(text.split()) * 1.3))

    @property
    def total_tokens(self) -> int:
        """Total number of tokens currently in the context."""
        return self._total_tokens

    @property
    def entry_count(self) -> int:
        """Number of conversation entries."""
        return len(self._entries)

    @property
    def available_tokens(self) -> int:
        """Number of tokens still available before hitting the limit."""
        return max(0, self.max_context_length - self._total_tokens)

    @property
    def usage_ratio(self) -> float:
        """Fraction (0.0-1.0) of the context window currently used."""
        if self.max_context_length == 0:
            return 0.0
        return self._total_tokens / self.max_context_length

    @property
    def history(self) -> List[Dict[str, Any]]:
        """Conversation history as a list of role/content dicts (excludes system prompt)."""
        entries = self._entries
        if self.max_history is not None:
            entries = entries[-self.max_history:]
        return [{"role": e.role, "content": e.content} for e in entries]

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the history, enforcing max_history and token_limit."""
        self.add_entry(role, content)
        if self.max_history is not None:
            while len(self._entries) > self.max_history:
                removed = self._entries.pop(0)
                self._total_tokens -= removed.token_count
        if self.token_limit is not None:
            while self._entries and self._total_tokens > self.token_limit:
                removed = self._entries.pop(0)
                self._total_tokens -= removed.token_count
                if self._total_tokens < 0:
                    self._total_tokens = 0

    def get_context(self) -> List[Dict[str, Any]]:
        """Return full message list (with system prompt first if set)."""
        return self.get_messages()

    def token_count(self) -> int:
        """Return total estimated token count of all messages."""
        return self._total_tokens

    def set_system_prompt(self, prompt: str) -> None:
        """
        Set or update the system prompt.

        This is always kept at the beginning of context.

        Args:
            prompt: System prompt text.
        """
        self._system_prompt = prompt
        self._system_token_count = self._token_counter(prompt)
        self._total_tokens = self._system_token_count + sum(
            e.token_count for e in self._entries
        )

    def add_entry(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationEntry:
        """
        Add a new entry to the conversation history.

        Automatically triggers truncation if the context is full.

        Args:
            role: Message role ("user", "assistant", "tool", "system").
            content: Message content.
            metadata: Optional metadata dictionary.

        Returns:
            The created ConversationEntry.
        """
        token_count = self._token_counter(content)
        entry = ConversationEntry(
            role=role,
            content=content,
            token_count=token_count,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        self._total_tokens += token_count

        if self._total_tokens > self.max_context_length:
            self._truncate()

        return entry

    def get_messages(self) -> List[Dict[str, Any]]:
        """
        Get the conversation as a list of message dicts for an LLM API.

        Returns:
            List of dicts with "role" and "content" keys.
            Includes the system prompt as the first message if set.
        """
        messages: List[Dict[str, Any]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        for entry in self._entries:
            msg: Dict[str, Any] = {"role": entry.role, "content": entry.content}
            if entry.role == "tool":
                msg["tool_call_id"] = entry.metadata.get("call_id", "")
            messages.append(msg)
        return messages

    def get_history(
        self,
        max_entries: Optional[int] = None,
    ) -> List[ConversationEntry]:
        """
        Get raw conversation history entries.

        Args:
            max_entries: Maximum number of entries to return.

        Returns:
            List of ConversationEntry instances.
        """
        if max_entries is not None:
            return self._entries[-max_entries:]
        return list(self._entries)

    def clear(self) -> None:
        """Clear all conversation entries (keeps system prompt)."""
        self._entries.clear()
        self._total_tokens = self._system_token_count
        self._truncation_count = 0

    def reset(self) -> None:
        """Reset everything including the system prompt."""
        self._entries.clear()
        self._system_prompt = None
        self._system_token_count = 0
        self._total_tokens = 0
        self._truncation_count = 0

    def _truncate(self) -> None:
        """
        Apply the configured truncation strategy to reduce context size.

        Raises:
            ValueError: If truncation strategy is unknown.
        """
        self._truncation_count += 1
        strategy_map = {
            "summarize": self._truncate_by_summarizing,
            "drop_oldest": self._truncate_by_dropping_oldest,
            "drop_system": self._truncate_by_dropping_system,
        }
        strategy = strategy_map.get(self.truncation_strategy)
        if strategy is None:
            logger.warning(
                "Unknown truncation strategy '%s', using 'drop_oldest'",
                self.truncation_strategy,
            )
            self._truncate_by_dropping_oldest()
        else:
            strategy()

    def _truncate_by_dropping_oldest(self) -> None:
        """
        Remove the oldest non-system entries until under the limit.

        Preserves the most recent entries.
        """
        original_count = len(self._entries)
        while (
            self._total_tokens > self.max_context_length * 0.9
            and self._entries
        ):
            removed = self._entries.pop(0)
            self._total_tokens -= removed.token_count
            if self._total_tokens < 0:
                self._total_tokens = 0

        dropped = original_count - len(self._entries)
        if dropped > 0:
            logger.info(
                "Truncation (drop_oldest): removed %d entries, "
                "total tokens now %d/%d",
                dropped,
                self._total_tokens,
                self.max_context_length,
            )

    def _truncate_by_dropping_system(self) -> None:
        """
        Reduce the system prompt or remove it if needed.

        Drops the system prompt to free up space.
        """
        if self._system_prompt:
            logger.info(
                "Truncation (drop_system): removing system prompt "
                "(%d tokens)", self._system_token_count
            )
            self._total_tokens -= self._system_token_count
            self._system_prompt = None
            self._system_token_count = 0

        if self._total_tokens > self.max_context_length * 0.9:
            self._truncate_by_dropping_oldest()

    def _truncate_by_summarizing(self) -> None:
        """
        Summarize older entries to reduce token usage.

        Replaces the oldest half of entries with a single "summary"
        entry. The actual summarization should be done externally;
        this method just marks entries for summarization.
        """
        if len(self._entries) < 4:
            self._truncate_by_dropping_oldest()
            return

        mid = len(self._entries) // 2
        old_entries = self._entries[:mid]
        new_entries = self._entries[mid:]

        old_tokens = sum(e.token_count for e in old_entries)
        summary_text = (
            f"[Summary of {len(old_entries)} previous messages "
            f"({old_tokens} tokens)]"
        )
        summary_tokens = self._token_counter(summary_text)

        summary_entry = ConversationEntry(
            role="assistant",
            content=summary_text,
            token_count=summary_tokens,
            metadata={"type": "summary", "compressed_tokens": old_tokens - summary_tokens},
        )

        self._entries = [summary_entry] + new_entries
        self._total_tokens = (
            self._system_token_count
            + summary_tokens
            + sum(e.token_count for e in new_entries)
        )

        logger.info(
            "Truncation (summarize): compressed %d entries (%d tokens) "
            "into summary (%d tokens). Total now %d/%d",
            len(old_entries),
            old_tokens,
            summary_tokens,
            self._total_tokens,
            self.max_context_length,
        )

    def serialize(self) -> Dict[str, Any]:
        """
        Serialize the conversation state for persistence.

        Returns:
            Dictionary with system prompt, entries, and config.
        """
        return {
            "system_prompt": self._system_prompt,
            "max_context_length": self.max_context_length,
            "truncation_strategy": self.truncation_strategy,
            "entries": [
                {
                    "role": e.role,
                    "content": e.content,
                    "token_count": e.token_count,
                    "metadata": e.metadata,
                }
                for e in self._entries
            ],
            "truncation_count": self._truncation_count,
        }

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> ContextManager:
        """
        Restore a ContextManager from serialized state.

        Args:
            data: Serialized state from serialize().

        Returns:
            Restored ContextManager instance.
        """
        cm = cls(
            max_context_length=data.get("max_context_length", 128_000),
            truncation_strategy=data.get("truncation_strategy", "summarize"),
        )
        cm._system_prompt = data.get("system_prompt")
        cm._system_token_count = (
            cm._token_counter(cm._system_prompt) if cm._system_prompt else 0
        )
        cm._entries = [
            ConversationEntry(
                role=e["role"],
                content=e["content"],
                token_count=e.get("token_count", 0),
                metadata=e.get("metadata", {}),
            )
            for e in data.get("entries", [])
        ]
        cm._total_tokens = cm._system_token_count + sum(
            e.token_count for e in cm._entries
        )
        cm._truncation_count = data.get("truncation_count", 0)
        return cm
