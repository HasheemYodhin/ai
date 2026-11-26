"""Unified platform endpoints for durable Dabba clients."""

from __future__ import annotations

import base64
import binascii
import asyncio
import contextlib
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from dabba.platform import (
    AgentDefinitionService,
    ApprovalService,
    SkillPackageService,
    ArtifactService,
    ConnectorRuntime,
    CoworkService,
    DocumentWorkspace,
    EvaluationService,
    IdentityService,
    MemoryService,
    TaskOrchestrator,
    ScheduledSkillService,
    WorkspaceService,
    BrowserAutomation,
    CodeIndexService,
    VerificationService,
    WorktreeService,
)
from dabba.platform.provider_gateway import ProviderGateway
from dabba.platform.skill_import import (
    SkillImportError,
    fetch_skill_markdown,
    parse_skill_markdown,
)


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TaskCreateRequest(BaseModel):
    kind: str
    request: Dict[str, Any] = Field(default_factory=dict)
    workspaceId: Optional[str] = None
    model: Optional[str] = None
    idempotencyKey: Optional[str] = None


class TaskTransitionRequest(BaseModel):
    status: str
    progress: Optional[float] = None
    currentStep: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class ApprovalCreateRequest(BaseModel):
    action: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    taskId: Optional[str] = None
    workspaceId: Optional[str] = None
    resource: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    allow: bool


class WorkspaceCreateRequest(BaseModel):
    rootPath: str
    name: Optional[str] = None


class CheckpointRequest(BaseModel):
    label: str
    taskId: Optional[str] = None
    paths: Optional[List[str]] = None


class ArtifactCreateRequest(BaseModel):
    name: str
    data: str
    mediaType: Optional[str] = None
    taskId: Optional[str] = None
    workspaceId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactPublishRequest(BaseModel):
    title: str = ""


class MemoryPutRequest(BaseModel):
    scope: str
    key: str
    content: str
    workspaceId: Optional[str] = None
    conversationId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConnectorHealthRequest(BaseModel):
    processRunning: bool
    authenticated: bool
    tools: List[str] = Field(default_factory=list)
    scopes: List[str] = Field(default_factory=list)
    readOnly: bool = True
    version: Optional[str] = None
    message: Optional[str] = None
    tokenExpiresAt: Optional[int] = None


class OAuthStartRequest(BaseModel):
    scopes: List[str] = Field(default_factory=list)
    redirectUri: str


class OAuthCompleteRequest(BaseModel):
    state: str
    token: Dict[str, Any]


class EvaluationStartRequest(BaseModel):
    suite: str
    subject: str


class EvaluationCompleteRequest(BaseModel):
    score: float
    metrics: Dict[str, Any] = Field(default_factory=dict)
    details: Dict[str, Any] = Field(default_factory=dict)


class DocumentImportRequest(BaseModel):
    name: str
    data: str
    mediaType: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentRevisionRequest(BaseModel):
    data: str
    changeSummary: str
    name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentEditRequest(BaseModel):
    replacements: Dict[str, str]
    changeSummary: Optional[str] = None


class WorktreeCreateRequest(BaseModel):
    destination: str
    branch: str
    approvalId: str


class BrowserInspectRequest(BaseModel):
    url: str


class CoworkCreateRequest(BaseModel):
    title: str
    description: str = ""
    status: str = "inbox"
    priority: str = "medium"
    assignee: Optional[str] = None
    dueAt: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    conversationId: Optional[str] = None


class CoworkUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    dueAt: Optional[int] = None
    tags: Optional[List[str]] = None
    conversationId: Optional[str] = None


class CoworkRunRequest(BaseModel):
    mode: str = "safe"
    workspacePath: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None


class CoworkSubtaskCreateRequest(BaseModel):
    title: str


class CoworkSubtaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None


class CoworkScheduleCreateRequest(BaseModel):
    cadence: str = "daily"
    intervalMinutes: Optional[int] = None
    timeOfDay: Optional[str] = None
    weekdays: List[int] = []
    mode: str = "agent"
    workspacePath: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None
    enabled: bool = True


class CoworkScheduleUpdateRequest(BaseModel):
    cadence: Optional[str] = None
    intervalMinutes: Optional[int] = None
    timeOfDay: Optional[str] = None
    weekdays: Optional[List[int]] = None
    mode: Optional[str] = None
    workspacePath: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None
    enabled: Optional[bool] = None


class SkillPackageCreateRequest(BaseModel):
    name: str
    instructions: str
    description: str = ""
    script: Optional[str] = None


class SkillImportRequest(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2048)
    content: Optional[str] = Field(default=None, max_length=512 * 1024)


class SkillPackageUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    script: Optional[str] = None


class SkillMatchRequest(BaseModel):
    message: str


class AgentDefinitionCreateRequest(BaseModel):
    name: str
    systemPrompt: str
    description: str = ""
    allowedTools: List[str] = []
    model: Optional[str] = None
    effort: Optional[str] = None


class AgentDefinitionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    systemPrompt: Optional[str] = None
    allowedTools: Optional[List[str]] = None
    model: Optional[str] = None
    effort: Optional[str] = None


class AgentDefinitionDispatchRequest(BaseModel):
    assignments: Dict[str, Dict[str, str]]  # role -> {definitionId, prompt}
    workspacePath: Optional[str] = None


class AgentDefinitionPipelineStage(BaseModel):
    definitionId: str
    promptTemplate: str  # must contain "{input}"
    outputSchema: Optional[Dict[str, Any]] = None


class AgentDefinitionPipelineRequest(BaseModel):
    stages: List[AgentDefinitionPipelineStage]
    initialInput: str = ""
    workspacePath: Optional[str] = None


class DirectoryPickRequest(BaseModel):
    initialPath: Optional[str] = None


class ScheduledSkillCreateRequest(BaseModel):
    name: str
    skillName: str
    instructions: str
    model: Optional[str] = None
    cadence: str = "daily"
    intervalMinutes: Optional[int] = None
    timeOfDay: Optional[str] = "09:00"
    weekdays: List[int] = Field(default_factory=list)
    enabled: bool = True
    nextRunAt: Optional[int] = None


class ScheduledSkillUpdateRequest(BaseModel):
    name: Optional[str] = None
    skillName: Optional[str] = None
    instructions: Optional[str] = None
    model: Optional[str] = None
    cadence: Optional[str] = None
    intervalMinutes: Optional[int] = None
    timeOfDay: Optional[str] = None
    weekdays: Optional[List[int]] = None
    enabled: Optional[bool] = None
    nextRunAt: Optional[int] = None


def _decode_base64(value: str) -> bytes:
    encoded = (
        value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    )
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 data") from exc


def _bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    return authorization.split(" ", 1)[1].strip()


def create_platform_router() -> APIRouter:
    router = APIRouter(prefix="/v1/platform", tags=["platform"])
    tasks = TaskOrchestrator()
    approvals = ApprovalService()
    identity = IdentityService()
    workspaces = WorkspaceService()
    artifacts = ArtifactService()
    memory = MemoryService()
    connectors = ConnectorRuntime()
    evaluations = EvaluationService()
    documents = DocumentWorkspace()
    providers = ProviderGateway()
    code_index = CodeIndexService()
    verification = VerificationService()
    worktrees = WorktreeService()
    browser = BrowserAutomation()
    cowork = CoworkService()
    scheduled_skills = ScheduledSkillService()
    agent_definitions = AgentDefinitionService()
    skill_packages = SkillPackageService()
    scheduler_task: Optional[asyncio.Task[Any]] = None
    background_tasks: set[asyncio.Task[Any]] = set()

    def launch(coro: Any) -> None:
        task = asyncio.create_task(coro)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    def _cowork_tool_summary(arguments: Any) -> Dict[str, str]:
        """Return useful activity details without persisting file bodies or secrets."""
        if not isinstance(arguments, dict):
            return {}
        visible = (
            "path",
            "file_path",
            "directory",
            "command",
            "query",
            "url",
            "pattern",
            "destination",
            "branch",
            "tool",
            "name",
        )
        summary: Dict[str, str] = {}
        for key in visible:
            if key in arguments and arguments[key] is not None:
                value = str(arguments[key]).replace("\n", " ").strip()
                if value:
                    summary[key] = value[:300]
        return summary

    def execute_cowork_item(item: Dict[str, Any], run: Dict[str, Any]) -> Any:
        task_record = tasks.get(run["taskId"])
        selected_model = task_record.get("model")
        selected_effort = task_record.get("request", {}).get("effort")
        description = (
            item["description"].strip() or "No additional description was supplied."
        )
        # If this item was run before, carry the previous run's summary forward
        # so a "Continue with tools" resume builds on the prior work instead of
        # starting a fresh session that has to rediscover the workspace.
        prior_summary = cowork.previous_summary(item["id"], run["userId"], run["id"])
        resume_block = (
            "\n\nThis assignment was worked on previously. Here is the summary of what was "
            "already done — continue from here, do NOT restart from scratch, and only redo "
            f"work if it is actually missing or broken:\n{prior_summary}\n"
            if prior_summary
            else ""
        )
        # Surface the user's checklist so the agent works through it in order.
        try:
            subtasks = cowork.list_subtasks(item["id"], run["userId"])
        except Exception:
            subtasks = []
        pending = [s for s in subtasks if s["status"] != "done"]
        checklist_block = (
            "\n\nWork through this checklist in order; complete every item and note which you "
            "finished in your summary:\n"
            + "\n".join(
                f"  [{'x' if s['status'] == 'done' else ' '}] {s['title']}"
                for s in subtasks
            )
            + "\n"
            if pending
            else ""
        )
        prompt = (
            "You are completing a Dabba Cowork assignment. Work autonomously and produce a concrete result.\n\n"
            f"Title: {item['title']}\nDescription: {description}\n"
            f"Priority: {item['priority']}\nTags: {', '.join(item['tags']) or 'none'}\n"
            f"{resume_block}{checklist_block}\n"
            "Use the available tools for every filesystem or implementation action. Do not claim that a "
            "file, feature, test, or command exists unless you actually created or ran it. Finish the "
            "assignment, verify the outcome where possible, and end with a concise summary of what was "
            "completed, any files or external resources created, real test results, and remaining blockers."
        )
        if run["mode"] == "safe":
            from dabba.api.agent_endpoints import _get_agent_proxy

            proxy = _get_agent_proxy()
            response = proxy._get_provider_registry().chat(
                [
                    {
                        "role": "system",
                        "content": "You are Dabba Cowork. Complete the assignment without calling tools.",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=selected_model,
                effort=selected_effort,
            )
            if str(response).lower().startswith(("i encountered an error", "error:")):
                raise RuntimeError(str(response))
            return response

        from dabba.cli.agent_proxy import AgentProxy

        proxy = AgentProxy()
        proxy.permissions.set_mode("allow")
        proxy.agent_config.require_tool_approval = False
        proxy.agent_config.max_steps = max(proxy.agent_config.max_steps, 60)
        proxy.agent_config.use_planning = False
        if selected_model:
            proxy.cli_config.default_model = selected_model
            proxy.agent_config.model_name = selected_model
        if selected_effort:
            proxy.cli_config.effort = selected_effort
        try:
            loop = proxy._ensure_agent_loop(
                run.get("workspacePath"), fresh_session=True
            )

            original_generate = loop.llm_generate

            provider_registry = proxy._get_provider_registry()
            primary_model = proxy.cli_config.default_model
            fallback_models: list[str] = []
            primary_provider = provider_registry.provider_name(primary_model)
            # Prefer a coding-capable model for a Cowork retry.  Falling back
            # from a saturated flagship model to the first arbitrary model in
            # the catalog made long implementation tasks both slow and prone
            # to emitting unusable tool syntax.
            preferred_fallbacks = (
                "poolside/laguna-xs-2.1",
                "nvidia/nemotron-3.5-lightning-30b-a3b",
                "minimaxai/minimax-m3.1-flash",
            )
            available = []
            for info in provider_registry.list_all_models():
                if info.id == primary_model or info.id in fallback_models:
                    continue
                provider, api_key = provider_registry._get_provider(info.id)
                if api_key:
                    priority = (
                        preferred_fallbacks.index(info.id)
                        if info.id in preferred_fallbacks
                        else len(preferred_fallbacks)
                    )
                    available.append(
                        (priority, info.provider != primary_provider, info.id)
                    )
            for _, _, model_id in sorted(available)[:3]:
                fallback_models.append(model_id)

            def generate_with_retry(messages: Any, parameters: Any) -> Any:
                candidates = [primary_model, *fallback_models]
                last_error: Optional[Exception] = None
                for index, candidate in enumerate(candidates):
                    try:
                        return original_generate(
                            messages, {**parameters, "model": candidate}
                        )
                    except Exception as exc:
                        last_error = exc
                        if index + 1 >= len(candidates):
                            raise
                        next_model = candidates[index + 1]
                        tasks.append_event(
                            run["taskId"],
                            "cowork.provider.fallback",
                            {
                                "model": candidate,
                                "nextModel": next_model,
                                "error": str(exc)[:500],
                            },
                        )
                        tasks.transition(
                            run["taskId"],
                            "running",
                            current_step=f"Switching model to {next_model}",
                        )
                        time.sleep(0.5)
                raise last_error or RuntimeError("No configured model was available")

            loop.llm_generate = generate_with_retry

            async def execute_with_activity(turn_prompt: str) -> str:
                responses: list[str] = []
                last_work_event = ""
                # A build-style Cowork task must not be marked done solely because a
                # model wrote a natural-language summary.  Keep an auditable record
                # of tools that actually changed the selected workspace this run.
                task_text = f"{item['title']}\n{description}".lower()
                change_request_words = (
                    "add",
                    "build",
                    "continue",
                    "create",
                    "develop",
                    "fix",
                    "implement",
                    "make",
                    "update",
                    "write",
                )
                requires_workspace_change = bool(run.get("workspacePath")) and any(
                    word in task_text for word in change_request_words
                )
                mutation_tools = {
                    "file_write",
                    "file_edit",
                    "transactional_edit",
                    "markdown_to_pdf",
                    "markdown_to_docx",
                }
                successful_mutations: list[str] = []
                successful_verifications: list[str] = []
                last_mutation_index = -1
                last_verification_index = -1
                event_index = 0
                async for chunk in loop.stream_chat(turn_prompt):
                    current = tasks.get(run["taskId"])
                    if current["status"] == "cancelled":
                        raise RuntimeError("Task was cancelled")
                    kind = chunk.get("type", "")
                    data = chunk.get("content")
                    if kind == "usage" and isinstance(data, dict):
                        step = max(1, int(data.get("step", 1)))
                        progress = min(0.82, 0.12 + step * 0.08)
                        tasks.transition(
                            run["taskId"],
                            "running",
                            progress=progress,
                            current_step=f"Agent reasoning step {step}",
                        )
                    elif kind == "text" and isinstance(data, str) and data.strip():
                        last_work_event = "text"
                        responses.append(data)
                        tasks.append_event(
                            run["taskId"],
                            "cowork.note",
                            {"content": data.strip()[:2000]},
                        )
                    elif kind == "tool_call" and isinstance(data, dict):
                        last_work_event = "tool_call"
                        tool_name = str(data.get("name") or "tool")
                        tasks.transition(
                            run["taskId"],
                            "running",
                            current_step=f"Using {tool_name}",
                        )
                        tasks.append_event(
                            run["taskId"],
                            "cowork.tool.started",
                            {
                                "tool": tool_name,
                                "arguments": _cowork_tool_summary(
                                    data.get("arguments")
                                ),
                            },
                        )
                    elif kind == "tool_result" and isinstance(data, dict):
                        last_work_event = "tool_result"
                        tool_name = str(data.get("tool") or "tool")
                        success = bool(data.get("success"))
                        event_index += 1
                        if success and tool_name in mutation_tools:
                            successful_mutations.append(tool_name)
                            last_mutation_index = event_index
                        elif success and tool_name in {
                            "file_read",
                            "file_search",
                            "code_analyze",
                            "shell_exec",
                        }:
                            # A successful inspection/test after the final write is
                            # the minimum evidence that the agent checked its work.
                            successful_verifications.append(tool_name)
                            last_verification_index = event_index
                        tasks.append_event(
                            run["taskId"],
                            "cowork.tool.finished",
                            {
                                "tool": tool_name,
                                "success": success,
                                "error": str(data.get("error") or "")[:500] or None,
                            },
                        )
                        tasks.transition(
                            run["taskId"],
                            "running",
                            current_step=(
                                f"Finished {tool_name}"
                                if success
                                else f"{tool_name} failed; reviewing result"
                            ),
                        )
                    elif kind == "error":
                        raise RuntimeError(str(data or "Cowork agent failed"))
                content = "\n\n".join(
                    part.strip() for part in responses if part.strip()
                )
                if "<tool_call>" in content.lower():
                    raise RuntimeError(
                        "The model ended with unexecuted tool calls, so Cowork did not "
                        "mark this assignment complete. Use Continue with tools to resume."
                    )
                if (
                    last_work_event in {"tool_call", "tool_result"}
                    and loop.get_metrics().get("step_count", 0) >= loop.config.max_steps
                ):
                    raise RuntimeError(
                        "Cowork reached its step limit before producing a final result. "
                        "Use Continue with tools to resume from the existing files."
                    )
                if content.lower().startswith(("i encountered an error", "error:")):
                    raise RuntimeError(content)
                if not content:
                    raise RuntimeError("Cowork ended without producing a final result")
                has_workspace_mutation = bool(
                    successful_mutations or proxy._pending_diffs
                )
                if requires_workspace_change and not has_workspace_mutation:
                    raise RuntimeError(
                        "Cowork did not make any successful file changes in the selected folder. "
                        "It was not marked complete; use Continue with tools to keep building."
                    )
                if requires_workspace_change and has_workspace_mutation:
                    # Require a read, analysis, or command after the last write.
                    # This prevents a one-file partial attempt from being presented
                    # as a verified implementation.
                    verified_after_change = bool(successful_verifications) and (
                        last_mutation_index < 0
                        or last_verification_index > last_mutation_index
                    )
                    if not verified_after_change:
                        raise RuntimeError(
                            "Cowork changed files but did not verify the changes before stopping. "
                            "It was not marked complete; use Continue with tools to verify and finish."
                        )
                return content

            # A long implementation frequently needs multiple model turns. Keep
            # the same agent context and automatically ask it to continue when a
            # turn ends with malformed tool text, a step limit, or no actual edit.
            content = ""
            turn_prompt = prompt
            recoverable = (
                "unexecuted tool calls",
                "step limit",
                "did not make any successful",
                "did not verify the changes",
            )
            for continuation in range(6):
                try:
                    content = asyncio.run(execute_with_activity(turn_prompt))
                    break
                except RuntimeError as exc:
                    message = str(exc)
                    if continuation >= 5 or not any(
                        marker in message.lower() for marker in recoverable
                    ):
                        raise
                    tasks.append_event(
                        run["taskId"],
                        "cowork.continuation",
                        {"attempt": continuation + 1, "reason": message[:500]},
                    )
                    tasks.transition(
                        run["taskId"],
                        "running",
                        progress=min(0.9, 0.72 + continuation * 0.03),
                        current_step=f"Continuing implementation (turn {continuation + 2}/6)",
                    )
                    turn_prompt = (
                        "Continue the same assignment from the current workspace state. Do not summarize "
                        "yet. Inspect the files or test output left by the previous turn, execute any "
                        "remaining tool calls using valid JSON and closing </tool_call> tags, and keep "
                        "implementing the requested milestone. Only provide a final summary after the "
                        "whole checklist is complete and verified."
                    )
            metrics = loop.get_metrics()
            return {
                "content": content,
                "toolCallCount": metrics.get("tool_call_count", 0),
                "changedFiles": list(
                    dict.fromkeys(
                        diff.get("path", "")
                        for diff in proxy._pending_diffs
                        if diff.get("path")
                    )
                ),
            }
        finally:
            proxy.close()

    def skill_executor_for(run: Dict[str, Any]) -> Callable[[str], str]:
        """Executor for one run: uses the schedule's own model (not the server's
        tiny default) and a prompt that carries today's date and earlier results."""
        schedule = scheduled_skills.get(run["scheduleId"], run["userId"])
        prompt = scheduled_skills.prompt_with_context(
            schedule, run["userId"], run["id"]
        )
        return lambda _instructions: execute_skill(prompt, schedule.get("model"))

    def execute_skill(instructions: str, model: Optional[str] = None) -> str:
        from dabba.api.agent_endpoints import _get_agent_proxy

        proxy = _get_agent_proxy()
        return proxy._get_provider_registry().chat(
            model=model or None,
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": "Run this scheduled skill now and return its result.",
                },
            ],
        )

    async def scheduler_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(scheduled_skills.dispatch_due)
                queued_runs = await asyncio.to_thread(scheduled_skills.queued_runs)
                for run in queued_runs:
                    launch(
                        asyncio.to_thread(
                            scheduled_skills.execute,
                            run["id"],
                            run["userId"],
                            skill_executor_for(run),
                        )
                    )
            except Exception:
                # Individual dispatch failures are retained by the durable task layer;
                # the scheduler itself must stay alive for later schedules.
                pass
            try:
                due_cowork = await asyncio.to_thread(cowork.dispatch_due_schedules)
                for run in due_cowork:
                    launch(
                        asyncio.to_thread(
                            cowork.execute,
                            run["id"],
                            run["userId"],
                            execute_cowork_item,
                        )
                    )
            except Exception:
                pass
            await asyncio.sleep(30)

    @router.on_event("startup")
    async def start_scheduler() -> None:
        nonlocal scheduler_task
        # Background Cowork workers do not survive a process restart. Release
        # their durable rows before serving requests, otherwise VS Code and
        # the web app only show a permanently-running task with no Stop or
        # Continue path.
        cowork.recover_orphaned_runs()
        if scheduler_task is None or scheduler_task.done():
            scheduler_task = asyncio.create_task(scheduler_loop())

    @router.on_event("shutdown")
    async def stop_scheduler() -> None:
        nonlocal scheduler_task
        if scheduler_task:
            scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler_task
            scheduler_task = None
        for task in list(background_tasks):
            task.cancel()

    def current_user(authorization: Optional[str]) -> Dict[str, Any]:
        token = _bearer(authorization)
        user = identity.authenticate(token)
        if not user:
            raise HTTPException(status_code=401, detail="Session is invalid or expired")
        return user

    @router.get("/capabilities")
    async def capabilities():
        return {
            "version": 1,
            "services": [
                "providers",
                "tasks",
                "approvals",
                "identity",
                "workspaces",
                "artifacts",
                "connectors",
                "memory",
                "evaluations",
                "telemetry",
                "documents",
                "cowork",
                "scheduled-skills",
            ],
            "taskStates": [
                "queued",
                "planning",
                "running",
                "waiting_for_approval",
                "retrying",
                "completed",
                "failed",
                "cancelled",
            ],
            "instructionFiles": ["DABBA.md", "AGENTS.md"],
            "documentFormats": [".pdf", ".docx", ".xlsx", ".pptx"],
        }

    @router.get("/cowork/items")
    async def list_cowork_items(
        status: Optional[str] = None,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return {"items": cowork.list(user["id"], status=status)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/cowork/items", status_code=201)
    async def create_cowork_item(
        body: CoworkCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return cowork.create(
                user["id"],
                body.title,
                description=body.description,
                status=body.status,
                priority=body.priority,
                assignee=body.assignee,
                due_at=body.dueAt,
                tags=body.tags,
                conversation_id=body.conversationId,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/cowork/items/{item_id}")
    async def update_cowork_item(
        item_id: str,
        body: CoworkUpdateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return cowork.update(
                item_id, user["id"], body.model_dump(exclude_unset=True)
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/cowork/items/{item_id}", status_code=204)
    async def delete_cowork_item(
        item_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            cowork.delete(item_id, user["id"])
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/cowork/items/{item_id}/activity")
    async def cowork_item_activity(
        item_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return {"activity": cowork.activity(item_id, user["id"])}
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc

    @router.get("/cowork/items/{item_id}/runs")
    async def cowork_item_runs(
        item_id: str,
        limit: int = 50,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return {"runs": cowork.runs(item_id, user["id"], limit)}
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc

    @router.get("/cowork/items/{item_id}/subtasks")
    async def list_cowork_subtasks(
        item_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return {"subtasks": cowork.list_subtasks(item_id, user["id"])}
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc

    @router.post("/cowork/items/{item_id}/subtasks", status_code=201)
    async def add_cowork_subtask(
        item_id: str,
        body: CoworkSubtaskCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return cowork.add_subtask(item_id, user["id"], body.title)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/cowork/subtasks/{subtask_id}")
    async def update_cowork_subtask(
        subtask_id: str,
        body: CoworkSubtaskUpdateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return cowork.update_subtask(
                subtask_id, user["id"], body.model_dump(exclude_unset=True)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Subtask not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/cowork/subtasks/{subtask_id}", status_code=204)
    async def delete_cowork_subtask(
        subtask_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            cowork.delete_subtask(subtask_id, user["id"])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Subtask not found") from exc

    @router.get("/cowork/items/{item_id}/schedules")
    async def list_cowork_schedules(
        item_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return {"schedules": cowork.list_schedules(item_id, user["id"])}
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc

    @router.post("/cowork/items/{item_id}/schedules", status_code=201)
    async def create_cowork_schedule(
        item_id: str,
        body: CoworkScheduleCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return cowork.create_schedule(
                item_id,
                user["id"],
                cadence=body.cadence,
                interval_minutes=body.intervalMinutes,
                time_of_day=body.timeOfDay,
                weekdays=body.weekdays,
                mode=body.mode,
                workspace_path=body.workspacePath,
                model=body.model,
                effort=body.effort,
                enabled=body.enabled,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/cowork/schedules/{schedule_id}")
    async def update_cowork_schedule(
        schedule_id: str,
        body: CoworkScheduleUpdateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return cowork.update_schedule(
                schedule_id, user["id"], body.model_dump(exclude_unset=True)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schedule not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/cowork/schedules/{schedule_id}", status_code=204)
    async def delete_cowork_schedule(
        schedule_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            cowork.delete_schedule(schedule_id, user["id"])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schedule not found") from exc

    @router.post("/cowork/items/{item_id}/runs", status_code=202)
    async def run_cowork_item(
        item_id: str,
        body: CoworkRunRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            run = cowork.dispatch(
                item_id,
                user["id"],
                mode=body.mode,
                workspace_path=body.workspacePath,
                model=body.model,
                effort=body.effort,
            )
            launch(
                asyncio.to_thread(
                    cowork.execute, run["id"], user["id"], execute_cowork_item
                )
            )
            return run
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Cowork item not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/cowork/runs/{run_id}/cancel")
    async def cancel_cowork_run(
        run_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return cowork.cancel_run(run_id, user["id"])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Cowork run not found") from exc

    def run_agent_definition(
        definition: Dict[str, Any], prompt: str, workspace_path: Optional[str] = None
    ) -> str:
        """
        Execute one prompt against a named subagent type: a fresh AgentProxy
        scoped to that definition's system prompt, tool allowlist, and model —
        run synchronously since this is called from SubagentCoordinator's
        thread pool, not the event loop.
        """
        from dabba.cli.agent_proxy import AgentProxy

        proxy = AgentProxy()
        proxy.permissions.set_mode("allow")
        proxy.agent_config.require_tool_approval = False
        proxy.agent_config.use_planning = False
        proxy.agent_config.allowed_tools = list(definition.get("allowedTools") or [])
        if definition.get("model"):
            proxy.cli_config.default_model = definition["model"]
            proxy.agent_config.model_name = definition["model"]
        if definition.get("effort"):
            proxy.cli_config.effort = definition["effort"]
        try:
            loop = proxy._ensure_agent_loop(workspace_path, fresh_session=True)
            result = loop.run(prompt, system_prompt=definition["systemPrompt"])
            return (
                result.get("response", "") if isinstance(result, dict) else str(result)
            )
        finally:
            proxy.close()

    @router.get("/skills")
    async def list_skill_packages(authorization: Optional[str] = Header(default=None)):
        user = current_user(authorization)
        return {"skills": skill_packages.list(user["id"])}

    @router.post("/skills", status_code=201)
    async def create_skill_package(
        body: SkillPackageCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return skill_packages.create(
                user["id"],
                body.name,
                body.instructions,
                description=body.description,
                script=body.script,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/skills/import", status_code=201)
    async def import_skill_package(
        body: SkillImportRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        """Create a skill from a SKILL.md file, given as text or an https link."""
        user = current_user(authorization)
        try:
            if body.content and body.content.strip():
                text = body.content
            elif body.url and body.url.strip():
                text = await asyncio.to_thread(fetch_skill_markdown, body.url)
            else:
                raise SkillImportError("Paste a SKILL.md link or choose a file")
            name, description, instructions = parse_skill_markdown(text)
        except SkillImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return skill_packages.create(
            user["id"], name, instructions, description=description
        )

    @router.patch("/skills/{skill_id}")
    async def update_skill_package(
        skill_id: str,
        body: SkillPackageUpdateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return skill_packages.update(
                skill_id, user["id"], body.model_dump(exclude_unset=True)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Skill not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/skills/{skill_id}", status_code=204)
    async def delete_skill_package(
        skill_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            skill_packages.delete(skill_id, user["id"])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Skill not found") from exc

    @router.post("/skills/match")
    async def match_skill_package(
        body: SkillMatchRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        """
        Best-matching skill for a free-text message, by relevance — lets the
        frontend auto-apply a skill's instructions instead of requiring the
        user to pick one manually every time. Returns {"skill": null} when
        nothing scores highly enough to be a confident match.
        """
        user = current_user(authorization)
        return {"skill": skill_packages.find_matching(user["id"], body.message)}

    @router.get("/agent-definitions")
    async def list_agent_definitions(
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return {"definitions": agent_definitions.list(user["id"])}

    @router.post("/agent-definitions", status_code=201)
    async def create_agent_definition(
        body: AgentDefinitionCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return agent_definitions.create(
                user["id"],
                body.name,
                body.systemPrompt,
                description=body.description,
                allowed_tools=body.allowedTools,
                model=body.model,
                effort=body.effort,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/agent-definitions/{definition_id}")
    async def update_agent_definition(
        definition_id: str,
        body: AgentDefinitionUpdateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return agent_definitions.update(
                definition_id, user["id"], body.model_dump(exclude_unset=True)
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Agent definition not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/agent-definitions/{definition_id}", status_code=204)
    async def delete_agent_definition(
        definition_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            agent_definitions.delete(definition_id, user["id"])
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Agent definition not found"
            ) from exc

    @router.post("/agent-definitions/dispatch")
    async def dispatch_agent_definitions(
        body: AgentDefinitionDispatchRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        """
        Fan out prompts to multiple named subagent types in parallel and wait
        for every result — the synchronous multi-agent-orchestration primitive
        (SubagentCoordinator) exposed over HTTP for the first time.
        """
        user = current_user(authorization)
        try:
            return await asyncio.to_thread(
                agent_definitions.dispatch_parallel,
                body.assignments,
                user["id"],
                lambda definition, prompt: run_agent_definition(
                    definition, prompt, body.workspacePath
                ),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Unknown agent definition: {exc}"
            ) from exc

    @router.post("/agent-definitions/pipeline")
    async def run_agent_definition_pipeline(
        body: AgentDefinitionPipelineRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        """
        Run named subagent types as a sequential pipeline — each stage's
        output feeds the next stage's prompt (via "{input}"), with optional
        JSON-schema validation of a stage's structured output before it's
        allowed to feed forward. A failing/invalid stage halts the pipeline.
        """
        from dabba.platform.coding import SubagentCoordinator

        user = current_user(authorization)
        stages = []
        for stage in body.stages:
            definition = agent_definitions.get(stage.definitionId, user["id"])
            stages.append(
                {
                    "role": definition["name"],
                    "prompt_template": stage.promptTemplate,
                    "output_schema": stage.outputSchema,
                    "_definition": definition,
                }
            )

        def runner(role: str, prompt: str) -> Any:
            definition = next(s["_definition"] for s in stages if s["role"] == role)
            return run_agent_definition(definition, prompt, body.workspacePath)

        try:
            plain_stages = [
                {k: v for k, v in s.items() if k != "_definition"} for s in stages
            ]
            results = await asyncio.to_thread(
                SubagentCoordinator().pipeline,
                plain_stages,
                runner,
                initial_input=body.initialInput,
            )
            return {"results": results}
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Unknown agent definition: {exc}"
            ) from exc

    @router.get("/scheduled-skills")
    async def list_scheduled_skills(
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return {"schedules": scheduled_skills.list(user["id"])}

    @router.post("/scheduled-skills", status_code=201)
    async def create_scheduled_skill(
        body: ScheduledSkillCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return scheduled_skills.create(
                user["id"],
                body.name,
                body.skillName,
                body.instructions,
                cadence=body.cadence,
                interval_minutes=body.intervalMinutes,
                time_of_day=body.timeOfDay,
                weekdays=body.weekdays,
                enabled=body.enabled,
                next_run_at=body.nextRunAt,
                model=body.model,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/scheduled-skills/{schedule_id}")
    async def update_scheduled_skill(
        schedule_id: str,
        body: ScheduledSkillUpdateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return scheduled_skills.update(
                schedule_id, user["id"], body.model_dump(exclude_unset=True)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schedule not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/scheduled-skills/{schedule_id}", status_code=204)
    async def delete_scheduled_skill(
        schedule_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            scheduled_skills.delete(schedule_id, user["id"])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schedule not found") from exc

    @router.post("/scheduled-skills/{schedule_id}/run", status_code=202)
    async def run_scheduled_skill(
        schedule_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            run = scheduled_skills.dispatch(schedule_id, user["id"])
            launch(
                asyncio.to_thread(
                    scheduled_skills.execute,
                    run["id"],
                    user["id"],
                    skill_executor_for(run),
                )
            )
            return run
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schedule not found") from exc

    @router.get("/scheduled-skills/runs")
    async def list_scheduled_skill_runs(
        scheduleId: Optional[str] = None,
        limit: int = 50,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return {
                "runs": scheduled_skills.runs(
                    user["id"], scheduleId, max(1, min(limit, 200))
                )
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Schedule not found") from exc

    @router.get("/usage")
    async def usage_summary(authorization: Optional[str] = Header(default=None)):
        """The signed-in user's token usage, totalled per model."""
        user = current_user(authorization)
        return await asyncio.to_thread(tasks.usage_summary, user["id"])

    @router.post("/identity/signup", status_code=201)
    async def signup(body: SignupRequest):
        try:
            user = identity.signup(body.name, body.email, body.password)
            session = identity.login(body.email, body.password)
            return {"user": user, **session}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/identity/login")
    async def login(body: LoginRequest):
        try:
            return identity.login(body.email, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @router.get("/identity/me")
    async def me(
        request: Request,
        response: Response,
        authorization: Optional[str] = Header(default=None),
    ):
        response.headers["Cache-Control"] = "no-store"
        return getattr(request.state, "dabba_user", None) or current_user(authorization)

    @router.post("/identity/logout")
    async def logout(authorization: Optional[str] = Header(default=None)):
        identity.logout(_bearer(authorization))
        return {"ok": True}

    @router.post("/tasks", status_code=201)
    async def create_task(
        body: TaskCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return tasks.create(
            body.kind,
            body.request,
            user_id=user["id"],
            workspace_id=body.workspaceId,
            model=body.model,
            idempotency_key=body.idempotencyKey,
        )

    @router.get("/tasks")
    async def list_tasks(
        status: Optional[str] = None,
        limit: int = 50,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return {"tasks": tasks.list(user_id=user["id"], status=status, limit=limit)}

    @router.get("/tasks/{task_id}")
    async def get_task(
        task_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        try:
            task = tasks.get(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if task["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @router.get("/tasks/{task_id}/events")
    async def task_events(
        task_id: str,
        after: int = 0,
        authorization: Optional[str] = Header(default=None),
    ):
        await get_task(task_id, authorization)
        return {"events": tasks.events(task_id, after=after)}

    @router.post("/tasks/{task_id}/transition")
    async def transition_task(
        task_id: str,
        body: TaskTransitionRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        await get_task(task_id, authorization)
        try:
            return tasks.transition(
                task_id,
                body.status,
                progress=body.progress,
                current_step=body.currentStep,
                result=body.result,
                error=body.error,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/tasks/{task_id}/cancel")
    async def cancel_task(
        task_id: str, authorization: Optional[str] = Header(default=None)
    ):
        await get_task(task_id, authorization)
        return tasks.cancel(task_id)

    @router.post("/tasks/{task_id}/resume")
    async def resume_task(
        task_id: str, authorization: Optional[str] = Header(default=None)
    ):
        await get_task(task_id, authorization)
        return tasks.resume(task_id)

    @router.post("/approvals", status_code=201)
    async def create_approval(
        body: ApprovalCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return approvals.request(
            body.action,
            body.arguments,
            task_id=body.taskId,
            user_id=user["id"],
            workspace_id=body.workspaceId,
            resource=body.resource,
        )

    @router.post("/approvals/{approval_id}/decision")
    async def decide_approval(
        approval_id: str,
        body: ApprovalDecisionRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            approval = approvals.get(approval_id)
            if approval["userId"] != user["id"]:
                raise KeyError(approval_id)
            return approvals.decide(approval_id, body.allow, user["id"])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Approval not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/workspaces", status_code=201)
    async def create_workspace(
        body: WorkspaceCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return workspaces.register(
                body.rootPath, name=body.name, user_id=user["id"]
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/filesystem/directories")
    async def browse_directories(
        path: Optional[str] = None,
        authorization: Optional[str] = Header(default=None),
    ):
        current_user(authorization)
        try:
            return workspaces.browse_directories(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/filesystem/pick-directory")
    async def pick_directory(
        body: DirectoryPickRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        current_user(authorization)
        try:
            return await asyncio.to_thread(workspaces.pick_directory, body.initialPath)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

    @router.get("/workspaces/{workspace_id}/instructions")
    async def workspace_instructions(
        workspace_id: str,
        path: str = "",
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        workspace = workspaces.get(workspace_id)
        if workspace["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return {"instructions": workspaces.instructions_for(workspace_id, path)}

    @router.post("/workspaces/{workspace_id}/checkpoints", status_code=201)
    async def create_checkpoint(
        workspace_id: str,
        body: CheckpointRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        await workspace_instructions(workspace_id, "", authorization)
        return workspaces.checkpoint(
            workspace_id, label=body.label, task_id=body.taskId, paths=body.paths
        )

    @router.post("/workspaces/{workspace_id}/index")
    async def index_workspace(
        workspace_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        workspace = workspaces.get(workspace_id)
        if workspace["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return code_index.index(workspace_id, workspace["rootPath"])

    @router.get("/workspaces/{workspace_id}/symbols")
    async def search_symbols(
        workspace_id: str,
        query: str,
        limit: int = 50,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        workspace = workspaces.get(workspace_id)
        if workspace["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return {"symbols": code_index.search(workspace_id, query, limit)}

    @router.post("/workspaces/{workspace_id}/verify")
    async def verify_workspace(
        workspace_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        workspace = workspaces.get(workspace_id)
        if workspace["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return verification.run(workspace["rootPath"])

    @router.post("/workspaces/{workspace_id}/worktrees", status_code=201)
    async def create_worktree(
        workspace_id: str,
        body: WorktreeCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        workspace = workspaces.get(workspace_id)
        if workspace["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Workspace not found")
        approval = approvals.get(body.approvalId)
        if (
            approval["userId"] != user["id"]
            or approval["workspaceId"] != workspace_id
            or approval["action"] != "worktree_create"
            or approval["status"] != "approved"
        ):
            raise HTTPException(
                status_code=403, detail="An approved worktree_create action is required"
            )
        return worktrees.create(workspace["rootPath"], body.destination, body.branch)

    @router.post("/browser/inspect")
    async def inspect_browser(
        body: BrowserInspectRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        if not body.url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400, detail="Browser URL must use http or https"
            )
        screenshot = (
            artifacts.root / "browser-runs" / f"{user['id']}-{len(body.url)}.png"
        )
        try:
            result = browser.inspect(body.url, str(screenshot))
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        artifact = artifacts.store_bytes(
            screenshot.name,
            screenshot.read_bytes(),
            media_type="image/png",
            user_id=user["id"],
            metadata={"sourceUrl": body.url, "browserValidation": True},
        )
        screenshot.unlink(missing_ok=True)
        return {**result, "screenshotArtifact": artifact}

    @router.get("/checkpoints/{checkpoint_id}/diff")
    async def checkpoint_diff(
        checkpoint_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        try:
            checkpoint = workspaces.checkpoint_info(checkpoint_id)
            workspace = workspaces.get(checkpoint["workspace_id"])
            if workspace["userId"] != user["id"]:
                raise KeyError(checkpoint_id)
            return workspaces.diff(checkpoint_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/checkpoints/{checkpoint_id}/rollback")
    async def checkpoint_rollback(
        checkpoint_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        try:
            checkpoint = workspaces.checkpoint_info(checkpoint_id)
            workspace = workspaces.get(checkpoint["workspace_id"])
            if workspace["userId"] != user["id"]:
                raise KeyError(checkpoint_id)
            return workspaces.rollback(checkpoint_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/artifacts", status_code=201)
    async def create_artifact(
        body: ArtifactCreateRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return artifacts.store_bytes(
            body.name,
            _decode_base64(body.data),
            media_type=body.mediaType,
            task_id=body.taskId,
            user_id=user["id"],
            workspace_id=body.workspaceId,
            metadata=body.metadata,
        )

    @router.get("/artifacts/{artifact_id}/download")
    async def download_artifact(
        artifact_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        artifact = artifacts.get(artifact_id)
        if artifact["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return FileResponse(
            artifact["path"],
            media_type=artifact["mediaType"],
            filename=artifact["name"],
        )

    @router.post("/artifacts/{artifact_id}/publish", status_code=201)
    async def publish_artifact(
        artifact_id: str,
        body: ArtifactPublishRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        """Mint a public, unauthenticated share URL for an artifact you own."""
        user = current_user(authorization)
        try:
            published = artifacts.publish(artifact_id, user["id"], body.title)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            **published,
            "url": f"/v1/platform/public/artifacts/{published['slug']}",
        }

    @router.get("/artifacts/published")
    async def list_published_artifacts(
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return {"published": artifacts.list_published(user["id"])}

    @router.delete("/artifacts/publish/{slug}", status_code=204)
    async def unpublish_artifact(
        slug: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        try:
            artifacts.unpublish(slug, user["id"])
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Published artifact not found"
            ) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.get("/public/artifacts/{slug}")
    async def serve_published_artifact(slug: str):
        """
        No authorization check — this is the whole point: a real standalone
        page anyone with the link can open, same as the artifact preview
        panel renders in-app, just persisted and given a stable public URL.
        """
        try:
            published = artifacts.get_published(slug)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="This link doesn't point to a published artifact",
            ) from exc
        artifact = published["artifact"]
        return FileResponse(
            artifact["path"],
            media_type=artifact["mediaType"],
            headers={
                "Content-Security-Policy": "sandbox allow-scripts",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.put("/memory")
    async def put_memory(
        body: MemoryPutRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        try:
            return memory.put(
                body.scope,
                body.key,
                body.content,
                user_id=user["id"],
                workspace_id=body.workspaceId,
                conversation_id=body.conversationId,
                metadata=body.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/memory")
    async def list_memory(
        scope: Optional[str] = None,
        workspace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return {
            "memories": memory.list(
                scope=scope,
                user_id=user["id"],
                workspace_id=workspace_id,
                conversation_id=conversation_id,
            )
        }

    @router.delete("/memory/{memory_id}", status_code=204)
    async def delete_memory(
        memory_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        try:
            memory.delete(memory_id, user["id"])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Memory not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.get("/connectors")
    async def list_connectors(authorization: Optional[str] = Header(default=None)):
        current_user(authorization)
        return {"connectors": connectors.list()}

    @router.put("/connectors/{name}/health")
    async def connector_health(
        name: str,
        body: ConnectorHealthRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        current_user(authorization)
        return connectors.record_health(
            name,
            process_running=body.processRunning,
            authenticated=body.authenticated,
            tools=body.tools,
            scopes=body.scopes,
            read_only=body.readOnly,
            version=body.version,
            message=body.message,
            token_expires_at=body.tokenExpiresAt,
        )

    @router.post("/connectors/{name}/oauth/start")
    async def start_connector_oauth(
        name: str,
        body: OAuthStartRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return connectors.begin_oauth(
            name,
            scopes=body.scopes,
            redirect_uri=body.redirectUri,
            user_id=user["id"],
        )

    @router.post("/connectors/oauth/complete")
    async def complete_connector_oauth(
        body: OAuthCompleteRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        current_user(authorization)
        try:
            return connectors.complete_oauth(body.state, body.token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/evaluations", status_code=201)
    async def start_evaluation(
        body: EvaluationStartRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        current_user(authorization)
        return evaluations.start(body.suite, body.subject)

    @router.post("/evaluations/{evaluation_id}/complete")
    async def complete_evaluation(
        evaluation_id: str,
        body: EvaluationCompleteRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        current_user(authorization)
        return evaluations.complete(
            evaluation_id,
            score=body.score,
            metrics=body.metrics,
            details=body.details,
        )

    @router.get("/providers/health")
    async def provider_health(authorization: Optional[str] = Header(default=None)):
        current_user(authorization)
        return {"providers": providers.health()}

    @router.post("/documents", status_code=201)
    async def import_document(
        body: DocumentImportRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        return documents.import_bytes(
            body.name,
            _decode_base64(body.data),
            user_id=user["id"],
            media_type=body.mediaType,
            metadata=body.metadata,
        )

    @router.post("/documents/{document_id}/revisions", status_code=201)
    async def revise_document(
        document_id: str,
        body: DocumentRevisionRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        latest = documents.latest(document_id)
        if latest["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Document not found")
        return documents.add_revision(
            document_id,
            _decode_base64(body.data),
            change_summary=body.changeSummary,
            name=body.name,
            metadata=body.metadata,
        )

    @router.post("/documents/{document_id}/edit", status_code=201)
    async def edit_document(
        document_id: str,
        body: DocumentEditRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        user = current_user(authorization)
        latest = documents.latest(document_id)
        if latest["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Document not found")
        try:
            return documents.edit(
                document_id,
                body.replacements,
                change_summary=body.changeSummary,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/documents/{document_id}/versions")
    async def document_versions(
        document_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        versions = documents.versions(document_id)
        if not versions or versions[0]["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"versions": versions}

    @router.get("/document-versions/{version_id}/download")
    async def download_document_version(
        version_id: str, authorization: Optional[str] = Header(default=None)
    ):
        user = current_user(authorization)
        version = documents.get_version(version_id)
        if version["userId"] != user["id"]:
            raise HTTPException(status_code=404, detail="Document version not found")
        return FileResponse(
            version["path"],
            media_type=version["mediaType"],
            filename=version["name"],
        )

    return router
