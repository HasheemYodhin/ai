"""
Multi-step task planning for the dabba agent system.

Decomposes complex requests into executable steps,
generates execution plans, and supports re-planning on failure.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from dabba.agent.tool_schema import ToolCall
from dabba.utils.logging import get_logger

logger = get_logger("dabba.agent.planner")


class StepStatus(Enum):
    """Status of a plan step during execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """
    A single step in an execution plan.

    Args:
        step_id: Unique identifier for this step.
        description: Human-readable description of what this step does.
        tool_name: Name of the tool to call (or "reason" for LLM reasoning).
        arguments: Arguments to pass to the tool.
        depends_on: Set of step_id values that must complete first.
        status: Current execution status.
        result: Output from executing this step.
        error: Error message if the step failed.
        created_at: Timestamp when the step was created.
    """

    step_id: str = ""
    description: str = ""
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    depends_on: Set[str] = field(default_factory=set)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str = ""
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.step_id:
            self.step_id = uuid.uuid4().hex[:8]
        if not self.created_at:
            self.created_at = time.time()

    def to_tool_call(self) -> ToolCall:
        """Convert this step to a ToolCall for execution."""
        return ToolCall(
            tool_name=self.tool_name,
            arguments=self.arguments,
            call_id=self.step_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize step for display or logging."""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "tool": self.tool_name,
            "depends_on": list(self.depends_on),
            "status": self.status.value,
        }


@dataclass
class ExecutionPlan:
    """
    A complete plan consisting of multiple steps.

    Args:
        plan_id: Unique identifier for this plan.
        objective: Original user request that this plan addresses.
        steps: Ordered list of PlanStep instances.
        created_at: Timestamp when the plan was created.
        metadata: Additional plan metadata.
    """

    plan_id: str = ""
    objective: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    created_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id:
            self.plan_id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()

    @property
    def total_steps(self) -> int:
        """Total number of steps in the plan."""
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        """Number of steps that have been completed."""
        return sum(
            1 for s in self.steps
            if s.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)
        )

    @property
    def failed_steps(self) -> int:
        """Number of steps that have failed."""
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    @property
    def is_complete(self) -> bool:
        """Whether all steps have been completed or failed."""
        return all(
            s.status in (StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SKIPPED)
            for s in self.steps
        )

    @property
    def is_successful(self) -> bool:
        """Whether all steps completed successfully (none failed)."""
        return all(s.status == StepStatus.SUCCEEDED for s in self.steps)

    def get_ready_steps(self) -> List[PlanStep]:
        """
        Get steps whose dependencies are all satisfied and are pending.

        Returns:
            List of PlanStep instances ready for execution.
        """
        completed_ids = {
            s.step_id for s in self.steps
            if s.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)
        }
        ready = []
        for step in self.steps:
            if step.status != StepStatus.PENDING:
                continue
            if step.depends_on and not step.depends_on.issubset(completed_ids):
                continue
            ready.append(step)
        return ready


PlanGeneratorFn = Callable[[str, List[Dict[str, Any]]], Optional[ExecutionPlan]]


class Planner:
    """
    Decomposes complex user requests into a multi-step execution plan.

    Uses a prompt-based approach to generate plans, and can work
    with or without an LLM for plan generation.

    Args:
        plan_generator: Optional callable that generates an ExecutionPlan
            from a user request and tool descriptions. If None, uses
            the built-in template-based planner.
        max_steps: Maximum number of steps allowed in a plan.
    """

    def __init__(
        self,
        plan_generator: Optional[PlanGeneratorFn] = None,
        max_steps: int = 20,
    ):
        self._plan_generator = plan_generator
        self.max_steps = max_steps
        self._plan_history: List[ExecutionPlan] = []

    @property
    def plan_history(self) -> List[ExecutionPlan]:
        """History of all plans created by this planner."""
        return list(self._plan_history)

    def create_plan(
        self,
        objective: str,
        tool_descriptions: List[Dict[str, Any]],
    ) -> ExecutionPlan:
        """
        Create an execution plan for the given objective.

        Args:
            objective: The user's request or task description.
            tool_descriptions: List of available tool definition dicts.

        Returns:
            An ExecutionPlan instance.

        Raises:
            ValueError: If the plan could not be generated.
        """
        if self._plan_generator is not None:
            plan = self._plan_generator(objective, tool_descriptions)
            if plan is not None:
                self._plan_history.append(plan)
                logger.info(
                    "Generated plan '%s' with %d steps from custom generator",
                    plan.plan_id,
                    plan.total_steps,
                )
                return plan

        plan = self._generate_template_plan(objective, tool_descriptions)
        self._plan_history.append(plan)
        logger.info(
            "Generated plan '%s' with %d steps",
            plan.plan_id,
            plan.total_steps,
        )
        return plan

    @staticmethod
    def _is_meaningful_word(word: str) -> bool:
        """Check if a word is meaningful for matching (not a stop word)."""
        stop_words = {
            "a", "an", "the", "of", "in", "to", "for", "with", "on", "at",
            "by", "is", "it", "as", "be", "are", "was", "were", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "can", "shall", "or", "and",
            "not", "no", "but", "if", "so", "than", "that", "this", "these",
            "those", "all", "each", "every", "both", "few", "more", "most",
            "other", "some", "such", "only", "own", "same", "too", "very",
        }
        return len(word) > 2 and word not in stop_words and word.replace(".", "").isalpha()

    def _generate_template_plan(
        self,
        objective: str,
        tool_descriptions: List[Dict[str, Any]],
    ) -> ExecutionPlan:
        """
        Generate a plan using a template/rule-based approach.

        Analyzes the objective and available tools to create a
        reasonable sequence of steps. Only matches meaningful content
        words to avoid false positives from common words.

        Args:
            objective: The user's request.
            tool_descriptions: Available tools.

        Returns:
            A basic ExecutionPlan.
        """
        tools_by_name = {t.get("name", ""): t for t in tool_descriptions}
        steps: List[PlanStep] = []
        used_tools: Set[str] = set()

        objective_lower = objective.lower()
        objective_words = set(objective_lower.split())

        for tool_name, tool_def in tools_by_name.items():
            if tool_name in used_tools:
                continue

            desc = tool_def.get("description", "").lower()
            desc_words = set(desc.split())

            meaningful_desc_words = {w for w in desc_words if self._is_meaningful_word(w)}
            meaningful_obj_words = {w for w in objective_words if self._is_meaningful_word(w)}

            if meaningful_desc_words & meaningful_obj_words:
                params_schema = tool_def.get("parameters", {})
                param_names = list(params_schema.get("properties", {}).keys())
                required_params = set(params_schema.get("required", []))

                args: Dict[str, Any] = {}
                if "path" in param_names:
                    args["path"] = self._extract_path(objective)
                if "query" in param_names:
                    args["query"] = objective
                if "pattern" in param_names:
                    args["pattern"] = self._extract_pattern(objective)

                # Skip tools whose required parameters this heuristic can't fill
                # (e.g. code_explain needs 'code', todo_update needs 'id'/'status') —
                # scheduling those would guarantee a failed step. Let the LLM handle
                # those tools directly instead of pre-empting with a broken plan.
                unfillable = required_params - set(args.keys())
                if unfillable:
                    continue

                step = PlanStep(
                    description=f"Execute {tool_name} to help with: {objective[:80]}",
                    tool_name=tool_name,
                    arguments=args,
                )
                steps.append(step)
                used_tools.add(tool_name)

        return ExecutionPlan(
            objective=objective,
            steps=steps[:self.max_steps],
        )

    @staticmethod
    def _extract_path(text: str) -> str:
        """Try to extract a file path from the text."""
        path_match = re.search(
            r'(?:path|file|directory|dir)[:\s]*["\']?([^\s"\']+)["\']?',
            text,
            re.IGNORECASE,
        )
        if path_match:
            return path_match.group(1)
        return "."

    @staticmethod
    def _extract_pattern(text: str) -> str:
        """Try to extract a search pattern from the text."""
        pattern_match = re.search(
            r'(?:pattern|glob|search)[:\s]*["\']?([^\s"\']+)["\']?',
            text,
            re.IGNORECASE,
        )
        if pattern_match:
            return pattern_match.group(1)
        return "*"

    def replan(
        self,
        original_plan: ExecutionPlan,
        failed_step: PlanStep,
        tool_descriptions: List[Dict[str, Any]],
    ) -> ExecutionPlan:
        """
        Create a revised plan after a step failure.

        Marks the failed step and its dependents, then creates
        a new plan for the remaining work.

        Args:
            original_plan: The plan that encountered a failure.
            failed_step: The step that failed.
            tool_descriptions: Available tools.

        Returns:
            A new ExecutionPlan for the remaining work.
        """
        failed_step.status = StepStatus.FAILED

        for step in original_plan.steps:
            if failed_step.step_id in step.depends_on and step.status == StepStatus.PENDING:
                step.status = StepStatus.SKIPPED
                logger.info("Skipping step '%s' (depends on failed step)", step.step_id)

        remaining = [
            s for s in original_plan.steps
            if s.status == StepStatus.PENDING
        ]

        if not remaining:
            logger.info("No remaining steps after failure; returning empty plan")
            return ExecutionPlan(
                objective=original_plan.objective,
                metadata={"replan_of": original_plan.plan_id, "reason": "all steps blocked"},
            )

        new_plan = ExecutionPlan(
            objective=original_plan.objective,
            steps=remaining[:self.max_steps],
            metadata={
                "replan_of": original_plan.plan_id,
                "reason": f"Step '{failed_step.step_id}' failed: {failed_step.error}",
            },
        )
        self._plan_history.append(new_plan)
        logger.info(
            "Replan: created plan '%s' with %d remaining steps",
            new_plan.plan_id,
            new_plan.total_steps,
        )
        return new_plan

    def validate_plan(self, plan: ExecutionPlan) -> List[str]:
        """
        Validate an execution plan for correctness.

        Checks for circular dependencies, missing tools, and step limits.

        Args:
            plan: The plan to validate.

        Returns:
            List of validation warnings/errors (empty if valid).
        """
        issues: List[str] = []
        if plan.total_steps == 0:
            issues.append("Plan has zero steps")
        if plan.total_steps > self.max_steps:
            issues.append(
                f"Plan has {plan.total_steps} steps, "
                f"exceeds maximum of {self.max_steps}"
            )

        step_ids = {s.step_id for s in plan.steps}
        for step in plan.steps:
            missing_deps = step.depends_on - step_ids
            if missing_deps:
                issues.append(
                    f"Step '{step.step_id}' depends on non-existent steps: {missing_deps}"
                )

        if self._has_circular_dependency(plan.steps):
            issues.append("Plan contains circular dependencies")

        return issues

    @staticmethod
    def _has_circular_dependency(steps: List[PlanStep]) -> bool:
        """
        Check for circular dependencies in step graph.

        Uses DFS-based cycle detection.

        Args:
            steps: List of plan steps.

        Returns:
            True if a circular dependency is found.
        """
        dep_map = {s.step_id: s.depends_on for s in steps}
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def _dfs(node: str) -> bool:
            if node in rec_stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            rec_stack.add(node)
            for dep in dep_map.get(node, set()):
                if dep in dep_map:
                    if _dfs(dep):
                        return True
            rec_stack.discard(node)
            return False

        for step_id in dep_map:
            if _dfs(step_id):
                return True
        return False
