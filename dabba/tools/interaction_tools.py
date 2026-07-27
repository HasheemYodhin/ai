"""
User-interaction tool for the dabba agent.

Lets the agent pause mid-task to ask the user a clarifying question instead
of guessing. Unlike every other tool, `ask_user` is never actually executed
through the normal registry dispatch path — AgentLoop.stream_chat() (see
agent_loop.py) special-cases it: the moment the model calls it, the loop
yields a "question" event and ends the turn cleanly, rather than running a
handler and feeding a result back into the same turn. The user's next
ordinary chat message is the answer — it lands in the same persisted
conversation context, so the model sees question + reply and continues
naturally. No blocking wait, no side-channel endpoint, no call_id plumbing
required, unlike the tool-call approval flow in agent_endpoints.py.

The handler registered here only matters if this tool is ever invoked
through some other path (direct testing, `registry.execute("ask_user", ...)`)
that skips agent_loop's special-casing — real usage never reaches it.
"""
from __future__ import annotations

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry


def ask_user(question: str, options: list | None = None) -> str:
    """Placeholder handler — see module docstring for why this rarely runs."""
    return (
        "This tool pauses the conversation for a human reply and has no "
        "programmatic result — the agent loop should have intercepted the "
        "call before this handler ran."
    )


def register_interaction_tools(registry: ToolRegistry) -> None:
    """Register the ask_user tool with a ToolRegistry."""
    registry.register(
        ToolDefinition(
            name="ask_user",
            description=(
                "Ask the user a clarifying question and PAUSE this turn until they "
                "reply — use this instead of guessing when a request is ambiguous, "
                "underspecified, or has a consequential choice to make (e.g. "
                "'light or dark theme?', 'which file did you mean?'). Do not call "
                "any other tool in the same turn as this one; ask first, then wait. "
                "Their next message is the answer — continue the task from there."
            ),
            parameters=[
                ToolParameter(name="question", type="string", description="The question to ask, in plain language."),
                ToolParameter(
                    name="options",
                    type="array",
                    description="Optional short list of suggested answers, e.g. [\"Light\", \"Dark\"]. Omit for open-ended questions.",
                    required=False,
                    items=ToolParameter(name="option", type="string"),
                ),
            ],
            handler=ask_user,
            handler_sync=True,
            category="interaction",
        )
    )
