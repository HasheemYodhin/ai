"""
Agent orchestration proxy for the dabba CLI.

Wraps the AgentLoop for CLI use, managing model connections,
streaming output, tool call display, and permission management.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, TYPE_CHECKING

import httpx

from dabba.cli.config import CliConfig
from dabba.cli.output_handler import OutputHandler
from dabba.cli.permissions import PermissionManager
from dabba.config.agent_config import AgentConfig

if TYPE_CHECKING:
    from dabba.agent import AgentLoop, ToolRegistry


def _get_logger():
    """Lazy logger to avoid importing torch through dabba.utils."""
    from dabba.utils.logging import get_logger
    return get_logger("dabba.cli.agent_proxy")


class AgentProxy:
    """
    High-level proxy around AgentLoop for CLI consumption.

    Handles LLM generation via API calls, permission checking,
    tool call rendering, and session lifecycle management.

    Args:
        cli_config: CLI configuration instance.
        output: OutputHandler for rendering.
        permissions: PermissionManager for tool approval.
        agent_config: Optional AgentConfig override.
    """

    def __init__(
        self,
        cli_config: Optional[CliConfig] = None,
        output: Optional[OutputHandler] = None,
        permissions: Optional[PermissionManager] = None,
        agent_config: Optional[AgentConfig] = None,
    ):
        self.cli_config = cli_config or CliConfig.load()
        self.output = output or OutputHandler(config=self.cli_config)
        self.permissions = permissions or PermissionManager(
            mode=self.cli_config.permission_mode,
        )
        if self.permissions.confirm_fn is None:
            self.permissions.confirm_fn = self._confirm_tool

        self.agent_config = agent_config or AgentConfig(
            model_name=self.cli_config.default_model,
            max_tokens=self.cli_config.default_max_tokens,
            temperature=self.cli_config.default_temperature,
            top_p=self.cli_config.default_top_p,
            show_tool_calls=self.cli_config.show_tool_calls,
            show_token_usage=self.cli_config.show_token_usage,
            require_tool_approval=self.cli_config.require_tool_approval,
            stream_output=self.cli_config.stream_output,
        )

        self.registry = None
        self._agent_loop = None
        self._http_client: Optional[httpx.Client] = None
        self._discovered_tools = False
        self._current_tool_calls: List[Dict[str, Any]] = []
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._todo_store = None
        # Real MCP (Model Context Protocol) client — connects to externally
        # configured servers and registers their tools alongside the
        # built-in ones. See dabba/agent/mcp_client.py for why this needs
        # its own background loop instead of piggybacking on whichever loop
        # is running when _get_registry() happens to be called.
        from dabba.agent.mcp_client import McpClientManager
        self.mcp_manager = McpClientManager()
        # Diffs from file edits this turn, queued here instead of printed
        # directly — the Textual TUI can't safely mix raw Rich console prints
        # with its own screen rendering, so it drains this list itself and
        # renders each diff as a proper widget instead.
        self._pending_diffs: List[Dict[str, str]] = []

    def _get_http_client(self) -> httpx.Client:
        """Get or create the HTTP client for API calls."""
        if self._http_client is None:
            self._http_client = httpx.Client(
                base_url=self.cli_config.api_endpoint,
                headers=self.cli_config.get_api_headers(),
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._http_client

    def _get_registry(self):
        """Get or create the ToolRegistry and register all tools."""
        from dabba.agent import ToolRegistry
        from dabba.agent.tool_schema import ToolCall as _ToolCall
        if not self._discovered_tools:
            self.registry = ToolRegistry()
            try:
                from dabba.tools.file_tools import register_file_tools
                from dabba.tools.shell_tools import register_shell_tools
                from dabba.tools.code_tools import register_code_tools
                from dabba.tools.todo_tools import register_todo_tools
                from dabba.tools.process_tools import register_process_tools
                from dabba.tools.ssh_tools import register_ssh_tools
                from dabba.tools.docker_tools import register_docker_tools
                from dabba.tools.artifact_tools import register_artifact_tools
                from dabba.tools.web_tools import register_web_tools
                from dabba.tools.rag_tool import register_rag_tools
                register_file_tools(self.registry)
                register_shell_tools(self.registry)
                register_code_tools(self.registry)
                register_process_tools(self.registry)
                register_ssh_tools(self.registry)
                register_docker_tools(self.registry)
                register_artifact_tools(self.registry)
                register_web_tools(self.registry)
                register_rag_tools(self.registry)
                self._todo_store = register_todo_tools(self.registry)
            except Exception as exc:
                _get_logger().warning("Tool registration failed: %s", exc)

            try:
                from dabba.agent.mcp_client import register_mcp_tools
                summary = self.mcp_manager.connect()
                added = register_mcp_tools(self.registry, self.mcp_manager)
                if summary["connected"]:
                    _get_logger().info(
                        "MCP servers connected: %s (%d tools registered)",
                        summary["connected"], added,
                    )
                if summary["failed"]:
                    _get_logger().warning("MCP servers failed to connect: %s", summary["failed"])
            except Exception as exc:
                # MCP is opt-in (empty config = no-op) — a broken server or
                # missing `mcp` package must not take down the whole agent.
                _get_logger().warning("MCP tool registration skipped: %s", exc)

            # AgentLoop's own dangerous-tool gate (require_tool_approval) just
            # auto-rejects with no way to actually approve — it never consults
            # PermissionManager at all. Disable it here and do the real check
            # (with diff preview via _confirm_tool) in this wrapper instead,
            # so /mode ask + the diff-on-confirm flow actually gets reached.
            self.agent_config.require_tool_approval = False

            # Patch ToolRegistry.execute to handle async contexts properly.
            # The original creates a new event loop (new_event_loop +
            # run_until_complete), which crashes with "Cannot run the event
            # loop while another loop is running" when called from within
            # the agent loop's async context.
            original_execute = self.registry.execute
            fn_tools = self.registry._fn_tools

            async def _execute_wrapper(call_or_name, arguments=None):
                if isinstance(call_or_name, str):
                    name = call_or_name
                    args = arguments or {}
                    if name in fn_tools:
                        return fn_tools[name](**args)
                    if name not in self.registry.tools:
                        raise ValueError(f"Unknown tool: '{name}'")
                    call = _ToolCall(tool_name=name, arguments=args)
                else:
                    call = call_or_name
                    name = call.tool_name
                    args = call.arguments

                if name in ("shell_exec", "powershell_exec") and not args.get("cwd") and getattr(self.agent_config, "workspace_root", None):
                    args["cwd"] = self.agent_config.workspace_root

                if self.permissions.is_dangerous_tool(name) and not self.permissions.check_tool(name, args):
                    from dabba.agent.tool_schema import ToolResult as _ToolResult
                    return _ToolResult(
                        tool_name=name,
                        call_id=getattr(call, "call_id", ""),
                        success=False,
                        error=f"Tool '{name}' was denied.",
                    )

                # Show a live before/after diff once a file edit actually runs,
                # regardless of how it was approved (auto mode / already-confirmed).
                # `call` is always a real _ToolCall by this point — the only path
                # that skips it (string name found in fn_tools) already returned above.
                if name in ("file_write", "file_edit"):
                    diff_text = self._build_file_diff(name, args)
                    result = await self.registry._execute_async(call)
                    if diff_text and getattr(result, "success", True):
                        # Classic REPL mode: print directly, colored via Rich.
                        self.output.info(f"Changed {args.get('path', '?')}:")
                        self.output.diff_display(diff_text)
                        # Textual TUI mode: queue for the TUI to render as a
                        # widget instead (raw console prints aren't safe there).
                        self._pending_diffs.append({"path": args.get("path", "?"), "diff": diff_text})
                    
                    # Post-write verification hook
                    if getattr(result, "success", True) and args.get("path"):
                        try:
                            from pathlib import Path
                            path = Path(args["path"])
                            if not path.is_absolute() and getattr(self.agent_config, "workspace_root", None):
                                path = Path(self.agent_config.workspace_root) / path
                            if path.exists():
                                content = path.read_text(encoding="utf-8", errors="replace")
                                compile_msg = ""
                                if path.suffix == ".py":
                                    try:
                                        compile(content, str(path), "exec")
                                        compile_msg = " (Python compilation check: PASSED)"
                                    except SyntaxError as e:
                                        compile_msg = f" (Python compilation check: FAILED with SyntaxError: {e})"
                                if hasattr(result, "output"):
                                    if isinstance(result.output, dict):
                                        result.output["verification"] = f"File exists and is readable.{compile_msg}"
                                        result.output["current_content"] = content
                                    else:
                                        result.output = f"{result.output}\n\n[Verification: File exists and is readable.{compile_msg}]\n[Current Content of {path.name}:]\n{content}"
                        except Exception as e:
                            _get_logger().warning("Post-write verification failed: %s", e)
                    return result

                return await self.registry._execute_async(call)

            def patched_execute(call_or_name, arguments=None):
                try:
                    asyncio.get_running_loop()
                    return _execute_wrapper(call_or_name, arguments)
                except RuntimeError:
                    return original_execute(call_or_name, arguments)

            self.registry.execute = patched_execute
            self._discovered_tools = True
        return self.registry

    def _get_provider_registry(self):
        """Get or create the provider registry."""
        if not hasattr(self, "_provider_registry") or self._provider_registry is None:
            from dabba.providers.registry import ProviderRegistry
            self._provider_registry = ProviderRegistry(self.cli_config)
        return self._provider_registry

    def _build_llm_generate(self):
        """Build the LLM generate callable — routes to the right provider."""

        def llm_generate(
            messages: List[Dict[str, Any]],
            generation_params: Dict[str, Any],
        ) -> str:
            registry = self._get_provider_registry()
            model  = generation_params.pop("model", None) or self.cli_config.default_model
            effort = generation_params.pop("effort", None) or getattr(self.cli_config, "effort", "medium")
            return registry.chat(
                messages,
                model=model,
                effort=effort,
                **generation_params,
            )

        return llm_generate

    def _ensure_agent_loop(self, workspace: Optional[str] = None):
        """Ensure the AgentLoop is initialized, restoring any persisted context."""
        from dabba.agent import AgentLoop
        # Ground the model in a real absolute path instead of letting it guess
        # at "the X directory" from conversation history alone. Set on every
        # call (not just first) so it stays current even once the loop is
        # cached — self.agent_config is the same object AgentLoop holds a
        # reference to, so this takes effect on the very next generation call.
        self.agent_config.workspace_root = workspace or os.getcwd()
        if self._agent_loop is None:
            self._agent_loop = AgentLoop(
                registry=self._get_registry(),
                config=self.agent_config,
                llm_generate=self._build_llm_generate(),
                context_manager=self._load_session(workspace),
            )
        return self._agent_loop

    def _session_path(self, workspace: Optional[str]):
        """
        Where this workspace's conversation context is persisted.

        One file per workspace so switching VSCode windows/projects doesn't
        cross-contaminate context; falls back to a global file when the
        extension didn't send a workspace root (e.g. no folder open).
        """
        from pathlib import Path
        if workspace:
            return Path(workspace) / ".dabba" / "session.json"
        return Path.home() / ".dabba" / "session.json"

    def _load_session(self, workspace: Optional[str]):
        """
        Restore persisted conversation context from a prior server run.

        Returns None (AgentLoop then builds a fresh ContextManager) if no
        session file exists yet or it can't be parsed — this is best-effort
        recovery, not something that should ever block startup.
        """
        import json
        from dabba.agent.context_manager import ContextManager

        path = self._session_path(workspace)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ContextManager.deserialize(data)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _get_logger().warning("Failed to load persisted session %s: %s", path, exc)
            return None

    def save_session(self, workspace: Optional[str] = None) -> None:
        """
        Persist the current conversation context to disk.

        Best-effort: a write failure (e.g. read-only filesystem) is logged
        and swallowed rather than breaking the chat turn that just completed.
        """
        import json

        if self._agent_loop is None:
            return
        path = self._session_path(workspace)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self._agent_loop.context_manager.serialize()),
                encoding="utf-8",
            )
        except OSError as exc:
            _get_logger().warning("Failed to persist session %s: %s", path, exc)

    def run(self, user_input: str) -> str:
        """
        Run a single user request through the agent loop.

        Args:
            user_input: The user's message.

        Returns:
            The agent's final response text.
        """
        agent_loop = self._ensure_agent_loop()
        try:
            result = agent_loop.run(user_input)
            response = result.get("response", "") if isinstance(result, dict) else str(result)
            metrics = agent_loop.get_metrics()

            if self.cli_config.show_token_usage:
                self.output.token_usage(
                    total_tokens=metrics.get("context_total_tokens", 0),
                )

            return response
        except Exception as exc:
            _get_logger().error("Agent run failed: %s", exc)
            return f"I encountered an error: {exc}"

    async def stream(
        self,
        user_input: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream the agent's response chunks.

        Args:
            user_input: The user's message.

        Yields:
            Dicts with "type" and "content" keys.
        """
        loop = self._ensure_agent_loop()

        try:
            async for chunk in loop.stream_chat(user_input):
                chunk_type = chunk.get("type", "")
                content = chunk.get("content", "")

                if chunk_type == "tool_call":
                    tool_name = content.get("name", "") if isinstance(content, dict) else ""
                    args = content.get("arguments", {}) if isinstance(content, dict) else {}

                    allowed = self.permissions.check_tool(tool_name, args)
                    if not allowed:
                        yield {
                            "type": "tool_denied",
                            "content": f"Tool '{tool_name}' was denied.",
                        }
                        continue

                    self._current_tool_calls.append(
                        {"name": tool_name, "arguments": args, "allowed": True}
                    )

                yield chunk
        except Exception as exc:
            _get_logger().error("Stream failed: %s", exc)
            yield {"type": "error", "content": str(exc)}

    def stream_sync(self, user_input: str) -> str:
        """
        Run in streaming mode synchronously, collecting the full response.

        Args:
            user_input: The user's message.

        Returns:
            The complete response text.
        """
        full_response = ""

        async def _collect():
            nonlocal full_response
            async for chunk in self._run_with_spinner(user_input):
                chunk_type = chunk.get("type", "")
                content = chunk.get("content", "")

                if chunk_type == "text":
                    if isinstance(content, str):
                        full_response += content
                        self.output.stream_token(content)
                elif chunk_type == "tool_call":
                    self._handle_tool_call_display(chunk)
                elif chunk_type == "tool_result":
                    self._handle_tool_result_display(chunk)
                elif chunk_type == "error":
                    self.output.error(f"Error: {content}")
                elif chunk_type == "tool_denied":
                    self.output.warning(f"Tool denied: {content}")
            self.output.stream_end()

            metrics = self._get_metrics()
            if metrics and self.cli_config.show_token_usage:
                self.output.token_usage(
                    total_tokens=metrics.get("context_total_tokens", 0),
                )

            return full_response

        loop = self._ensure_event_loop()
        try:
            return loop.run_until_complete(_collect())
        except RuntimeError as exc:
            if "Event loop is closed" in str(exc) or "already running" in str(exc):
                self._event_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._event_loop)
                return self._event_loop.run_until_complete(_collect())
            raise

    async def _run_with_spinner(self, user_input: str):
        """Run streaming with a spinner during API calls."""
        # progress_spinner is a @contextmanager — collect chunks first, then yield
        chunks_collected = []
        error_chunk = None

        loop = self._ensure_agent_loop()

        # Run the agent loop inside the spinner context
        with self.output.progress_spinner("thinking..."):
            try:
                async for chunk in loop.stream_chat(user_input):
                    chunks_collected.append(chunk)
            except Exception as exc:
                error_chunk = {"type": "error", "content": str(exc)}

        # Spinner is gone — now yield chunks for display
        if error_chunk:
            yield error_chunk
            return

        for chunk in chunks_collected:
            chunk_type = chunk.get("type", "")
            content = chunk.get("content", "")

            if chunk_type == "tool_call":
                tool_data = content if isinstance(content, dict) else {}
                tool_name = tool_data.get("name", "")
                arguments = tool_data.get("arguments", {})
                allowed = self.permissions.check_tool(tool_name, arguments)
                if not allowed:
                    yield {"type": "tool_denied", "content": f"Tool '{tool_name}' was denied."}
                    continue

            yield chunk

    def _confirm_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]]) -> bool:
        """
        Render a real y/n confirmation for a dangerous tool call.

        Shows a diff preview for file_write/file_edit before asking, since a
        bare tool name tells the user nothing about what will actually change.
        """
        arguments = arguments or {}
        if tool_name in ("file_write", "file_edit"):
            diff_text = self._build_file_diff(tool_name, arguments)
            if diff_text:
                self.output.info(f"Proposed change to {arguments.get('path', '?')}:")
                self.output.diff_display(diff_text)
        elif tool_name == "shell_exec":
            self.output.info(f"Command: {arguments.get('command', '')}")
        else:
            args_str = json.dumps(arguments, indent=2) if arguments else ""
            if args_str:
                self.output.info(args_str[:500])

        return self.output.confirm(f"Allow '{tool_name}'?", default=False)

    def _build_file_diff(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Compute a unified diff for a pending file_write/file_edit call."""
        import difflib
        from pathlib import Path

        path = arguments.get("path", "")
        if not path:
            return ""

        try:
            existing = Path(path).expanduser().resolve().read_text(
                encoding="utf-8", errors="replace"
            )
        except (OSError, UnicodeDecodeError):
            existing = ""

        if tool_name == "file_write":
            new_content = arguments.get("content", "")
        else:  # file_edit
            old_string = arguments.get("old_string", "")
            new_string = arguments.get("new_string", "")
            if old_string and old_string in existing:
                new_content = existing.replace(old_string, new_string)
            else:
                return ""

        diff = difflib.unified_diff(
            existing.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        return "".join(diff)

    def _handle_tool_call_display(self, chunk: Dict[str, Any]) -> None:
        """Display a tool call notification."""
        content = chunk.get("content", {})
        if isinstance(content, dict):
            tool_name = content.get("name", "unknown")
            args = content.get("arguments", {})
            args_str = json.dumps(args, indent=2) if args else ""
            self.output.tool_message(tool_name, "start", args_str[:200])

    def _handle_tool_result_display(self, chunk: Dict[str, Any]) -> None:
        """Display a tool result."""
        content = chunk.get("content", {})
        if isinstance(content, dict):
            tool_name = content.get("tool", "unknown")
            success = content.get("success", True)
            if success:
                self.output.tool_message(tool_name, "success")
            else:
                error = content.get("error", "")
                self.output.tool_message(tool_name, "error", error[:100])

    def _get_metrics(self) -> Dict[str, Any]:
        """Get current agent metrics."""
        if self._agent_loop is not None:
            return self._agent_loop.get_metrics()
        return {}

    def reset(self) -> None:
        """Reset the agent state for a new session."""
        if self._agent_loop is not None:
            self._agent_loop.reset()
        self._current_tool_calls.clear()

    def reload_config(self) -> None:
        """Reload CLI config from disk and reinitialize agent."""
        self.cli_config = CliConfig.load()
        self.agent_config = AgentConfig(
            model_name=self.cli_config.default_model,
            max_tokens=self.cli_config.default_max_tokens,
            temperature=self.cli_config.default_temperature,
            top_p=self.cli_config.default_top_p,
            show_tool_calls=self.cli_config.show_tool_calls,
            show_token_usage=self.cli_config.show_token_usage,
            require_tool_approval=self.cli_config.require_tool_approval,
        )
        self._agent_loop = None
        self.registry = None
        self._discovered_tools = False
        self.permissions.set_mode(self.cli_config.permission_mode)

    def _ensure_event_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create a persistent event loop for this proxy."""
        if self._event_loop is None or self._event_loop.is_closed():
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)
        return self._event_loop

    def close(self) -> None:
        """Clean up resources."""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
        if self._event_loop is not None and not self._event_loop.is_closed():
            self._event_loop.close()
            self._event_loop = None
        self.mcp_manager.close()
