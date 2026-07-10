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
    max_iterations: int = 10
    max_tool_calls_per_step: int = 5
    max_steps: int = 20
    max_tool_retries: int = 3

    # Planning
    use_planning: bool = True
    planning_prompt: str = "planning"
    replan_check_frequency: int = 3

    # Context management
    max_context_length: int = 128000
    context_truncation_strategy: str = "summarize"
    persist_conversation: bool = True
    conversation_dir: str = "./conversations"

    # Tool configuration
    allowed_tools: List[str] = field(
        default_factory=lambda: [
            "file_read", "file_write", "file_edit", "file_search",
            "shell_exec", "powershell_exec", "web_fetch", "web_search",
            "code_analyze", "rag_query", "image_analyze",
            "process_start", "process_list", "process_output", "process_stop",
            "ssh_exec", "scp_copy",
            "docker_exec", "docker_run", "docker_list_containers",
            "markdown_to_pdf", "markdown_to_docx",
        ]
    )
    require_tool_approval: bool = True
    dangerous_tools: List[str] = field(
        default_factory=lambda: [
            "shell_exec", "powershell_exec", "file_write",
            "process_start", "process_stop",
            "ssh_exec", "scp_copy", "docker_exec", "docker_run",
            "markdown_to_pdf", "markdown_to_docx",
        ]
    )

    # Permissions
    sandbox_shell: bool = True
    allowed_commands: List[str] = field(
        default_factory=lambda: [
            "ls", "cat", "head", "tail", "echo", "grep", "find",
            "python", "python3", "node", "npm", "git", "curl", "wget",
            "mkdir", "cp", "mv", "rm", "touch", "chmod",
        ]
    )
    blocked_commands: List[str] = field(
        default_factory=lambda: [
            "sudo", "su", "chown", "passwd", "kill", "pkill",
            "shutdown", "reboot", "init", "systemctl",
            "dd", "mkfs", "fdisk", "mount",
        ]
    )

    # Memory
    memory_type: str = "conversation"  # "conversation", "persistent", "hybrid"
    memory_limit: int = 100  # Number of past conversations to retain

    # Streaming
    stream_output: bool = True
    show_token_usage: bool = True
    show_tool_calls: bool = True
