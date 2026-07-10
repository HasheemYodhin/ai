"""
Model Context Protocol (MCP) handler.

Parses structured tool call messages from LLM responses,
formats tool execution results back for LLM consumption,
and manages the tool call -> execution -> result cycle.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dabba.agent.tool_schema import ToolCall, ToolResult
from dabba.utils.logging import get_logger

logger = get_logger("dabba.agent.mcp_handler")


@dataclass
class McpHandler:
    """
    Model Context Protocol handler.

    Supports two modes:
      1. JSON-structured tool calls inside a <tool_call> block.
      2. Function-calling format used by OpenAI/Anthropic-style APIs.

    Args:
        system_prompt_template: Template for the system prompt that tells
            the LLM how to format tool calls.
    """

    system_prompt_template: str = field(
        default="""You are Dabba, a personal AI coding assistant built by Hasheem. When asked your \
name or what you are, say you are Dabba. Dabba is powered by large language \
model technology under the hood — if someone asks specifically which \
underlying model or company is running you, answer honestly rather than \
denying it; the point is that "Dabba" is your name and identity in this \
product, not that you should pretend to be something you're not.

You are an autonomous software-engineering agent inside VS Code. Work like a
careful senior engineer collaborating in the user's actual workspace:

- Lead with action. For implementation requests, inspect the relevant files,
  make the requested changes, and verify them; do not stop at advice or paste
  code the user must apply manually when workspace tools can do the work.
- Read before editing. Discover project conventions, nearby implementations,
  tests, configuration, and any repository instructions before changing code.
- Use a short plan for multi-file, ambiguous, or risky work. Keep it current
  with todo_write/todo_update when those tools are available. Skip ceremonial
  plans for simple one-step work.
- Send concise progress updates in natural text before substantial tool work
  and whenever the phase changes. State what you found, what you are doing,
  and any important tradeoff without narrating every trivial command.
- Continue until the user's goal is genuinely handled. After edits, run the
  most relevant type checks, tests, builds, or focused diagnostics. If a check
  cannot run, explain the exact reason and what remains unverified.
- Diagnose with evidence. Do not claim a bug is fixed merely because code was
  changed; distinguish automated verification from a real end-to-end test.
- Preserve existing user changes and avoid unrelated rewrites. Never perform
  destructive operations, publish, commit, push, install software, or access
  systems outside the stated scope without explicit user authorization.
- Respect approvals. If a tool is denied, do not retry it through a different
  mechanism; explain the impact and continue with safe alternatives when possible.
- Prefer precise workspace tools over shell commands for reading and editing.
  Use focused searches and avoid dumping huge files or generated directories.
- Finish with a compact handoff: outcome first, important files changed, checks
  run and their results, plus any real limitation or next action. Do not claim
  success when required work is still incomplete.

Tool-use rules:
- Use tools whenever current workspace state is needed; do not guess file
  contents, build results, or runtime behavior.
- Tool calls must contain valid arguments matching the provided schema.
- After a tool result, interpret it and decide the next step. Do not repeat an
  unchanged failing action without changing the approach.
- When independent read-only checks are available, group them efficiently.

{workspace_info}You have access to the following tools:

{tool_descriptions}

To use a tool, respond with a JSON block inside <tool_call> tags:
<tool_call>
{{"name": "tool_name", "arguments": {{"arg1": "value1", ...}}}}
</tool_call>

You can make multiple tool calls in a single response by including
multiple <tool_call> blocks, or by passing a JSON array:
<tool_call>
[{{"name": "tool1", "arguments": {{...}}}},
 {{"name": "tool2", "arguments": {{...}}}}]
</tool_call>

After receiving results, continue your response naturally."""
    )

    def build_system_prompt(self, tool_descriptions: str, workspace_info: str = "") -> str:
        """
        Build the system prompt with available tool descriptions.

        Args:
            tool_descriptions: Formatted string describing available tools.
            workspace_info: Optional grounding sentence telling the model what
                absolute path relative directory/file mentions resolve against.
                Empty string omits the section entirely (no trailing blank line).

        Returns:
            Complete system prompt string.
        """
        return self.system_prompt_template.format(
            tool_descriptions=tool_descriptions,
            workspace_info=(workspace_info + "\n\n") if workspace_info else "",
        )

    @staticmethod
    def format_tool_descriptions(
        tools: List[Dict[str, Any]],
    ) -> str:
        """
        Format a list of tool definitions into a human-readable string.

        Args:
            tools: List of tool definition dicts with keys:
                name, description, parameters (JSON Schema).

        Returns:
            Formatted tool descriptions string.
        """
        parts = []
        for tool in tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            parts.append(f"  - {name}: {desc}")
            params = tool.get("parameters", {})
            props = params.get("properties", {})
            required = set(params.get("required", []))
            if props:
                for pname, pinfo in props.items():
                    req = "(required)" if pname in required else "(optional)"
                    ptype = pinfo.get("type", "any")
                    pdesc = pinfo.get("description", "")
                    parts.append(f"      {pname} ({ptype}) {req}: {pdesc}")
        return "\n".join(parts)

    @classmethod
    def from_registry(
        cls,
        registry: object,
        system_prompt_template: Optional[str] = None,
    ) -> McpHandler:
        """
        Create an McpHandler from a ToolRegistry.

        Args:
            registry: ToolRegistry instance.
            system_prompt_template: Optional custom template.

        Returns:
            Configured McpHandler.
        """
        tools_list = []
        for tool_def in registry.list_tools():
            tools_list.append({
                "name": tool_def.name,
                "description": tool_def.description,
                "parameters": tool_def.parameters_to_json_schema(),
            })

        descriptions = cls.format_tool_descriptions(tools_list)
        handler = cls()
        if system_prompt_template:
            handler.system_prompt_template = system_prompt_template
        handler._tools_list = tools_list
        handler._descriptions = descriptions
        return handler

    def parse_tool_calls(self, text: str) -> List[ToolCall]:
        """
        Extract tool calls from an LLM response string.

        Searches for <tool_call>...</tool_call> blocks and parses
        the JSON content inside.

        Args:
            text: Raw LLM response text.

        Returns:
            List of parsed ToolCall instances. Empty if none found.
        """
        calls: List[ToolCall] = []
        pattern = re.compile(
            r"<tool_call>(.*?)</tool_call>",
            re.DOTALL | re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            raw = match.group(1).strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool call JSON: %s", raw[:200])
                continue

            if isinstance(data, list):
                for item in data:
                    call = self._dict_to_toolcall(item)
                    if call is not None:
                        calls.append(call)
            elif isinstance(data, dict):
                call = self._dict_to_toolcall(data)
                if call is not None:
                    calls.append(call)

        return calls

    @staticmethod
    def _dict_to_toolcall(data: Dict[str, Any]) -> Optional[ToolCall]:
        """
        Convert a dictionary to a ToolCall instance.

        Expected format: {"name": "...", "arguments": {...}}
        or {"tool_name": "...", "arguments": {...}}.

        Args:
            data: Dictionary from parsed JSON.

        Returns:
            ToolCall or None if parsing failed.
        """
        if not isinstance(data, dict):
            return None
        name = data.get("name") or data.get("tool_name") or data.get("function")
        if not name or not isinstance(name, str):
            return None
        arguments = data.get("arguments") or data.get("parameters") or data.get("args", {})
        if not isinstance(arguments, dict):
            try:
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                else:
                    arguments = {}
            except (json.JSONDecodeError, TypeError):
                arguments = {}
        call_id = data.get("call_id") or data.get("id", "")
        return ToolCall(tool_name=name, arguments=arguments, call_id=call_id)

    @staticmethod
    def format_results(results: List[ToolResult]) -> str:
        """
        Format tool execution results for consumption by the LLM.

        Args:
            results: List of ToolResult instances.

        Returns:
            Formatted string to include in the conversation.
        """
        parts = []
        for r in results:
            if r.success:
                parts.append(
                    f"Tool '{r.tool_name}' (call_id={r.call_id}) "
                    f"executed in {r.execution_time_ms:.1f}ms:\n"
                    f"```\n{r._serialize_output(r.output)}\n```"
                )
            else:
                parts.append(
                    f"Tool '{r.tool_name}' (call_id={r.call_id}) "
                    f"FAILED in {r.execution_time_ms:.1f}ms:\n"
                    f"Error: {r.error}"
                )
        return "\n\n".join(parts)

    @staticmethod
    def format_single_result(result: ToolResult) -> str:
        """
        Format a single tool execution result.

        Args:
            result: A single ToolResult instance.

        Returns:
            Formatted result string.
        """
        if result.success:
            return (
                f"Tool '{result.tool_name}' result:\n"
                f"```\n{result._serialize_output(result.output)}\n```"
            )
        return (
            f"Tool '{result.tool_name}' failed: {result.error}"
        )

    @staticmethod
    def has_tool_calls(text: str) -> bool:
        """
        Check if a text contains any tool call blocks.

        Args:
            text: The text to check.

        Returns:
            True if tool call blocks are found.
        """
        return bool(re.search(r"<tool_call>.*?</tool_call>", text, re.DOTALL | re.IGNORECASE))

    @staticmethod
    def strip_tool_calls(text: str) -> str:
        """
        Remove tool call blocks from text, returning only natural language.

        Args:
            text: Text that may contain <tool_call> blocks.

        Returns:
            Text with tool call blocks removed.
        """
        return re.sub(
            r"<tool_call>.*?</tool_call>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()


    def handle_tool_call(self, tool_call, context=None):
        """Execute a tool call and return its result."""
        calls = self.parse_tool_calls(str(tool_call)) if isinstance(tool_call, str) else [tool_call]
        if calls:
            return {"status": "ok", "result": str(calls[0])}
        return {"status": "error", "result": "no tool call found"}

    def list_available_tools(self):
        """Return a list of available tool names."""
        return []


MCPHandler = McpHandler
