"""
Agent and MCP (Model Context Protocol) configuration.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class AgentConfig:
    """
    Configuration for the AI agent loop, MCP handler, tool registry,
    planning, and context management.
    """

    # Model settings
    model_name: str = "dabba"  # or "llama3", "gpt-4", etc.
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9

    # Agent behavior
    system_prompt: str = "You are a helpful AI assistant."
    # Absolute path the model should resolve relative directory/file mentions
    # against (e.g. "the train directory"). Set per-request by
    # AgentProxy._ensure_agent_loop — None means no grounding was provided
    # and the model has to guess from conversation history alone.
    workspace_root: Optional[str] = None
    active_file: Optional[str] = None
    max_iterations: int = 10
    max_tool_calls_per_step: int = 5
    max_steps: int = 50
    max_tool_retries: int = 3
    max_llm_retries: int = 2

    # Planning
    use_planning: bool = True
    planning_prompt: str = "planning"
    replan_check_frequency: int = 3
    # When True, a multi-step plan is proposed to the caller and must be
    # explicitly approved (via the streaming "plan_approval_required" event)
    # before the executor runs it. Defaults off so existing callers (CLI,
    # Cowork) keep auto-executing plans exactly as before.
    require_plan_approval: bool = False

    # Context management
    max_context_length: int = 128000
    context_truncation_strategy: str = "summarize"
    persist_conversation: bool = True
    conversation_dir: str = "./conversations"
    # Proactive LLM-based compaction: when the context fills past this
    # fraction, older turns are summarized (by the model) into one entry
    # BEFORE the next step, so a long task keeps its earlier context as a
    # real summary instead of losing it to a placeholder or a hard drop.
    # Set to 0 to disable proactive compaction (emergency truncation still
    # runs if the hard max_context_length is ever exceeded).
    context_compaction_threshold: float = 0.75
    # Most recent entries always kept verbatim (never folded into a summary).
    context_compaction_keep_recent: int = 6

    # Tool configuration. Empty (the default) means unrestricted — every tool
    # in the registry is available, matching every existing caller's behavior
    # today. Set to a non-empty list to scope an AgentLoop to only those
    # tools (both in what's advertised to the model and what actually
    # executes) — used for custom subagent types with a fixed tool allowlist.
    allowed_tools: List[str] = field(default_factory=list)
    # When True, only a small "always visible" set of tools plus whatever the
    # model has already activated via the tool_search meta-tool are
    # advertised in tools=, instead of the full registry — cuts prompt bloat
    # on a large tool registry. Off by default: every existing caller keeps
    # seeing every allowed tool up front, same as today.
    use_tool_search: bool = False
    tool_search_always_visible: List[str] = field(
        default_factory=lambda: ["tool_search", "ask_user", "todo_write", "todo_list"]
    )
    require_tool_approval: bool = True
    dangerous_tools: List[str] = field(
        default_factory=lambda: [
            "shell_exec",
            "powershell_exec",
            "file_write",
            "transactional_edit",
            "process_start",
            "process_stop",
            "ssh_exec",
            "scp_copy",
            "docker_exec",
            "docker_run",
            "markdown_to_pdf",
            "markdown_to_docx",
        ]
    )

    # Permissions
    sandbox_shell: bool = True
    allowed_commands: List[str] = field(
        default_factory=lambda: [
            "ls",
            "cat",
            "head",
            "tail",
            "echo",
            "grep",
            "find",
            "python",
            "python3",
            "node",
            "npm",
            "git",
            "curl",
            "wget",
            "mkdir",
            "cp",
            "mv",
            "rm",
            "touch",
            "chmod",
        ]
    )
    blocked_commands: List[str] = field(
        default_factory=lambda: [
            "sudo",
            "su",
            "chown",
            "passwd",
            "kill",
            "pkill",
            "shutdown",
            "reboot",
            "init",
            "systemctl",
            "dd",
            "mkfs",
            "fdisk",
            "mount",
        ]
    )

    # Memory
    memory_type: str = "conversation"  # "conversation", "persistent", "hybrid"
    memory_limit: int = 100  # Number of past conversations to retain

    # Streaming
    stream_output: bool = True
    show_token_usage: bool = True
    show_tool_calls: bool = True
