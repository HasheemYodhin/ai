from __future__ import annotations
import json as _json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TIERS = ["low", "medium", "high", "xhigh", "max"]

EFFORT_PARAMS: Dict[str, Dict] = {
    "low":    {"max_tokens": 1024,  "temperature": 1.0},
    "medium": {"max_tokens": 4096,  "temperature": 0.7},
    "high":   {"max_tokens": 8192,  "temperature": 0.3},
    "xhigh":  {"max_tokens": 16384, "temperature": 0.1},
    "max":    {"max_tokens": 32768, "temperature": 0.0},
}

TIER_LABELS: Dict[str, str] = {
    "low":   "low   ",
    "medium":"medium",
    "high":  "high  ",
    "xhigh": "xhigh ",
    "max":   "max   ",
}


@dataclass
class ModelInfo:
    id: str
    name: str
    provider: str
    tier: str               # recommended tier
    description: str
    context_window: int = 8192
    cost_input: float = 0.0   # USD per 1M tokens
    cost_output: float = 0.0
    supports_thinking: bool = False
    requires_key: bool = True


class BaseProvider(ABC):
    name: str = ""

    @abstractmethod
    def chat(
        self,
        messages: List[Dict],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs,
    ) -> str: ...

    @abstractmethod
    def list_models(self) -> List[ModelInfo]: ...

    @property
    def is_available(self) -> bool:
        return True

    def get_api_key(self, config) -> Optional[str]:
        return config.api_keys.get(self.name, "")


# ── Native function-calling adapters ────────────────────────────────────────
#
# dabba's agent loop (dabba/agent/agent_loop.py + mcp_handler.py) only knows
# how to parse a model's INTENT to call a tool via a prompted
# "<tool_call>{json}</tool_call>" text convention — it has no concept of a
# provider's native tool-calling API. Rather than teach the whole pipeline
# two representations, providers that support native function-calling
# (openai_provider.py, anthropic_provider.py) use these helpers to:
#   1. convert dabba's plain tool_dicts into the provider's native schema,
#   2. convert whatever native tool call the model actually made back into
#      the SAME <tool_call> tag text McpHandler.parse_tool_calls already
#      understands, and append it to the returned string.
# This makes tool-calling reliable (native APIs are far more likely to
# produce a real function call than a prompted text convention) while
# keeping agent_loop.py/mcp_handler.py/context_manager.py completely
# unchanged — from their point of view, nothing about the response shape
# is any different than a model that emitted the tag on its own.

def tools_to_openai_schema(tool_dicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert dabba's tool dicts (name/description/parameters) to OpenAI's tools= schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for t in tool_dicts
    ]


def openai_tool_calls_to_tags(message: Any) -> str:
    """
    Convert an OpenAI ChatCompletionMessage's native `.tool_calls` (if any)
    into dabba's `<tool_call>{json}</tool_call>` tag text.

    Returns "" if the message made no tool calls.
    """
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return ""
    blocks = []
    for tc in tool_calls:
        try:
            args = _json.loads(tc.function.arguments) if tc.function.arguments else {}
        except (ValueError, TypeError):
            args = {}
        payload = {"name": tc.function.name, "arguments": args, "call_id": tc.id}
        blocks.append(f"<tool_call>\n{_json.dumps(payload)}\n</tool_call>")
    return "\n".join(blocks)


def tools_to_anthropic_schema(tool_dicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert dabba's tool dicts (name/description/parameters) to Anthropic's tools= schema."""
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
        }
        for t in tool_dicts
    ]


def anthropic_tool_use_to_tags(content_blocks: Any) -> str:
    """
    Convert Anthropic's native `tool_use` content blocks (if any) into
    dabba's `<tool_call>{json}</tool_call>` tag text.

    Returns "" if no block has type "tool_use".
    """
    blocks = []
    for b in content_blocks:
        if getattr(b, "type", None) == "tool_use":
            payload = {"name": b.name, "arguments": b.input, "call_id": b.id}
            blocks.append(f"<tool_call>\n{_json.dumps(payload)}\n</tool_call>")
    return "\n".join(blocks)


def remap_tool_role_for_provider(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rewrite any {"role": "tool", ...} message into {"role": "user", ...}
    with a "[Tool Result]" marker, dropping tool_call_id.

    dabba/agent/context_manager.py emits role="tool" for every tool-result
    entry (see ContextManager.get_messages), but:
      - Anthropic's API only accepts "user"/"assistant" roles — a literal
        "tool" role is rejected outright.
      - OpenAI's API DOES have a "tool" role, but requires it to carry a
        tool_call_id that matches a tool_calls entry on the IMMEDIATELY
        PRECEDING assistant message — a pairing dabba's flat
        one-blob-per-step result format (mcp_handler.format_results) doesn't
        preserve, since the assistant history is stored as plain stripped
        text, not the native tool_calls structure.
    Remapping to "user" sidesteps both issues without needing to restructure
    context_manager's storage format or the rest of the agent loop.
    """
    remapped = []
    for m in messages:
        if m.get("role") == "tool":
            remapped.append({"role": "user", "content": f"[Tool Result]\n{m.get('content', '')}"})
        else:
            remapped.append(m)
    return remapped
