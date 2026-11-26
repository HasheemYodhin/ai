"""SQLite persistence and shared helpers for Dabba platform services."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from dabba.utils.paths import get_dabba_config_dir


def utc_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: Optional[str], default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def get_platform_data_dir() -> Path:
    """Return the overrideable root for mutable platform state."""
    configured = os.environ.get("DABBA_DATA_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else get_dabba_config_dir()
    )


def get_workspace_roots() -> list[Path]:
    """Directories exposed to authenticated workspace pickers and Cowork agents."""
    configured = os.environ.get("DABBA_WORKSPACE_ROOTS", "")
    candidates = (
        [Path(value) for value in configured.split(os.pathsep) if value.strip()]
        if configured
        else [Path.cwd(), Path.home()]
    )
    roots: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def resolve_workspace_directory(value: str) -> Path:
    candidate = Path(value).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError("Workspace path must be an existing directory")
    roots = get_workspace_roots()
    if not any(candidate == root or root in candidate.parents for root in roots):
        raise ValueError("Workspace path is outside the allowed workspace roots")
    return candidate


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    workspace_id TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT,
    error_json TEXT,
    progress REAL NOT NULL DEFAULT 0,
    current_step TEXT,
    model TEXT,
    idempotency_key TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    cancelled_at INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency
ON tasks(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_user_updated ON tasks(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS model_usage (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cost_usd REAL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_usage_user ON model_usage(user_id, created_at);


CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    user_id TEXT,
    workspace_id TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    risk TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_by TEXT,
    expires_at INTEGER,
    created_at INTEGER NOT NULL,
    decided_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_approvals_task ON approvals(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    revoked_at INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT,
    label TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    user_id TEXT,
    workspace_id TEXT,
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS published_artifacts (
    slug TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_published_artifacts_artifact ON published_artifacts(artifact_id);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    workspace_id TEXT,
    conversation_id TEXT,
    scope TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_scope_key
ON memories(IFNULL(user_id, ''), IFNULL(workspace_id, ''),
            IFNULL(conversation_id, ''), scope, memory_key);

CREATE TABLE IF NOT EXISTS connector_status (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    authenticated INTEGER NOT NULL DEFAULT 0,
    read_only INTEGER NOT NULL DEFAULT 1,
    scopes_json TEXT NOT NULL,
    tools_json TEXT NOT NULL,
    version TEXT,
    message TEXT,
    checked_at INTEGER NOT NULL,
    token_expires_at INTEGER
);

CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    suite TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL,
    metrics_json TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    completed_at INTEGER
);

CREATE TABLE IF NOT EXISTS provider_health (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    state TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL,
    last_error_code TEXT,
    last_error_message TEXT,
    blocked_until INTEGER,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(provider, model)
);

CREATE TABLE IF NOT EXISTS document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    user_id TEXT,
    original_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    version INTEGER NOT NULL,
    parent_version_id TEXT,
    change_summary TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_document_version
ON document_versions(document_id, version);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    task_id TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    outcome TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS code_symbols (
    workspace_id TEXT NOT NULL,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    line INTEGER NOT NULL,
    signature TEXT,
    dependencies_json TEXT NOT NULL,
    indexed_at INTEGER NOT NULL,
    PRIMARY KEY(workspace_id, path, symbol, kind, line)
);
CREATE INDEX IF NOT EXISTS idx_code_symbols_lookup
ON code_symbols(workspace_id, symbol);

CREATE TABLE IF NOT EXISTS encrypted_secrets (
    owner TEXT NOT NULL,
    secret_key TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(owner, secret_key)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    connector TEXT NOT NULL,
    user_id TEXT,
    verifier TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    scopes_json TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    used_at INTEGER
);

CREATE TABLE IF NOT EXISTS cowork_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'inbox',
    priority TEXT NOT NULL DEFAULT 'medium',
    assignee TEXT,
    due_at INTEGER,
    tags_json TEXT NOT NULL DEFAULT '[]',
    conversation_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cowork_user_status
ON cowork_items(user_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS cowork_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(item_id) REFERENCES cowork_items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cowork_activity_item
ON cowork_activity(item_id, id DESC);

CREATE TABLE IF NOT EXISTS cowork_runs (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    workspace_path TEXT,
    status TEXT NOT NULL,
    output_json TEXT,
    error TEXT,
    started_at INTEGER NOT NULL,
    completed_at INTEGER,
    FOREIGN KEY(item_id) REFERENCES cowork_items(id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cowork_runs_item
ON cowork_runs(item_id, started_at DESC);

CREATE TABLE IF NOT EXISTS cowork_subtasks (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    position INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(item_id) REFERENCES cowork_items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cowork_subtasks_item
ON cowork_subtasks(item_id, position);

CREATE TABLE IF NOT EXISTS skill_packages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL,
    script TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_skill_packages_user
ON skill_packages(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_definitions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL,
    allowed_tools_json TEXT NOT NULL DEFAULT '[]',
    model TEXT,
    effort TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_definitions_user
ON agent_definitions(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS cowork_schedules (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    cadence TEXT NOT NULL,
    interval_minutes INTEGER,
    time_of_day TEXT,
    weekdays_json TEXT NOT NULL DEFAULT '[]',
    mode TEXT NOT NULL DEFAULT 'agent',
    workspace_path TEXT,
    model TEXT,
    effort TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at INTEGER,
    last_run_at INTEGER,
    last_status TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(item_id) REFERENCES cowork_items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cowork_schedules_due
ON cowork_schedules(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS scheduled_skills (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    instructions TEXT NOT NULL,
    model TEXT,
    cadence TEXT NOT NULL,
    interval_minutes INTEGER,
    time_of_day TEXT,
    weekdays_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at INTEGER,
    last_run_at INTEGER,
    last_status TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_scheduled_skills_due
ON scheduled_skills(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS scheduled_skill_runs (
    id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    task_id TEXT,
    status TEXT NOT NULL,
    triggered_by TEXT NOT NULL,
    output_json TEXT,
    error TEXT,
    started_at INTEGER NOT NULL,
    completed_at INTEGER,
    FOREIGN KEY(schedule_id) REFERENCES scheduled_skills(id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_runs_schedule
ON scheduled_skill_runs(schedule_id, started_at DESC);
"""


class PlatformStore:
    """Small thread-safe SQLite store with explicit transaction boundaries."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or (get_platform_data_dir() / "platform.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    # Columns added after a table first shipped. CREATE TABLE IF NOT EXISTS does
    # not touch a table that already exists, so databases created earlier get
    # these added here. (table, column, SQL type); names are constants.
    _ADDED_COLUMNS = (("scheduled_skills", "model", "TEXT"),)

    def initialize(self) -> None:
        with self._lock, self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            for table, column, sql_type in self._ADDED_COLUMNS:
                existing = {
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                }
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def fetchone(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> Optional[Dict[str, Any]]:
        with self._lock, self.connect() as conn:
            row = conn.execute(query, params).fetchone()
            return dict(row) if row else None

    def fetchall(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[Dict[str, Any]]:
        with self._lock, self.connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def audit(
        self,
        action: str,
        outcome: str,
        *,
        user_id: Optional[str] = None,
        task_id: Optional[str] = None,
        resource: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs
                    (user_id, task_id, action, resource, outcome, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    task_id,
                    action,
                    resource,
                    outcome,
                    json_dumps(details or {}),
                    utc_ms(),
                ),
            )


_default_store: Optional[PlatformStore] = None
_default_lock = threading.Lock()


def get_platform_store() -> PlatformStore:
    global _default_store
    if _default_store is None:
        with _default_lock:
            if _default_store is None:
                _default_store = PlatformStore()
    return _default_store
