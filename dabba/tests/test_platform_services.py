import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from dabba.platform.coding import CodeIndexService
from dabba.platform.core import PlatformStore
from dabba.platform.provider_gateway import ProviderFailure, ProviderGateway
from dabba.platform.services import (
    ApprovalService,
    ArtifactService,
    ConnectorRuntime,
    CoworkService,
    DocumentWorkspace,
    IdentityService,
    SecretVault,
    ScheduledSkillService,
    TaskOrchestrator,
    WorkspaceService,
)
from dabba.tools.file_tools import transactional_edit


@pytest.fixture()
def store(tmp_path):
    return PlatformStore(tmp_path / "platform.db")


def test_task_state_machine_and_event_replay(store):
    tasks = TaskOrchestrator(store)
    task = tasks.create("coding", {"prompt": "fix tests"}, idempotency_key="same")
    duplicate = tasks.create("coding", {"prompt": "ignored"}, idempotency_key="same")
    assert duplicate["id"] == task["id"]

    tasks.transition(task["id"], "running", progress=0.25, current_step="Inspecting")
    completed = tasks.transition(task["id"], "completed", result={"files": 2})

    assert completed["progress"] == 1
    assert [event["type"] for event in tasks.events(task["id"])] == [
        "task.created",
        "task.running",
        "task.completed",
    ]
    with pytest.raises(ValueError, match="Invalid task transition"):
        tasks.transition(task["id"], "running")


def test_server_identity_sessions_are_hashed_and_revocable(store):
    identity = IdentityService(store)
    user = identity.signup("Hasheem", "hasheem@example.com", "a-secure-password")
    session = identity.login("hasheem@example.com", "a-secure-password")

    assert identity.authenticate(session["token"])["id"] == user["id"]
    row = store.fetchone("SELECT password_hash FROM users WHERE id=?", (user["id"],))
    assert "a-secure-password" not in row["password_hash"]

    identity.logout(session["token"])
    assert identity.authenticate(session["token"]) is None


def test_critical_actions_always_require_approval(store):
    approvals = ApprovalService(store)
    assert approvals.requires_approval("delete", mode="auto")
    request = approvals.request("file_write", {"path": "app.py"}, user_id="user")
    decision = approvals.decide(request["id"], True, "user")
    assert decision["status"] == "approved"


def test_encrypted_secret_vault_and_oauth_state(store, tmp_path, monkeypatch):
    monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path / "data"))
    vault = SecretVault(store)
    vault.put("provider", "nvidia", "nvapi-secret")
    row = store.fetchone(
        "SELECT ciphertext FROM encrypted_secrets WHERE owner='provider' AND secret_key='nvidia'"
    )
    assert b"nvapi-secret" not in row["ciphertext"]
    assert vault.get("provider", "nvidia") == "nvapi-secret"

    connectors = ConnectorRuntime(store)
    oauth = connectors.begin_oauth(
        "github",
        scopes=["repo:read"],
        redirect_uri="http://localhost/callback",
        user_id="user",
    )
    completed = connectors.complete_oauth(
        oauth["state"],
        {"access_token": "connector-secret", "expires_in": 3600},
        vault=vault,
    )
    assert completed["stored"] is True
    assert "connector-secret" in vault.get("connector:github", "oauth_token")


def test_provider_gateway_opens_circuit_and_normalizes_capacity(store):
    gateway = ProviderGateway(
        store, max_attempts=1, failure_threshold=2, cooldown_seconds=60
    )

    def fail(_model):
        raise RuntimeError("ResourceExhausted: worker request limit reached")

    for _ in range(2):
        with pytest.raises(ProviderFailure) as captured:
            gateway.run("model", fail, provider_for=lambda _: "nvidia")
        assert captured.value.code in {"provider_capacity", "provider_circuit_open"}

    health = gateway.health()[0]
    assert health["state"] == "open"
    assert (
        health["lastErrorMessage"] == "The selected model is temporarily at capacity."
    )


def test_transactional_multi_file_edit_and_preflight_rollback(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("name = 'old'\n")
    second.write_text("value = 'keep'\n")

    with pytest.raises(ValueError):
        transactional_edit(
            str(tmp_path),
            [
                {"path": "first.py", "old_string": "old", "new_string": "new"},
                {"path": "second.py", "old_string": "missing", "new_string": "new"},
            ],
        )
    assert first.read_text() == "name = 'old'\n"

    result = transactional_edit(
        str(tmp_path),
        [
            {"path": "first.py", "old_string": "old", "new_string": "new"},
            {"path": "second.py", "old_string": "keep", "new_string": "changed"},
        ],
    )
    assert result["files_changed"] == 2
    assert "new" in first.read_text()


def test_nested_repository_instructions_and_symbol_index(store, tmp_path):
    root = tmp_path / "repo"
    nested = root / "src" / "feature"
    nested.mkdir(parents=True)
    (root / "DABBA.md").write_text("Root rule")
    (root / "src" / "AGENTS.md").write_text("Nested rule")
    source = nested / "service.py"
    source.write_text(
        "import json\n\ndef execute(value):\n    return json.dumps(value)\n"
    )

    workspaces = WorkspaceService(store)
    workspace = workspaces.register(str(root), user_id="user")
    instructions = workspaces.instructions_for(
        workspace["id"], "src/feature/service.py"
    )
    assert [Path(item["path"]).name for item in instructions] == [
        "DABBA.md",
        "AGENTS.md",
    ]

    index = CodeIndexService(store)
    summary = index.index(workspace["id"], str(root))
    assert summary["symbols"] == 1
    assert (
        index.search(workspace["id"], "execute")[0]["path"] == "src/feature/service.py"
    )


def test_docx_original_and_format_preserving_revision(store, tmp_path, monkeypatch):
    monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path / "data"))
    from docx import Document

    document = Document()
    document.add_heading("ASHIN ROSHEK C", level=1)
    document.add_paragraph("Original content")
    buffer = io.BytesIO()
    document.save(buffer)

    workspace = DocumentWorkspace(store)
    original = workspace.import_bytes("report.docx", buffer.getvalue(), user_id="user")
    edited = workspace.edit(
        original["documentId"],
        {"ASHIN ROSHEK C": "Hasheem"},
        change_summary="Updated student name",
    )

    assert original["version"] == 1
    assert edited["version"] == 2
    assert Path(original["path"]).read_bytes() == buffer.getvalue()
    revised = Document(edited["path"])
    assert revised.paragraphs[0].text == "Hasheem"


def test_cowork_items_are_user_scoped_and_audited(store):
    identity = IdentityService(store)
    first = identity.signup("First", "first@example.com", "a-secure-password")
    second = identity.signup("Second", "second@example.com", "a-secure-password")
    cowork = CoworkService(store)

    item = cowork.create(
        first["id"], "Prepare release", priority="high", tags=["release"]
    )
    updated = cowork.update(item["id"], first["id"], {"status": "in_progress"})

    assert updated["status"] == "in_progress"
    assert [
        event["eventType"] for event in cowork.activity(item["id"], first["id"])
    ] == [
        "updated",
        "created",
    ]
    assert cowork.list(second["id"]) == []
    with pytest.raises(KeyError):
        cowork.get(item["id"], second["id"])


def test_cowork_agent_run_completes_item_and_persists_output(
    store, tmp_path, monkeypatch
):
    monkeypatch.setenv("DABBA_WORKSPACE_ROOTS", str(tmp_path))
    identity = IdentityService(store)
    user = identity.signup("Cowork", "cowork@example.com", "a-secure-password")
    cowork = CoworkService(store)
    item = cowork.create(
        user["id"],
        "Create a release note",
        description="Summarize version 2",
        status="planned",
        assignee="Dabba",
    )

    run = cowork.dispatch(
        item["id"], user["id"], mode="agent", workspace_path=str(tmp_path)
    )
    completed = cowork.execute(
        run["id"],
        user["id"],
        lambda assignment, context: (
            f"Completed {assignment['title']} in {context['workspacePath']}"
        ),
    )

    assert completed["status"] == "completed"
    assert "Create a release note" in completed["output"]["content"]
    assert cowork.get(item["id"], user["id"])["status"] == "done"
    assert cowork.runs(item["id"], user["id"])[0]["taskId"] == run["taskId"]


def test_cowork_previous_summary_carries_forward(store, tmp_path, monkeypatch):
    monkeypatch.setenv("DABBA_WORKSPACE_ROOTS", str(tmp_path))
    identity = IdentityService(store)
    user = identity.signup("Cowork", "cowork@example.com", "a-secure-password")
    cowork = CoworkService(store)
    item = cowork.create(
        user["id"], "Build the app", status="planned", assignee="Dabba"
    )

    # First run finishes with a summary.
    run1 = cowork.dispatch(
        item["id"], user["id"], mode="agent", workspace_path=str(tmp_path)
    )
    cowork.execute(
        run1["id"],
        user["id"],
        lambda a, c: {"content": "Created models and API; tests not written yet."},
    )

    # A fresh run should see the previous run's summary, but not its own.
    run2 = cowork.dispatch(
        item["id"], user["id"], mode="agent", workspace_path=str(tmp_path)
    )
    summary = cowork.previous_summary(item["id"], user["id"], run2["id"])
    assert summary == "Created models and API; tests not written yet."

    # The very first run had no prior summary.
    assert cowork.previous_summary(item["id"], user["id"], run1["id"]) is None


def test_cowork_subtasks_crud_and_scoping(store):
    identity = IdentityService(store)
    owner = identity.signup("Owner", "owner@example.com", "a-secure-password")
    other = identity.signup("Other", "other@example.com", "a-secure-password")
    cowork = CoworkService(store)
    item = cowork.create(owner["id"], "Build feature")

    a = cowork.add_subtask(item["id"], owner["id"], "Write models")
    b = cowork.add_subtask(item["id"], owner["id"], "Write tests")
    assert [s["title"] for s in cowork.list_subtasks(item["id"], owner["id"])] == [
        "Write models",
        "Write tests",
    ]
    assert a["position"] == 0 and b["position"] == 1

    done = cowork.update_subtask(a["id"], owner["id"], {"status": "done"})
    assert done["status"] == "done"

    with pytest.raises(ValueError):
        cowork.update_subtask(a["id"], owner["id"], {"status": "bogus"})
    with pytest.raises(KeyError):
        cowork.list_subtasks(item["id"], other["id"])  # ownership enforced

    cowork.delete_subtask(b["id"], owner["id"])
    assert len(cowork.list_subtasks(item["id"], owner["id"])) == 1


def test_cowork_schedule_dispatches_when_due(store, tmp_path, monkeypatch):
    monkeypatch.setenv("DABBA_WORKSPACE_ROOTS", str(tmp_path))
    identity = IdentityService(store)
    user = identity.signup("Cowork", "cowork@example.com", "a-secure-password")
    cowork = CoworkService(store)
    item = cowork.create(
        user["id"], "Nightly check", status="planned", assignee="Dabba"
    )

    sched = cowork.create_schedule(
        item["id"],
        user["id"],
        cadence="interval",
        interval_minutes=60,
        mode="agent",
        workspace_path=str(tmp_path),
    )
    # Not due yet (next_run is ~60 min out).
    assert cowork.dispatch_due_schedules() == []

    # Force it due and confirm it dispatches a run and advances next_run_at.
    with store.transaction() as conn:
        conn.execute(
            "UPDATE cowork_schedules SET next_run_at=? WHERE id=?", (0, sched["id"])
        )
    dispatched = cowork.dispatch_due_schedules()
    assert len(dispatched) == 1
    assert dispatched[0]["itemId"] == item["id"]
    refreshed = cowork.list_schedules(item["id"], user["id"])[0]
    assert refreshed["nextRunAt"] > 0
    assert refreshed["lastStatus"] == "queued"

    # With a run already active, a second due tick is skipped (not errored).
    with store.transaction() as conn:
        conn.execute(
            "UPDATE cowork_schedules SET next_run_at=? WHERE id=?", (0, sched["id"])
        )
    assert cowork.dispatch_due_schedules() == []
    assert cowork.list_schedules(item["id"], user["id"])[0]["lastStatus"] == "skipped"


def test_agent_definition_crud_and_scoping(store):
    from dabba.platform.services import AgentDefinitionService

    identity = IdentityService(store)
    owner = identity.signup("Owner", "owner2@example.com", "a-secure-password")
    other = identity.signup("Other", "other2@example.com", "a-secure-password")
    defs = AgentDefinitionService(store)

    created = defs.create(
        owner["id"],
        "Reviewer",
        "You are a strict code reviewer.",
        description="Reviews diffs",
        allowed_tools=["file_read", "code_analyze"],
        model="claude-sonnet-5",
        effort="high",
    )
    assert created["name"] == "Reviewer"
    assert created["allowedTools"] == ["file_read", "code_analyze"]

    updated = defs.update(
        created["id"], owner["id"], {"effort": "max", "allowedTools": ["file_read"]}
    )
    assert updated["effort"] == "max"
    assert updated["allowedTools"] == ["file_read"]

    assert [d["id"] for d in defs.list(owner["id"])] == [created["id"]]
    assert defs.list(other["id"]) == []
    with pytest.raises(KeyError):
        defs.get(created["id"], other["id"])

    with pytest.raises(ValueError):
        defs.create(owner["id"], "", "also required")

    defs.delete(created["id"], owner["id"])
    assert defs.list(owner["id"]) == []


def test_agent_definition_dispatch_parallel_resolves_definitions_per_role(store):
    from dabba.platform.services import AgentDefinitionService

    identity = IdentityService(store)
    owner = identity.signup("Owner", "owner3@example.com", "a-secure-password")
    defs = AgentDefinitionService(store)
    reviewer = defs.create(
        owner["id"], "Reviewer", "Review code.", allowed_tools=["file_read"]
    )
    writer = defs.create(
        owner["id"], "Writer", "Write code.", allowed_tools=["file_write"]
    )

    calls = []

    def run_one(definition, prompt):
        calls.append((definition["name"], prompt))
        return f"{definition['name']} did: {prompt}"

    results = defs.dispatch_parallel(
        {
            "review": {"definitionId": reviewer["id"], "prompt": "check auth.py"},
            "write": {"definitionId": writer["id"], "prompt": "add a test"},
        },
        owner["id"],
        run_one,
    )
    assert results["review"] == {
        "success": True,
        "result": "Reviewer did: check auth.py",
    }
    assert results["write"] == {"success": True, "result": "Writer did: add a test"}
    assert sorted(calls) == [("Reviewer", "check auth.py"), ("Writer", "add a test")]


def test_skill_package_crud_and_scoping(store):
    from dabba.platform.services import SkillPackageService

    identity = IdentityService(store)
    owner = identity.signup("Owner", "owner4@example.com", "a-secure-password")
    other = identity.signup("Other", "other4@example.com", "a-secure-password")
    skills = SkillPackageService(store)

    created = skills.create(
        owner["id"],
        "Release Notes",
        "Summarize commits into release notes.",
        description="Writes release notes from a diff",
        script="git log --oneline",
    )
    assert created["name"] == "Release Notes"
    assert created["script"] == "git log --oneline"

    updated = skills.update(created["id"], owner["id"], {"description": "Updated desc"})
    assert updated["description"] == "Updated desc"

    assert [s["id"] for s in skills.list(owner["id"])] == [created["id"]]
    assert skills.list(other["id"]) == []
    with pytest.raises(KeyError):
        skills.get(created["id"], other["id"])
    with pytest.raises(ValueError):
        skills.create(owner["id"], "", "also required")

    skills.delete(created["id"], owner["id"])
    assert skills.list(owner["id"]) == []


def test_skill_package_find_matching_auto_triggers_by_relevance(store):
    from dabba.platform.services import SkillPackageService

    identity = IdentityService(store)
    owner = identity.signup("Owner", "owner5@example.com", "a-secure-password")
    skills = SkillPackageService(store)
    skills.create(
        owner["id"], "Release Notes", "Summarize git commits into release notes."
    )
    skills.create(
        owner["id"], "Bug Triage", "Classify and prioritize incoming bug reports."
    )

    match = skills.find_matching(
        owner["id"], "please write release notes from these commits"
    )
    assert match is not None and match["name"] == "Release Notes"

    match = skills.find_matching(owner["id"], "help me triage this bug report")
    assert match is not None and match["name"] == "Bug Triage"

    # Generic, unrelated message shouldn't spuriously match anything.
    assert skills.find_matching(owner["id"], "what time is it") is None


def test_artifact_publish_and_unpublish_flow(store):
    identity = IdentityService(store)
    owner = identity.signup("Owner", "owner6@example.com", "a-secure-password")
    other = identity.signup("Other", "other6@example.com", "a-secure-password")
    artifacts = ArtifactService(store)

    artifact = artifacts.store_bytes(
        "page.html",
        b"<!doctype html><html><body>hi</body></html>",
        media_type="text/html",
        user_id=owner["id"],
    )

    published = artifacts.publish(artifact["id"], owner["id"], "My Page")
    assert published["title"] == "My Page"
    assert published["artifact"]["id"] == artifact["id"]

    fetched = artifacts.get_published(published["slug"])
    assert fetched["artifact"]["path"] == artifact["path"]

    assert [p["slug"] for p in artifacts.list_published(owner["id"])] == [
        published["slug"]
    ]
    assert artifacts.list_published(other["id"]) == []

    with pytest.raises(PermissionError):
        artifacts.publish(artifact["id"], other["id"], "Stolen")
    with pytest.raises(PermissionError):
        artifacts.unpublish(published["slug"], other["id"])
    with pytest.raises(KeyError):
        artifacts.get_published("nonexistent-slug")

    artifacts.unpublish(published["slug"], owner["id"])
    with pytest.raises(KeyError):
        artifacts.get_published(published["slug"])


def test_memory_delete_enforces_ownership(store):
    from dabba.platform.services import MemoryService

    identity = IdentityService(store)
    owner = identity.signup("Owner", "owner7@example.com", "a-secure-password")
    other = identity.signup("Other", "other7@example.com", "a-secure-password")
    memory = MemoryService(store)

    memory.put("preference", "favorite-language", "Python", user_id=owner["id"])
    listed = memory.list(scope="preference", user_id=owner["id"])
    assert len(listed) == 1 and listed[0]["content"] == "Python"
    memory_id = listed[0]["id"]

    with pytest.raises(PermissionError):
        memory.delete(memory_id, other["id"])
    with pytest.raises(KeyError):
        memory.delete("nonexistent-id", owner["id"])

    memory.delete(memory_id, owner["id"])
    assert memory.list(scope="preference", user_id=owner["id"]) == []


def test_workspace_folder_browser_is_contained_to_configured_roots(
    store, tmp_path, monkeypatch
):
    root = tmp_path / "allowed"
    child = root / "project"
    hidden = root / ".secret"
    child.mkdir(parents=True)
    hidden.mkdir()
    monkeypatch.setenv("DABBA_WORKSPACE_ROOTS", str(root))
    workspaces = WorkspaceService(store)

    roots = workspaces.browse_directories()
    listing = workspaces.browse_directories(str(root))

    assert roots["roots"] == [{"name": "allowed", "path": str(root)}]
    assert listing["directories"] == [{"name": "project", "path": str(child)}]
    assert listing["parent"] is None
    with pytest.raises(ValueError, match="outside the allowed"):
        workspaces.browse_directories(str(tmp_path))


def test_native_workspace_picker_returns_validated_selected_folder(
    store, tmp_path, monkeypatch
):
    root = tmp_path / "allowed"
    selected = root / "chosen"
    selected.mkdir(parents=True)
    monkeypatch.setenv("DABBA_WORKSPACE_ROOTS", str(root))
    monkeypatch.setattr(
        "dabba.platform.services.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "zenity" else None,
    )
    monkeypatch.setattr(
        "dabba.platform.services.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{selected}\n"),
    )

    result = WorkspaceService(store).pick_directory(str(root))

    assert result == {"cancelled": False, "path": str(selected)}


def test_cowork_prevents_duplicate_active_runs_and_can_cancel(store):
    identity = IdentityService(store)
    user = identity.signup(
        "Cowork Cancel", "cowork-cancel@example.com", "a-secure-password"
    )
    cowork = CoworkService(store)
    item = cowork.create(user["id"], "Long assignment")
    run = cowork.dispatch(
        item["id"], user["id"], model="configured-model", effort="high"
    )
    task = cowork.tasks.get(run["taskId"])
    assert task["model"] == "configured-model"
    assert task["request"]["effort"] == "high"

    with pytest.raises(ValueError, match="already running"):
        cowork.dispatch(item["id"], user["id"])
    with pytest.raises(ValueError, match="Cancel the active"):
        cowork.delete(item["id"], user["id"])

    cancelled = cowork.cancel_run(run["id"], user["id"])
    assert cancelled["status"] == "cancelled"
    assert cowork.get(item["id"], user["id"])["status"] == "planned"
    assert (
        cowork.execute(
            run["id"], user["id"], lambda *_: pytest.fail("cancelled run executed")
        )["status"]
        == "cancelled"
    )


def test_cowork_releases_runs_orphaned_by_server_restart(store):
    identity = IdentityService(store)
    user = identity.signup(
        "Cowork Recovery", "cowork-recovery@example.com", "a-secure-password"
    )
    cowork = CoworkService(store)
    item = cowork.create(user["id"], "Fix the workspace", status="planned")
    run = cowork.dispatch(item["id"], user["id"], mode="agent")

    assert cowork.recover_orphaned_runs() == 1

    recovered = cowork.get_run(run["id"], user["id"])
    assert recovered["status"] == "failed"
    assert "server restart" in recovered["error"].lower()
    assert cowork.tasks.get(run["taskId"])["status"] == "failed"
    assert cowork.get(item["id"], user["id"])["status"] == "planned"
    # The old run must not prevent the user from continuing the item.
    assert cowork.dispatch(item["id"], user["id"], mode="agent")["status"] == "queued"


def test_scheduled_skill_dispatch_and_execution_history(store):
    identity = IdentityService(store)
    user = identity.signup("Scheduler", "scheduler@example.com", "a-secure-password")
    schedules = ScheduledSkillService(store)
    schedule = schedules.create(
        user["id"],
        "Daily brief",
        "Brief",
        "Summarize project status",
        cadence="interval",
        interval_minutes=5,
    )

    run = schedules.dispatch(schedule["id"], user["id"])
    completed = schedules.execute(
        run["id"], user["id"], lambda prompt: f"Done: {prompt}"
    )

    assert completed["status"] == "completed"
    assert completed["output"]["content"] == "Done: Summarize project status"
    assert schedules.get(schedule["id"], user["id"])["lastStatus"] == "completed"
