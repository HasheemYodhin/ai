"""
Main agent orchestration loop for the dabba agent system.

Implements the observe -> plan -> act -> observe cycle, integrating
the planner, executor, tool registry, MCP handler, context manager,
and LLM inference.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from dabba.agent.context_manager import ContextManager
from dabba.agent.executor import Executor, ExecutionStats
from dabba.agent.mcp_handler import McpHandler
from dabba.agent.planner import ExecutionPlan, Planner
from dabba.agent.tool_schema import ToolCall, ToolResult
from dabba.agent.tool_registry import ToolRegistry
from dabba.config.agent_config import AgentConfig
from dabba.utils.logging import get_logger

logger = get_logger("dabba.agent.agent_loop")


LLMGenerateFn = Callable[
    [List[Dict[str, Any]], Dict[str, Any]],
    str,
]


class AgentLoop:
    """
    Main agent orchestration loop.

    Integrates all agent components into a cohesive loop:
        1. Observe: Receive user input, maintain context.
        2. Plan: Optionally decompose into a multi-step plan.
        3. Act: Execute tool calls via the tool registry.
        4. Observe: Incorporate tool results into context.

    Args:
        registry: ToolRegistry with registered tools.
        config: AgentConfig with behavior settings.
        llm_generate: Callable that takes a message list and
            generation params, returns the LLM response string.
        mcp_handler: Optional McpHandler instance.
        context_manager: Optional ContextManager instance.
        planner: Optional Planner instance.
        executor: Optional Executor instance.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        config: AgentConfig,
        llm_generate: LLMGenerateFn,
        mcp_handler: Optional[McpHandler] = None,
        context_manager: Optional[ContextManager] = None,
        planner: Optional[Planner] = None,
        executor: Optional[Executor] = None,
    ):
        self.registry = registry
        self.config = config
        self.llm_generate = llm_generate

        self.mcp_handler = mcp_handler or self._build_mcp_handler()
        self.context_manager = context_manager or ContextManager(
            max_context_length=config.max_context_length,
            truncation_strategy=config.context_truncation_strategy,
        )
        self.planner = planner or Planner(max_steps=config.max_steps)
        self.executor = executor or Executor(
            registry=registry,
            max_retries=config.max_tool_retries,
        )

        self._current_plan: Optional[ExecutionPlan] = None
        self._step_count: int = 0
        self._tool_call_count: int = 0
        self._session_start: float = 0.0
        self._metrics: Dict[str, Any] = {}
        # Track workspace root used when building the system prompt so we can
        # detect cross-workspace moves and rebuild with the new directory tree.
        self._system_prompt_workspace: Optional[str] = None

    def _ensure_system_prompt(self, override: Optional[str] = None) -> None:
        """Build or rebuild the system prompt if workspace changed or no prompt set."""
        if override:
            self.context_manager.set_system_prompt(override)
            self._system_prompt_workspace = getattr(self.config, "workspace_root", None)
            return

        current_workspace = getattr(self.config, "workspace_root", None)
        workspace_changed = (
            current_workspace
            and self._system_prompt_workspace is not None
            and current_workspace != self._system_prompt_workspace
        )

        if workspace_changed or not self.context_manager._system_prompt:
            tool_dicts = self._tool_dicts()
            sys_prompt = self.mcp_handler.build_system_prompt(
                self.mcp_handler.format_tool_descriptions(tool_dicts),
                self._workspace_info(),
            )
            self.context_manager.set_system_prompt(sys_prompt)
            self._system_prompt_workspace = current_workspace

    def _build_mcp_handler(self) -> McpHandler:
        """Build an McpHandler from the current registry."""
        return McpHandler.from_registry(self.registry)

    def _tool_dicts(self) -> List[Dict[str, Any]]:
        """Tool definitions as plain dicts — used for both the system prompt
        text and the native `tools=` schema passed to llm_generate."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_to_json_schema(),
            }
            for t in self.registry.list_tools()
            if hasattr(t, "name")
        ]

    def _workspace_info(self) -> str:
        """
        Grounding sentence telling the model what "the X directory" resolves
        against. Without this the model has zero absolute-path context and
        can only guess from conversation history — see AgentConfig.workspace_root.
        """
        root = getattr(self.config, "workspace_root", None)
        if not root:
            return ""
        
        tree_lines = []
        try:
            from pathlib import Path
            root_path = Path(root).expanduser().resolve()
            exclude_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", "out", "dist", "build", ".dabba", ".vscode"}
            
            def get_tree(dir_path: Path, prefix: str = "", depth: int = 0):
                if depth > 2:
                    return
                try:
                    entries = sorted(list(dir_path.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
                except OSError:
                    return
                
                for entry in entries:
                    if entry.name in exclude_dirs:
                        continue
                    if entry.is_dir():
                        tree_lines.append(f"{prefix}📁 {entry.name}/")
                        get_tree(entry, prefix + "  ", depth + 1)
                    else:
                        tree_lines.append(f"{prefix}📄 {entry.name}")
            
            get_tree(root_path)
        except Exception:
            pass
        
        tree_str = "\n".join(tree_lines[:100])
        if len(tree_lines) > 100:
            tree_str += f"\n  ... and {len(tree_lines) - 100} more files/directories."
            
        workspace_map = f"\n\nHere is a structural map of the current workspace:\n{tree_str}" if tree_str else ""
        
        return (
            f"Your current working directory / workspace root is: {root}\n"
            "Resolve every relative path and directory reference against this root unless the user gives an "
            f"absolute path. Never guess a different root.{workspace_map}"
        )

    def run(
        self,
        user_input: str,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a single user input through the full agent loop (synchronous).

        Returns:
            Dict with "response", "steps_taken", and optional "truncated" keys.
        """
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                self._async_run(user_input, system_prompt)
            )
        finally:
            loop.close()
        return {
            "response": response,
            "steps_taken": self._step_count,
        }

    def run_stream(
        self,
        user_input: str,
        system_prompt: Optional[str] = None,
    ):
        """Yield streaming events from the agent loop."""
        result = self.run(user_input, system_prompt)
        yield {"type": "response", "content": result.get("response", "")}

    def query(self, user_input: str, **kwargs) -> str:
        """Convenience wrapper that returns just the response string."""
        return self.run(user_input, **kwargs).get("response", "")

    def query_stream(self, user_input: str, **kwargs):
        """Yield response tokens/chunks as strings."""
        yield self.query(user_input, **kwargs)

    async def _async_run(
        self,
        user_input: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Internal async run implementation."""
        self._session_start = time.monotonic()
        self._step_count = 0
        self._tool_call_count = 0

        self._ensure_system_prompt(system_prompt)

        self.context_manager.add_entry(role="user", content=user_input)

        if self.config.use_planning:
            await self._try_planning(user_input)

        final_response = await self._run_loop()

        self._record_metrics(final_response)
        return final_response

    async def _try_planning(self, user_input: str) -> None:
        """
        Attempt to create and execute a multi-step plan.

        If planning produces a valid plan with multiple steps,
        execute it and incorporate results into context.

        Args:
            user_input: The original user request.
        """
        tool_list = self.registry.list_tools()
        tool_dicts = [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_to_json_schema(),
            }
            for t in tool_list
        ]

        try:
            plan = self.planner.create_plan(user_input, tool_dicts)
            issues = self.planner.validate_plan(plan)
            if issues:
                logger.warning("Plan validation issues: %s", issues)

            if plan.total_steps > 1:
                self._current_plan = plan
                logger.info(
                    "Executing plan '%s' with %d steps",
                    plan.plan_id, plan.total_steps,
                )

                stats = await self.executor.execute_plan(plan, max_concurrent=1)

                summary_parts = [
                    f"Executed plan with {stats.total_steps} steps: "
                    f"{stats.completed} succeeded, "
                    f"{stats.failed} failed, "
                    f"{stats.skipped} skipped."
                ]
                for step in plan.steps:
                    status_icon = "✓" if step.status.value == "succeeded" else "✗"
                    summary_parts.append(
                        f"  {status_icon} [{step.status.value}] "
                        f"{step.description or step.tool_name}"
                    )
                    if step.result is not None and step.status.value == "succeeded":
                        summary_parts.append(
                            f"    Result: {str(step.result)[:200]}"
                        )
                    if step.error:
                        summary_parts.append(f"    Error: {step.error[:200]}")

                summary = "\n".join(summary_parts)
                self.context_manager.add_entry(
                    role="assistant",
                    content=summary,
                    metadata={"type": "plan_execution_summary"},
                )

                if stats.failed > 0:
                    failed_steps = [
                        s for s in plan.steps if s.status.value == "failed"
                    ]
                    if failed_steps and self._step_count < self.config.max_steps:
                        new_plan = self.planner.replan(
                            plan, failed_steps[0], tool_dicts
                        )
                        if new_plan.total_steps > 0:
                            self._current_plan = new_plan
                            logger.info(
                                "Replanning with %d steps", new_plan.total_steps
                            )

            elif plan.total_steps == 1:
                logger.info("Single step plan; will handle in main loop")

        except Exception as exc:
            logger.error("Planning failed: %s", exc)
            self.context_manager.add_entry(
                role="assistant",
                content=f"Planning failed: {exc}. Continuing without plan.",
                metadata={"type": "planning_error"},
            )

    async def _run_loop(self) -> str:
        """
        Run the main observe-plan-act-observe loop.

        Returns:
            The final response text from the LLM.
        """
        final_response = ""

        while self._step_count < self.config.max_steps:
            self._step_count += 1
            logger.debug("Agent loop iteration %d/%d", self._step_count, self.config.max_steps)

            messages = self.context_manager.get_messages()
            generation_params = {
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                # Native function-calling schema — providers that support it
                # (openai/anthropic) use this to make a real tool call instead
                # of hoping the model spontaneously emits a <tool_call> tag.
                # Providers that don't read this kwarg (ollama/google/dabba)
                # silently ignore it, same as they already ignore top_p today.
                "tools": self._tool_dicts(),
            }

            try:
                # llm_generate calls a synchronous, blocking SDK client (requests/httpx
                # under the hood). Running it directly here would block the entire
                # asyncio event loop — freezing every other request the server is
                # handling, including unrelated /health checks — until it returns.
                # asyncio.to_thread runs it on a worker thread instead.
                response = await asyncio.to_thread(self.llm_generate, messages, generation_params)
            except Exception as exc:
                error_msg = f"LLM generation failed: {exc}"
                logger.error(error_msg)
                self.context_manager.add_entry(
                    role="assistant",
                    content=error_msg,
                    metadata={"type": "llm_error"},
                )
                final_response = f"I encountered an error: {exc}"
                break

            tool_calls = self.mcp_handler.parse_tool_calls(response)
            natural_response = self.mcp_handler.strip_tool_calls(response)

            if not tool_calls:
                final_response = response if response.strip() else natural_response
                self.context_manager.add_entry(
                    role="assistant",
                    content=final_response,
                )
                break

            if natural_response.strip():
                self.context_manager.add_entry(
                    role="assistant",
                    content=natural_response,
                )

            if self.config.show_tool_calls:
                logger.info(
                    "LLM requested %d tool call(s): %s",
                    len(tool_calls),
                    [tc.tool_name for tc in tool_calls],
                )

            tool_calls = tool_calls[: self.config.max_tool_calls_per_step]
            results = await self._execute_tool_calls(tool_calls)

            result_text = self.mcp_handler.format_results(results)
            self.context_manager.add_entry(
                role="tool",
                content=result_text,
                metadata={"type": "tool_results", "call_count": len(results)},
            )

            if self.config.show_token_usage:
                logger.info(
                    "Step %d: context usage %d/%d tokens (%.1f%%)",
                    self._step_count,
                    self.context_manager.total_tokens,
                    self.context_manager.max_context_length,
                    self.context_manager.usage_ratio * 100,
                )

        else:
            final_response = (
                final_response
                or "I've reached the maximum number of steps. "
                "Please refine your request if the task isn't complete."
            )

        return final_response

    async def _execute_tool_calls(
        self,
        calls: List["ToolCall"],
    ) -> List["ToolResult"]:
        """
        Execute a batch of tool calls.

        Checks approval requirements, executes via registry.

        Args:
            calls: List of ToolCall instances.

        Returns:
            List of ToolResult instances.
        """
        results: List[ToolResult] = []
        for call in calls:
            self._tool_call_count += 1

            if self.config.require_tool_approval:
                if call.tool_name in self.config.dangerous_tools:
                    logger.info(
                        "Tool '%s' requires approval (dangerous tool)",
                        call.tool_name,
                    )
                    results.append(ToolResult(
                        tool_name=call.tool_name,
                        call_id=call.call_id,
                        success=False,
                        error=(
                            f"Tool '{call.tool_name}' requires manual approval. "
                            "Please confirm in a separate message."
                        ),
                        execution_time_ms=0.0,
                    ))
                    continue

            result = await self.registry.execute(call)
            results.append(result)

        return results

    async def chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Convenience method for single-turn chat.

        Args:
            message: User message.
            system_prompt: Optional system prompt.

        Returns:
            Agent response.
        """
        return await self._async_run(message, system_prompt)

    async def stream_chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
    ):
        """
        Stream the agent's response token by token.

        Yields response chunks as they are generated by the LLM,
        including tool call notifications.

        Args:
            message: User message.
            system_prompt: Optional system prompt.

        Yields:
            Dict with "type" ("text", "tool_call", "tool_result", "error")
            and "content".
        """
        self._session_start = time.monotonic()
        self._step_count = 0
        self._tool_call_count = 0

        self._ensure_system_prompt(system_prompt)

        self.context_manager.add_entry(role="user", content=message, metadata={"stream": True})

        if self.config.use_planning:
            await self._try_planning(message)

        while self._step_count < self.config.max_steps:
            self._step_count += 1
            messages = self.context_manager.get_messages()
            generation_params = {
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "tools": self._tool_dicts(),
            }

            # Live token count: tokens of everything sent to the LLM this step
            input_tokens = sum(
                self.context_manager._token_counter(m.get("content", "") or "")
                for m in messages
                if isinstance(m, dict)
            )

            try:
                # See the comment on the equivalent call in _run_loop — this must
                # not block the event loop while waiting on a slow provider.
                response = await asyncio.to_thread(self.llm_generate, messages, generation_params)
            except Exception as exc:
                error_msg = f"LLM generation failed: {exc}"
                logger.error(error_msg)
                yield {"type": "error", "content": str(exc)}
                break

            output_tokens = self.context_manager._token_counter(response or "")
            yield {
                "type": "usage",
                "content": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "step": self._step_count,
                },
            }

            tool_calls = self.mcp_handler.parse_tool_calls(response)
            natural_response = self.mcp_handler.strip_tool_calls(response)

            if natural_response.strip():
                yield {"type": "text", "content": natural_response}
                self.context_manager.add_entry(role="assistant", content=natural_response)

            if not tool_calls:
                break

            for tc in tool_calls[:self.config.max_tool_calls_per_step]:
                yield {
                    "type": "tool_call",
                    "content": {"name": tc.tool_name, "arguments": tc.arguments, "call_id": tc.call_id},
                }

            results = await self._execute_tool_calls(
                tool_calls[:self.config.max_tool_calls_per_step]
            )

            result_text = self.mcp_handler.format_results(results)
            self.context_manager.add_entry(role="tool", content=result_text)

            for r in results:
                yield {"type": "tool_result", "content": r.to_dict()}

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current session metrics.

        Returns:
            Dictionary with steps, tool calls, context usage, etc.
        """
        metrics = dict(self._metrics)
        metrics.update({
            "step_count": self._step_count,
            "tool_call_count": self._tool_call_count,
            "context_usage_ratio": self.context_manager.usage_ratio,
            "context_total_tokens": self.context_manager.total_tokens,
            "context_entry_count": self.context_manager.entry_count,
        })
        if self._session_start > 0:
            metrics["session_duration_ms"] = (time.monotonic() - self._session_start) * 1000
        return metrics

    def _record_metrics(self, final_response: str) -> None:
        """Record session metrics after completion."""
        duration = (time.monotonic() - self._session_start) * 1000 if self._session_start > 0 else 0
        self._metrics = {
            "steps_used": self._step_count,
            "tool_calls_made": self._tool_call_count,
            "duration_ms": duration,
            "response_length": len(final_response),
            "context_entries": self.context_manager.entry_count,
            "context_tokens": self.context_manager.total_tokens,
        }

    def reset(self) -> None:
        """Reset the agent state for a new session."""
        self.context_manager.reset()
        self._current_plan = None
        self._step_count = 0
        self._tool_call_count = 0
        self._session_start = 0.0
        self._metrics.clear()
        logger.info("Agent loop reset")
