"""
Plan executor for the dabba agent system.

Executes generated plans step by step, handling tool call results,
errors, step dependencies, and progress tracking.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from dabba.agent.planner import ExecutionPlan, PlanStep, StepStatus
from dabba.agent.tool_registry import ToolRegistry
from dabba.utils.logging import get_logger

logger = get_logger("dabba.agent.executor")


ProgressCallback = Callable[[ExecutionPlan, PlanStep], None]


@dataclass
class ExecutionStats:
    """
    Statistics about plan execution.

    Args:
        total_steps: Total steps in the plan.
        completed: Steps that succeeded.
        failed: Steps that failed.
        skipped: Steps that were skipped.
        total_duration_ms: Wall-clock time for execution.
        tool_calls_made: Number of tool calls executed.
    """

    total_steps: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    total_duration_ms: float = 0.0
    tool_calls_made: int = 0


class Executor:
    """
    Executes ExecutionPlan instances step by step.

    Handles dependency resolution, tool dispatch, error recovery,
    and progress reporting.

    Args:
        registry: ToolRegistry for executing tool calls.
        max_retries: Maximum retries per step on failure.
        progress_callback: Optional callback invoked after each step.
            Receives the plan and the step that was just processed.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        max_retries: int = 3,
        progress_callback: Optional[ProgressCallback] = None,
    ):
        self.registry = registry
        self.max_retries = max_retries
        self.progress_callback = progress_callback

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        max_concurrent: int = 1,
    ) -> ExecutionStats:
        """
        Execute all steps in a plan.

        Respects step dependencies. Steps with satisfied dependencies
        are executed. If max_concurrent > 1, independent steps may
        run in parallel.

        Args:
            plan: The execution plan to carry out.
            max_concurrent: Maximum number of steps to run concurrently.

        Returns:
            ExecutionStats summarizing the results.
        """
        start_time = time.monotonic()
        stats = ExecutionStats(total_steps=plan.total_steps)

        if plan.total_steps == 0:
            logger.warning("Executing plan with zero steps")
            stats.total_duration_ms = (time.monotonic() - start_time) * 1000
            return stats

        completed_ids: Set[str] = set()
        pending = {s.step_id for s in plan.steps if s.status == StepStatus.PENDING}

        while pending:
            ready_steps = self._get_ready_steps(plan, completed_ids)
            if not ready_steps:
                blocked = self._get_blocked_steps(plan, completed_ids)
                if blocked and not ready_steps:
                    logger.warning(
                        "Deadlock: %d steps blocked with unsatisfied dependencies",
                        len(blocked),
                    )
                    for step in blocked:
                        step.status = StepStatus.SKIPPED
                        pending.discard(step.step_id)
                        stats.skipped += 1
                break

            batch = ready_steps[:max_concurrent]
            for step in batch:
                step.status = StepStatus.RUNNING

            tasks = [self._execute_step(step) for step in batch]
            results = await asyncio.gather(*tasks)

            for step, success in zip(batch, results):
                if success:
                    completed_ids.add(step.step_id)
                    stats.completed += 1
                else:
                    stats.failed += 1
                pending.discard(step.step_id)
                stats.tool_calls_made += 1

                if self.progress_callback:
                    self.progress_callback(plan, step)

        stats.total_duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "Plan execution completed: %d/%d steps succeeded, "
            "%d failed, %d skipped in %.1fms",
            stats.completed,
            stats.total_steps,
            stats.failed,
            stats.skipped,
            stats.total_duration_ms,
        )
        return stats

    def execute_step(self, step) -> Dict[str, Any]:
        """
        Execute a single plan step (synchronous).

        Returns:
            Dict with "status" and "result" keys.
        """
        import asyncio as _asyncio
        loop = _asyncio.new_event_loop()
        try:
            ok = loop.run_until_complete(self._execute_step(step))
        except Exception as exc:
            return {"status": "failed", "result": None, "error": str(exc)}
        finally:
            loop.close()
        return {"status": "success" if ok else "failed", "result": getattr(step, "result", None)}

    async def _execute_step(self, step: PlanStep) -> bool:
        """
        Internal step execution with retries.

        Args:
            step: The step to execute.

        Returns:
            True if the step eventually succeeded.
        """
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                tool_call = step.to_tool_call()
                result = await self.registry.execute(tool_call)

                if result.success:
                    step.result = result.output
                    step.status = StepStatus.SUCCEEDED
                    logger.info(
                        "Step '%s' (%s) succeeded in %.1fms",
                        step.step_id,
                        step.tool_name,
                        result.execution_time_ms,
                    )
                    return True

                last_error = result.error
                logger.warning(
                    "Step '%s' attempt %d/%d failed: %s",
                    step.step_id,
                    attempt,
                    self.max_retries,
                    result.error,
                )

                if attempt < self.max_retries:
                    wait = 0.5 * (2 ** (attempt - 1))
                    await asyncio.sleep(wait)

            except Exception as exc:
                last_error = str(exc)
                logger.error(
                    "Step '%s' attempt %d/%d raised: %s",
                    step.step_id,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        step.status = StepStatus.FAILED
        step.error = last_error
        logger.error(
            "Step '%s' (%s) failed after %d attempts: %s",
            step.step_id,
            step.tool_name,
            self.max_retries,
            last_error,
        )
        return False

    @staticmethod
    def _get_ready_steps(
        plan: ExecutionPlan,
        completed_ids: Set[str],
    ) -> List[PlanStep]:
        """
        Get steps whose dependencies are satisfied.

        Args:
            plan: The execution plan.
            completed_ids: Set of completed step IDs.

        Returns:
            List of steps ready to execute.
        """
        ready = []
        for step in plan.steps:
            if step.status != StepStatus.PENDING:
                continue
            if step.depends_on and not step.depends_on.issubset(completed_ids):
                continue
            ready.append(step)
        return ready

    @staticmethod
    def _get_blocked_steps(
        plan: ExecutionPlan,
        completed_ids: Set[str],
    ) -> List[PlanStep]:
        """
        Get steps that are pending but have unsatisfied dependencies.

        Args:
            plan: The execution plan.
            completed_ids: Set of completed step IDs.

        Returns:
            List of blocked steps.
        """
        blocked = []
        for step in plan.steps:
            if step.status != StepStatus.PENDING:
                continue
            if step.depends_on and not step.depends_on.issubset(completed_ids):
                blocked.append(step)
        return blocked
