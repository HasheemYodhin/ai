"""Production service layer for Dabba tasks, identity, files, and integrations."""

from __future__ import annotations

import base64
import difflib
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

from dabba.platform.core import (
    PlatformStore,
    get_platform_data_dir,
    get_platform_store,
    json_dumps,
    json_loads,
    new_id,
    get_workspace_roots,
    resolve_workspace_directory,
    utc_ms,
)

TASK_STATES = {
    "queued",
    "planning",
    "running",
    "waiting_for_approval",
    "retrying",
    "completed",
    "failed",
    "cancelled",
}
TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}


def compute_next_run(
    cadence: str,
    after_ms: int,
    interval_minutes: Optional[int],
    time_of_day: Optional[str],
    weekdays: Optional[list[int]],
) -> int:
    """Next fire time (epoch ms) for a recurring schedule. Shared by skill and Cowork schedules."""
    after = datetime.fromtimestamp(after_ms / 1000, tz=timezone.utc)
    if cadence == "interval":
        return int(
            (after + timedelta(minutes=interval_minutes or 60)).timestamp() * 1000
        )
    hour, minute = map(int, (time_of_day or "09:00").split(":"))
    candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    if cadence == "weekly":
        valid = set(weekdays or [0])
        while candidate.weekday() not in valid:
            candidate += timedelta(days=1)
    return int(candidate.timestamp() * 1000)


def validate_cadence(
    cadence: str,
    interval_minutes: Optional[int],
    time_of_day: Optional[str],
    weekdays: Optional[list[int]],
) -> None:
    """Validate recurring-schedule fields. Shared by skill and Cowork schedules."""
    if cadence not in {"interval", "daily", "weekly"}:
        raise ValueError("Cadence must be interval, daily, or weekly")
    if cadence == "interval" and (not interval_minutes or interval_minutes < 5):
        raise ValueError("Interval must be at least 5 minutes")
    if cadence in {"daily", "weekly"}:
        try:
            hour, minute = map(int, str(time_of_day or "09:00").split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("Time must use HH:MM")
    if cadence == "weekly" and not all(day in range(7) for day in (weekdays or [])):
        raise ValueError("Weekdays must be between 0 and 6")


TASK_TRANSITIONS = {
    "queued": {"planning", "running", "cancelled", "failed"},
    "planning": {"running", "waiting_for_approval", "cancelled", "failed"},
    "running": {
        "waiting_for_approval",
        "retrying",
        "completed",
        "cancelled",
        "failed",
    },
    "waiting_for_approval": {"running", "cancelled", "failed"},
    "retrying": {"running", "cancelled", "failed"},
    "completed": set(),
    "failed": {"queued"},
    "cancelled": {"queued"},
}


class TaskOrchestrator:
    """Durable state machine and event log for long-running work."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def create(
        self,
        kind: str,
        request: Dict[str, Any],
        *,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        model: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        if idempotency_key:
            existing = self.store.fetchone(
                "SELECT * FROM tasks WHERE user_id IS ? AND idempotency_key = ?",
                (user_id, idempotency_key),
            )
            if existing:
                return self._decode(existing)

        task_id = new_id("task")
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tasks
                    (id, user_id, workspace_id, kind, status, request_json,
                     progress, model, idempotency_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, 0, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    workspace_id,
                    kind,
                    json_dumps(request),
                    model,
                    idempotency_key,
                    now,
                    now,
                ),
            )
            self._insert_event(conn, task_id, "task.created", {"kind": kind}, now)
        return self.get(task_id)

    def get(self, task_id: str) -> Dict[str, Any]:
        row = self.store.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not row:
            raise KeyError(f"Task not found: {task_id}")
        return self._decode(row)

    def list(
        self,
        *,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[Dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 200)))
        rows = self.store.fetchall(
            f"SELECT * FROM tasks {where} ORDER BY updated_at DESC LIMIT ?",
            tuple(params),
        )
        return [self._decode(row) for row in rows]

    def transition(
        self,
        task_id: str,
        status: str,
        *,
        progress: Optional[float] = None,
        current_step: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if status not in TASK_STATES:
            raise ValueError(f"Unknown task state: {status}")
        current = self.get(task_id)
        if (
            status != current["status"]
            and status not in TASK_TRANSITIONS[current["status"]]
        ):
            raise ValueError(
                f"Invalid task transition: {current['status']} -> {status}"
            )

        now = utc_ms()
        resolved_progress = (
            max(0.0, min(float(progress), 1.0))
            if progress is not None
            else current["progress"]
        )
        if status == "completed":
            resolved_progress = 1.0
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE tasks SET status=?, progress=?, current_step=?,
                    result_json=COALESCE(?, result_json),
                    error_json=COALESCE(?, error_json),
                    started_at=CASE
                        WHEN ? IN ('planning','running') THEN COALESCE(started_at, ?)
                        ELSE started_at END,
                    completed_at=CASE WHEN ? IN ('completed','failed') THEN ? ELSE completed_at END,
                    cancelled_at=CASE WHEN ? = 'cancelled' THEN ? ELSE cancelled_at END,
                    updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    resolved_progress,
                    current_step,
                    json_dumps(result) if result is not None else None,
                    json_dumps(error) if error is not None else None,
                    status,
                    now,
                    status,
                    now,
                    status,
                    now,
                    now,
                    task_id,
                ),
            )
            self._insert_event(
                conn,
                task_id,
                f"task.{status}",
                {
                    "progress": resolved_progress,
                    "current_step": current_step,
                    "result": result,
                    "error": error,
                },
                now,
            )
        return self.get(task_id)

    def append_event(
        self, task_id: str, event_type: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        self.get(task_id)
        now = utc_ms()
        with self.store.transaction() as conn:
            event_id = self._insert_event(conn, task_id, event_type, payload, now)
            conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (now, task_id))
        return {
            "id": event_id,
            "taskId": task_id,
            "type": event_type,
            "payload": payload,
            "createdAt": now,
        }

    def events(self, task_id: str, after: int = 0) -> list[Dict[str, Any]]:
        self.get(task_id)
        rows = self.store.fetchall(
            """
            SELECT * FROM task_events
            WHERE task_id=? AND id>? ORDER BY id ASC
            """,
            (task_id, after),
        )
        return [
            {
                "id": row["id"],
                "taskId": row["task_id"],
                "type": row["event_type"],
                "payload": json_loads(row["payload_json"], {}),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def cancel(self, task_id: str) -> Dict[str, Any]:
        current = self.get(task_id)
        if current["status"] in TERMINAL_TASK_STATES:
            return current
        return self.transition(task_id, "cancelled")

    def resume(self, task_id: str) -> Dict[str, Any]:
        current = self.get(task_id)
        if current["status"] not in {"failed", "cancelled"}:
            return current
        return self.transition(task_id, "queued", progress=0, current_step=None)

    def run(
        self,
        task_id: str,
        handler: Callable[
            [Dict[str, Any], Callable[[float, str], None]], Dict[str, Any]
        ],
    ) -> Dict[str, Any]:
        """Run a registered job handler while persisting progress and failure."""
        task = self.get(task_id)
        if task["status"] not in {"queued", "retrying"}:
            raise ValueError(f"Task {task_id} cannot run from {task['status']}")
        self.transition(task_id, "running", current_step="Starting")

        def progress(value: float, step: str) -> None:
            current = self.get(task_id)
            if current["status"] == "cancelled":
                raise RuntimeError("Task was cancelled")
            self.transition(task_id, "running", progress=value, current_step=step)

        try:
            result = handler(task["request"], progress)
            return self.transition(task_id, "completed", result=result)
        except Exception as exc:
            current = self.get(task_id)
            if current["status"] == "cancelled":
                return current
            return self.transition(
                task_id,
                "failed",
                error={
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                    "retryable": True,
                },
            )

    def submit(
        self,
        task_id: str,
        handler: Callable[
            [Dict[str, Any], Callable[[float, str], None]], Dict[str, Any]
        ],
    ) -> threading.Thread:
        """Start a durable in-process job; external workers can call run instead."""
        thread = threading.Thread(
            target=self.run,
            args=(task_id, handler),
            name=f"dabba-{task_id}",
            daemon=True,
        )
        thread.start()
        return thread

    @staticmethod
    def _insert_event(
        conn, task_id: str, kind: str, payload: Dict[str, Any], now: int
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO task_events(task_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, kind, json_dumps(payload), now),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _decode(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "userId": row["user_id"],
            "workspaceId": row["workspace_id"],
            "kind": row["kind"],
            "status": row["status"],
            "request": json_loads(row["request_json"], {}),
            "result": json_loads(row["result_json"]),
            "error": json_loads(row["error_json"]),
            "progress": row["progress"],
            "currentStep": row["current_step"],
            "model": row["model"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "startedAt": row["started_at"],
            "completedAt": row["completed_at"],
            "cancelledAt": row["cancelled_at"],
        }


class ApprovalService:
    """One risk-aware approval policy shared by all clients."""

    ALWAYS_ASK = {"delete", "credential", "publish", "purchase", "external_write"}
    ASK_BY_DEFAULT = {
        "file_write",
        "file_edit",
        "shell_exec",
        "mcp_write",
        "git_push",
    }

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def risk_for(self, action: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        lowered = action.lower()
        args = json_dumps(arguments or {}).lower()
        if any(
            marker in lowered or marker in args
            for marker in (
                "delete",
                "rm -",
                "secret",
                "token",
                "password",
                "push --force",
            )
        ):
            return "critical"
        if lowered in self.ALWAYS_ASK or lowered in self.ASK_BY_DEFAULT:
            return "high"
        if any(
            marker in lowered
            for marker in ("write", "edit", "execute", "send", "create")
        ):
            return "medium"
        return "low"

    def requires_approval(
        self,
        action: str,
        *,
        mode: str = "ask",
        untrusted_workspace: bool = False,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> bool:
        risk = self.risk_for(action, arguments)
        if mode == "deny":
            return True
        if untrusted_workspace and risk != "low":
            return True
        if risk == "critical":
            return True
        return mode == "ask" and risk in {"medium", "high"}

    def request(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        resource: Optional[str] = None,
        ttl_seconds: int = 900,
    ) -> Dict[str, Any]:
        approval_id = new_id("approval")
        now = utc_ms()
        risk = self.risk_for(action, arguments)
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO approvals
                    (id, task_id, user_id, workspace_id, action, resource, risk,
                     arguments_json, status, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    approval_id,
                    task_id,
                    user_id,
                    workspace_id,
                    action,
                    resource,
                    risk,
                    json_dumps(arguments),
                    now + ttl_seconds * 1000,
                    now,
                ),
            )
        self.store.audit(
            "approval.requested",
            "pending",
            user_id=user_id,
            task_id=task_id,
            resource=resource,
            details={"approvalId": approval_id, "action": action, "risk": risk},
        )
        return self.get(approval_id)

    def get(self, approval_id: str) -> Dict[str, Any]:
        row = self.store.fetchone("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not row:
            raise KeyError(f"Approval not found: {approval_id}")
        if (
            row["status"] == "pending"
            and row["expires_at"]
            and row["expires_at"] < utc_ms()
        ):
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE approvals SET status='expired', decided_at=? WHERE id=?",
                    (utc_ms(), approval_id),
                )
            row["status"] = "expired"
        return {
            "id": row["id"],
            "taskId": row["task_id"],
            "userId": row["user_id"],
            "workspaceId": row["workspace_id"],
            "action": row["action"],
            "resource": row["resource"],
            "risk": row["risk"],
            "arguments": json_loads(row["arguments_json"], {}),
            "status": row["status"],
            "decisionBy": row["decision_by"],
            "expiresAt": row["expires_at"],
            "createdAt": row["created_at"],
            "decidedAt": row["decided_at"],
        }

    def decide(self, approval_id: str, allow: bool, actor: str) -> Dict[str, Any]:
        current = self.get(approval_id)
        if current["status"] != "pending":
            raise ValueError(f"Approval is already {current['status']}")
        status = "approved" if allow else "denied"
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE approvals SET status=?, decision_by=?, decided_at=?
                WHERE id=? AND status='pending'
                """,
                (status, actor, now, approval_id),
            )
        self.store.audit(
            "approval.decided",
            status,
            user_id=current["userId"],
            task_id=current["taskId"],
            resource=current["resource"],
            details={"approvalId": approval_id, "actor": actor},
        )
        return self.get(approval_id)


class IdentityService:
    """Server-side users and bearer sessions using PBKDF2-HMAC-SHA256."""

    ITERATIONS = 310_000

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    @classmethod
    def hash_password(cls, password: str) -> str:
        if len(password) < 10:
            raise ValueError("Password must be at least 10 characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, cls.ITERATIONS
        )
        return "pbkdf2_sha256${}${}${}".format(
            cls.ITERATIONS,
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )

    @staticmethod
    def verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            salt = base64.urlsafe_b64decode(salt_b64)
            expected = base64.urlsafe_b64decode(digest_b64)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, int(iterations)
            )
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False

    def signup(self, name: str, email: str, password: str) -> Dict[str, Any]:
        normalized = email.strip().lower()
        if not name.strip() or "@" not in normalized:
            raise ValueError("A valid name and email are required")
        user_id = new_id("user")
        now = utc_ms()
        try:
            with self.store.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO users
                        (id, email, name, password_hash, role, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'member', ?, ?)
                    """,
                    (
                        user_id,
                        normalized,
                        name.strip(),
                        self.hash_password(password),
                        now,
                        now,
                    ),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("An account with this email already exists") from exc
            raise
        self.store.audit("identity.signup", "success", user_id=user_id)
        return self.get_user(user_id)

    def login(
        self, email: str, password: str, *, ttl_seconds: int = 30 * 24 * 3600
    ) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM users WHERE email=?", (email.strip().lower(),)
        )
        if (
            not row
            or row["disabled"]
            or not self.verify_password(password, row["password_hash"])
        ):
            self.store.audit(
                "identity.login",
                "denied",
                details={
                    "emailHash": hashlib.sha256(email.lower().encode()).hexdigest()[:16]
                },
            )
            raise ValueError("Invalid email or password")
        token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = utc_ms()
        session_id = new_id("session")
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sessions
                    (id, user_id, token_hash, expires_at, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, row["id"], token_hash, now + ttl_seconds * 1000, now, now),
            )
        self.store.audit("identity.login", "success", user_id=row["id"])
        return {
            "token": token,
            "sessionId": session_id,
            "expiresAt": now + ttl_seconds * 1000,
            "user": self.get_user(row["id"]),
        }

    def authenticate(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = utc_ms()
        row = self.store.fetchone(
            """
            SELECT s.id AS session_id, s.user_id, s.expires_at, u.*
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.revoked_at IS NULL
              AND s.expires_at>? AND u.disabled=0
            """,
            (token_hash, now),
        )
        if not row:
            return None
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE sessions SET last_seen_at=? WHERE id=?",
                (now, row["session_id"]),
            )
        return self.get_user(row["user_id"])

    def logout(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (utc_ms(), token_hash),
            )

    def get_user(self, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
        if not row:
            raise KeyError(f"User not found: {user_id}")
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "role": row["role"],
            "disabled": bool(row["disabled"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }


class SecretVault:
    """Fernet-encrypted secrets with a private local master key."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()
        self._fernet = self._load_fernet()

    @staticmethod
    def _load_fernet():
        from cryptography.fernet import Fernet

        configured = os.environ.get("DABBA_MASTER_KEY")
        if configured:
            key = configured.encode("ascii")
        else:
            key_path = get_platform_data_dir() / "master.key"
            key_path.parent.mkdir(parents=True, exist_ok=True)
            if key_path.exists():
                key = key_path.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(key)
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        return Fernet(key)

    def put(
        self,
        owner: str,
        key: str,
        value: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        ciphertext = self._fernet.encrypt(value.encode("utf-8"))
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO encrypted_secrets
                    (owner, secret_key, ciphertext, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner, secret_key) DO UPDATE SET
                    ciphertext=excluded.ciphertext,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (owner, key, ciphertext, json_dumps(metadata or {}), now, now),
            )

    def get(self, owner: str, key: str) -> Optional[str]:
        row = self.store.fetchone(
            "SELECT ciphertext FROM encrypted_secrets WHERE owner=? AND secret_key=?",
            (owner, key),
        )
        if not row:
            return None
        token = row["ciphertext"]
        if isinstance(token, str):
            token = token.encode("ascii")
        return self._fernet.decrypt(token).decode("utf-8")

    def delete(self, owner: str, key: str) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM encrypted_secrets WHERE owner=? AND secret_key=?",
                (owner, key),
            )

    def keys(self, owner: str) -> list[str]:
        return [
            row["secret_key"]
            for row in self.store.fetchall(
                "SELECT secret_key FROM encrypted_secrets WHERE owner=? ORDER BY secret_key",
                (owner,),
            )
        ]


class WorkspaceService:
    """Workspace containment, instructions, snapshots, diffs, and rollback."""

    INSTRUCTION_NAMES = ("DABBA.md", "AGENTS.md")

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def register(
        self,
        root_path: str,
        *,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        root = Path(root_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Workspace directory does not exist: {root}")
        workspace_id = new_id("workspace")
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO workspaces
                    (id, user_id, name, root_path, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, '{}', ?, ?)
                """,
                (workspace_id, user_id, name or root.name, str(root), now, now),
            )
        return self.get(workspace_id)

    def get(self, workspace_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM workspaces WHERE id=?", (workspace_id,)
        )
        if not row:
            raise KeyError(f"Workspace not found: {workspace_id}")
        return {
            "id": row["id"],
            "userId": row["user_id"],
            "name": row["name"],
            "rootPath": row["root_path"],
            "metadata": json_loads(row["metadata_json"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def browse_directories(self, path: Optional[str] = None) -> Dict[str, Any]:
        """List selectable server-side directories without exposing file contents."""
        roots = get_workspace_roots()
        if not path:
            return {
                "path": None,
                "parent": None,
                "roots": [
                    {"name": root.name or str(root), "path": str(root)}
                    for root in roots
                ],
                "directories": [],
            }
        current = resolve_workspace_directory(path)
        directories = []
        try:
            children = sorted(current.iterdir(), key=lambda entry: entry.name.lower())
        except OSError as exc:
            raise ValueError(f"Cannot read directory: {current}") from exc
        for child in children:
            if child.name.startswith(".") or child.is_symlink():
                continue
            try:
                if child.is_dir():
                    directories.append(
                        {"name": child.name, "path": str(child.resolve())}
                    )
            except OSError:
                continue
            if len(directories) >= 500:
                break
        containing_root = next(
            root for root in roots if current == root or root in current.parents
        )
        parent = current.parent if current != containing_root else None
        return {
            "path": str(current),
            "parent": str(parent) if parent else None,
            "roots": [
                {"name": root.name or str(root), "path": str(root)} for root in roots
            ],
            "directories": directories,
        }

    def pick_directory(self, initial_path: Optional[str] = None) -> Dict[str, Any]:
        """Open the host OS folder chooser for a local Dabba desktop session."""
        roots = get_workspace_roots()
        initial = (
            resolve_workspace_directory(initial_path)
            if initial_path
            else (roots[0] if roots else Path.cwd().resolve())
        )
        if sys.platform == "win32":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
                f"$d.SelectedPath='{str(initial).replace(chr(39), chr(39) * 2)}';"
                "if($d.ShowDialog() -eq 'OK'){Write-Output $d.SelectedPath}"
            )
            command = ["powershell", "-NoProfile", "-Command", script]
        elif sys.platform == "darwin":
            command = [
                "osascript",
                "-e",
                f'POSIX path of (choose folder with prompt "Choose Cowork folder" default location POSIX file "{initial}")',
            ]
        elif shutil.which("zenity"):
            command = [
                shutil.which("zenity") or "zenity",
                "--file-selection",
                "--directory",
                "--title=Choose Cowork folder",
                f"--filename={initial}/",
            ]
        elif shutil.which("kdialog"):
            command = [
                "kdialog",
                "--getexistingdirectory",
                str(initial),
                "--title",
                "Choose Cowork folder",
            ]
        else:
            raise RuntimeError(
                "A native folder chooser is not installed; use the in-app folder list"
            )
        chooser_environment = None
        if sys.platform.startswith("linux"):
            # Dabba is commonly launched from the Snap build of VS Code. Snap
            # injects GTK/library paths that make host programs such as zenity
            # load incompatible libraries and exit before showing a window.
            # Pass only the desktop-session values needed by the host chooser.
            desktop_keys = (
                "HOME",
                "USER",
                "LOGNAME",
                "DISPLAY",
                "WAYLAND_DISPLAY",
                "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS",
                "XAUTHORITY",
                "LANG",
                "LANGUAGE",
                "LC_ALL",
                "LC_CTYPE",
            )
            chooser_environment = {
                key: os.environ[key] for key in desktop_keys if os.environ.get(key)
            }
            chooser_environment["PATH"] = (
                "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                env=chooser_environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Folder selection timed out") from exc
        selected = result.stdout.strip()
        if result.returncode != 0 or not selected:
            error = getattr(result, "stderr", "").strip()
            if error:
                raise RuntimeError(f"Folder chooser could not open: {error}")
            return {"cancelled": True, "path": None}
        return {"cancelled": False, "path": str(resolve_workspace_directory(selected))}

    def resolve_path(self, workspace_id: str, relative_path: str) -> Path:
        workspace = self.get(workspace_id)
        root = Path(workspace["rootPath"]).resolve()
        candidate = (root / relative_path).resolve()
        if candidate != root and root not in candidate.parents:
            raise PermissionError("Path escapes the registered workspace")
        return candidate

    def instructions_for(
        self, workspace_id: str, relative_path: str = ""
    ) -> list[Dict[str, str]]:
        workspace = self.get(workspace_id)
        root = Path(workspace["rootPath"]).resolve()
        target = self.resolve_path(workspace_id, relative_path)
        cursor = target if target.is_dir() else target.parent
        directories = []
        while cursor == root or root in cursor.parents:
            directories.append(cursor)
            if cursor == root:
                break
            cursor = cursor.parent
        result = []
        for directory in reversed(directories):
            for name in self.INSTRUCTION_NAMES:
                path = directory / name
                if path.is_file():
                    result.append(
                        {
                            "path": str(path),
                            "content": path.read_text(
                                encoding="utf-8", errors="replace"
                            ),
                        }
                    )
        return result

    def checkpoint(
        self,
        workspace_id: str,
        *,
        label: str,
        task_id: Optional[str] = None,
        paths: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        workspace = self.get(workspace_id)
        root = Path(workspace["rootPath"])
        checkpoint_id = new_id("checkpoint")
        snapshot_root = get_platform_data_dir() / "checkpoints" / checkpoint_id
        snapshot_root.mkdir(parents=True, exist_ok=False)
        requested = paths or [
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]
        manifest: Dict[str, Dict[str, Any]] = {}
        for relative in requested:
            source = self.resolve_path(workspace_id, relative)
            if not source.is_file():
                continue
            destination = snapshot_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            content = source.read_bytes()
            manifest[relative] = {
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints
                    (id, workspace_id, task_id, label, manifest_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    workspace_id,
                    task_id,
                    label,
                    json_dumps(manifest),
                    utc_ms(),
                ),
            )
        return {
            "id": checkpoint_id,
            "workspaceId": workspace_id,
            "label": label,
            "files": len(manifest),
            "path": str(snapshot_root),
        }

    def diff(self, checkpoint_id: str) -> Dict[str, Any]:
        row = self.checkpoint_info(checkpoint_id)
        workspace = self.get(row["workspace_id"])
        root = Path(workspace["rootPath"])
        snapshot_root = get_platform_data_dir() / "checkpoints" / checkpoint_id
        manifest = json_loads(row["manifest_json"], {})
        changes = []
        for relative in manifest:
            before_path = snapshot_root / relative
            after_path = root / relative
            before = before_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            after = (
                after_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if after_path.exists()
                else []
            )
            patch = "\n".join(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                    lineterm="",
                )
            )
            if patch:
                changes.append({"path": relative, "diff": patch})
        return {"checkpointId": checkpoint_id, "changes": changes}

    def rollback(self, checkpoint_id: str) -> Dict[str, Any]:
        row = self.checkpoint_info(checkpoint_id)
        workspace = self.get(row["workspace_id"])
        root = Path(workspace["rootPath"])
        snapshot_root = get_platform_data_dir() / "checkpoints" / checkpoint_id
        manifest = json_loads(row["manifest_json"], {})
        restored = []
        for relative in manifest:
            source = snapshot_root / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            restored.append(relative)
        self.store.audit(
            "workspace.rollback",
            "success",
            task_id=row["task_id"],
            resource=workspace["rootPath"],
            details={"checkpointId": checkpoint_id, "files": restored},
        )
        return {"checkpointId": checkpoint_id, "restored": restored}

    def checkpoint_info(self, checkpoint_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM checkpoints WHERE id=?", (checkpoint_id,)
        )
        if not row:
            raise KeyError(f"Checkpoint not found: {checkpoint_id}")
        return row


class ArtifactService:
    """Immutable artifact registration and versioned binary storage."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()
        # Keep binary artifacts alongside the SQLite store.  Using the global
        # config directory here ignored injected/test stores and failed when
        # that directory was read-only, even though the store itself was valid.
        self.root = self.store.path.parent / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def store_bytes(
        self,
        name: str,
        content: bytes,
        *,
        media_type: Optional[str] = None,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        artifact_id = new_id("artifact")
        safe_name = Path(name).name or "artifact.bin"
        destination = self.root / artifact_id / safe_name
        destination.parent.mkdir(parents=True, exist_ok=False)
        destination.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        resolved_type = (
            media_type
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )
        version_row = self.store.fetchone(
            """
            SELECT MAX(version) AS version FROM artifacts
            WHERE user_id IS ? AND workspace_id IS ? AND name=?
            """,
            (user_id, workspace_id, safe_name),
        )
        version = int((version_row or {}).get("version") or 0) + 1
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO artifacts
                    (id, task_id, user_id, workspace_id, name, media_type, path,
                     size, checksum, version, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    task_id,
                    user_id,
                    workspace_id,
                    safe_name,
                    resolved_type,
                    str(destination),
                    len(content),
                    checksum,
                    version,
                    json_dumps(metadata or {}),
                    utc_ms(),
                ),
            )
        return self.get(artifact_id)

    def get(self, artifact_id: str) -> Dict[str, Any]:
        row = self.store.fetchone("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if not row:
            raise KeyError(f"Artifact not found: {artifact_id}")
        return {
            "id": row["id"],
            "taskId": row["task_id"],
            "userId": row["user_id"],
            "workspaceId": row["workspace_id"],
            "name": row["name"],
            "mediaType": row["media_type"],
            "path": row["path"],
            "size": row["size"],
            "checksum": row["checksum"],
            "version": row["version"],
            "metadata": json_loads(row["metadata_json"], {}),
            "createdAt": row["created_at"],
        }

    def publish(self, artifact_id: str, user_id: str, title: str) -> Dict[str, Any]:
        """
        Mint a public, unauthenticated share slug for an artifact the caller
        owns — turns the in-session-only preview panel into a standalone page
        with a real shareable URL, served by GET /v1/platform/public/artifacts/{slug}.
        """
        artifact = self.get(artifact_id)
        if artifact["userId"] != user_id:
            raise PermissionError("You do not own this artifact")
        slug = secrets.token_urlsafe(9)
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO published_artifacts (slug,artifact_id,user_id,title,created_at) VALUES (?,?,?,?,?)",
                (
                    slug,
                    artifact_id,
                    user_id,
                    title.strip() or artifact["name"],
                    utc_ms(),
                ),
            )
        return self.get_published(slug)

    def get_published(self, slug: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM published_artifacts WHERE slug=?", (slug,)
        )
        if not row:
            raise KeyError(f"No published artifact at slug: {slug}")
        artifact = self.get(row["artifact_id"])
        return {
            "slug": row["slug"],
            "title": row["title"],
            "createdAt": row["created_at"],
            "artifact": artifact,
        }

    def list_published(self, user_id: str) -> list[Dict[str, Any]]:
        rows = self.store.fetchall(
            "SELECT * FROM published_artifacts WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        )
        return [
            {
                "slug": r["slug"],
                "title": r["title"],
                "artifactId": r["artifact_id"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ]

    def unpublish(self, slug: str, user_id: str) -> None:
        row = self.store.fetchone(
            "SELECT * FROM published_artifacts WHERE slug=?", (slug,)
        )
        if not row:
            raise KeyError(f"No published artifact at slug: {slug}")
        if row["user_id"] != user_id:
            raise PermissionError("You do not own this published artifact")
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM published_artifacts WHERE slug=?", (slug,))


class MemoryService:
    """Explicitly scoped conversation, project, and preference memory."""

    VALID_SCOPES = {"conversation", "project", "preference", "workspace"}

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def put(
        self,
        scope: str,
        key: str,
        content: str,
        *,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if scope not in self.VALID_SCOPES:
            raise ValueError(f"Unknown memory scope: {scope}")
        memory_id = new_id("memory")
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO memories
                    (id, user_id, workspace_id, conversation_id, scope, memory_key,
                     content, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO UPDATE SET
                    content=excluded.content,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    memory_id,
                    user_id,
                    workspace_id,
                    conversation_id,
                    scope,
                    key,
                    content,
                    json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
        return {
            "scope": scope,
            "key": key,
            "content": content,
            "metadata": metadata or {},
            "updatedAt": now,
        }

    def list(
        self,
        *,
        scope: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        clauses = ["user_id IS ?", "workspace_id IS ?", "conversation_id IS ?"]
        params: list[Any] = [user_id, workspace_id, conversation_id]
        if scope:
            clauses.append("scope=?")
            params.append(scope)
        rows = self.store.fetchall(
            f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",
            tuple(params),
        )
        return [
            {
                "id": row["id"],
                "scope": row["scope"],
                "key": row["memory_key"],
                "content": row["content"],
                "metadata": json_loads(row["metadata_json"], {}),
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    def delete(self, memory_id: str, user_id: Optional[str] = None) -> None:
        row = self.store.fetchone("SELECT * FROM memories WHERE id=?", (memory_id,))
        if not row:
            raise KeyError(memory_id)
        if row["user_id"] != user_id:
            raise PermissionError("You do not own this memory")
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))


class ConnectorRuntime:
    """Connector capability verification independent of process startup."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def record_health(
        self,
        name: str,
        *,
        process_running: bool,
        authenticated: bool,
        tools: list[str],
        scopes: Optional[list[str]] = None,
        read_only: bool = True,
        version: Optional[str] = None,
        message: Optional[str] = None,
        token_expires_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not process_running:
            status = "stopped"
        elif not authenticated:
            status = "authentication_required"
        elif not tools:
            status = "degraded"
        else:
            status = "connected"
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO connector_status
                    (name, status, authenticated, read_only, scopes_json,
                     tools_json, version, message, checked_at, token_expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    status=excluded.status,
                    authenticated=excluded.authenticated,
                    read_only=excluded.read_only,
                    scopes_json=excluded.scopes_json,
                    tools_json=excluded.tools_json,
                    version=excluded.version,
                    message=excluded.message,
                    checked_at=excluded.checked_at,
                    token_expires_at=excluded.token_expires_at
                """,
                (
                    name,
                    status,
                    int(authenticated),
                    int(read_only),
                    json_dumps(scopes or []),
                    json_dumps(tools),
                    version,
                    message,
                    now,
                    token_expires_at,
                ),
            )
        return self.get(name)

    def get(self, name: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM connector_status WHERE name=?", (name,)
        )
        if not row:
            raise KeyError(f"Connector has not been verified: {name}")
        return {
            "name": row["name"],
            "status": row["status"],
            "authenticated": bool(row["authenticated"]),
            "readOnly": bool(row["read_only"]),
            "scopes": json_loads(row["scopes_json"], []),
            "tools": json_loads(row["tools_json"], []),
            "version": row["version"],
            "message": row["message"],
            "checkedAt": row["checked_at"],
            "tokenExpiresAt": row["token_expires_at"],
        }

    def list(self) -> list[Dict[str, Any]]:
        return [
            self.get(row["name"])
            for row in self.store.fetchall(
                "SELECT name FROM connector_status ORDER BY name"
            )
        ]

    def begin_oauth(
        self,
        name: str,
        *,
        scopes: list[str],
        redirect_uri: str,
        user_id: Optional[str] = None,
        ttl_seconds: int = 600,
    ) -> Dict[str, Any]:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO oauth_states
                    (state, connector, user_id, verifier, redirect_uri,
                     scopes_json, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state,
                    name,
                    user_id,
                    verifier,
                    redirect_uri,
                    json_dumps(scopes),
                    now + ttl_seconds * 1000,
                    now,
                ),
            )
        return {
            "state": state,
            "codeChallenge": challenge,
            "codeChallengeMethod": "S256",
            "redirectUri": redirect_uri,
            "scopes": scopes,
            "expiresAt": now + ttl_seconds * 1000,
        }

    def complete_oauth(
        self,
        state: str,
        token_payload: Dict[str, Any],
        *,
        vault: Optional[SecretVault] = None,
    ) -> Dict[str, Any]:
        row = self.store.fetchone("SELECT * FROM oauth_states WHERE state=?", (state,))
        if not row or row["used_at"] or row["expires_at"] < utc_ms():
            raise ValueError("OAuth state is invalid, expired, or already used")
        resolved_vault = vault or SecretVault(self.store)
        resolved_vault.put(
            f"connector:{row['connector']}",
            "oauth_token",
            json_dumps(token_payload),
            metadata={"scopes": json_loads(row["scopes_json"], [])},
        )
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE oauth_states SET used_at=? WHERE state=?", (utc_ms(), state)
            )
        return {
            "connector": row["connector"],
            "scopes": json_loads(row["scopes_json"], []),
            "stored": True,
        }


class EvaluationService:
    """Persisted regression and quality evaluation results."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def start(self, suite: str, subject: str) -> Dict[str, Any]:
        evaluation_id = new_id("eval")
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO evaluations
                    (id, suite, subject, status, metrics_json, details_json, created_at)
                VALUES (?, ?, ?, 'running', '{}', '{}', ?)
                """,
                (evaluation_id, suite, subject, utc_ms()),
            )
        return self.get(evaluation_id)

    def complete(
        self,
        evaluation_id: str,
        *,
        score: float,
        metrics: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE evaluations
                SET status='completed', score=?, metrics_json=?, details_json=?,
                    completed_at=?
                WHERE id=?
                """,
                (
                    score,
                    json_dumps(metrics),
                    json_dumps(details or {}),
                    utc_ms(),
                    evaluation_id,
                ),
            )
        return self.get(evaluation_id)

    def get(self, evaluation_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM evaluations WHERE id=?", (evaluation_id,)
        )
        if not row:
            raise KeyError(f"Evaluation not found: {evaluation_id}")
        return {
            "id": row["id"],
            "suite": row["suite"],
            "subject": row["subject"],
            "status": row["status"],
            "score": row["score"],
            "metrics": json_loads(row["metrics_json"], {}),
            "details": json_loads(row["details_json"], {}),
            "createdAt": row["created_at"],
            "completedAt": row["completed_at"],
        }


class TelemetryService:
    """Optional OpenTelemetry spans plus local counters when OTel is absent."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()
        try:
            from opentelemetry import metrics, trace

            self._configure_exporter(trace)
            self._tracer = trace.get_tracer("dabba.platform")
            meter = metrics.get_meter("dabba.platform")
            self._request_counter = meter.create_counter(
                "dabba.http.requests",
                description="HTTP requests handled by Dabba",
            )
            self._duration_histogram = meter.create_histogram(
                "dabba.http.duration",
                unit="ms",
                description="Dabba HTTP request duration",
            )
        except ImportError:
            self._tracer = None
            self._request_counter = None
            self._duration_histogram = None

    @staticmethod
    def _configure_exporter(trace_module) -> None:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            return
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            current = trace_module.get_tracer_provider()
            if current.__class__.__module__.startswith("opentelemetry.sdk"):
                return
            provider = TracerProvider(
                resource=Resource.create({"service.name": "dabba"})
            )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
            trace_module.set_tracer_provider(provider)
        except (ImportError, ValueError):
            return

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Any]:
        started = time.perf_counter()
        if self._tracer:
            with self._tracer.start_as_current_span(name) as span:
                for key, value in attributes.items():
                    if value is not None:
                        span.set_attribute(key, value)
                try:
                    yield span
                except Exception as exc:
                    span.record_exception(exc)
                    raise
            return
        try:
            yield None
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.store.audit(
                "telemetry.span",
                "recorded",
                details={"name": name, "durationMs": elapsed, "attributes": attributes},
            )

    def record_http(
        self, method: str, route: str, status: int, duration_ms: float
    ) -> None:
        attributes = {
            "http.request.method": method,
            "http.route": route,
            "http.response.status_code": status,
        }
        if self._request_counter:
            self._request_counter.add(1, attributes)
        if self._duration_histogram:
            self._duration_histogram.record(duration_ms, attributes)


class DocumentWorkspace:
    """Immutable original documents and format-preserving revision history."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()
        self.root = get_platform_data_dir() / "documents"
        self.root.mkdir(parents=True, exist_ok=True)

    def import_bytes(
        self,
        name: str,
        content: bytes,
        *,
        user_id: Optional[str] = None,
        media_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        document_id = new_id("document")
        safe_name = Path(name).name
        destination = self.root / document_id / "v1" / safe_name
        destination.parent.mkdir(parents=True, exist_ok=False)
        destination.write_bytes(content)
        version_id = new_id("docver")
        resolved_type = (
            media_type
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO document_versions
                    (id, document_id, user_id, original_name, media_type,
                     source_path, version, change_summary, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, 'Original upload', ?, ?)
                """,
                (
                    version_id,
                    document_id,
                    user_id,
                    safe_name,
                    resolved_type,
                    str(destination),
                    json_dumps(metadata or {}),
                    utc_ms(),
                ),
            )
        return self.get_version(version_id)

    def add_revision(
        self,
        document_id: str,
        content: bytes,
        *,
        change_summary: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        latest = self.latest(document_id)
        version = latest["version"] + 1
        safe_name = Path(name or latest["name"]).name
        destination = self.root / document_id / f"v{version}" / safe_name
        destination.parent.mkdir(parents=True, exist_ok=False)
        destination.write_bytes(content)
        version_id = new_id("docver")
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO document_versions
                    (id, document_id, user_id, original_name, media_type,
                     source_path, version, parent_version_id, change_summary,
                     metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    document_id,
                    latest["userId"],
                    safe_name,
                    mimetypes.guess_type(safe_name)[0] or latest["mediaType"],
                    str(destination),
                    version,
                    latest["id"],
                    change_summary,
                    json_dumps(metadata or {}),
                    utc_ms(),
                ),
            )
        return self.get_version(version_id)

    def edit(
        self,
        document_id: str,
        replacements: Dict[str, str],
        *,
        change_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        from dabba.platform.document_editing import edit_document

        if not replacements or any(not old for old in replacements):
            raise ValueError("Each replacement requires non-empty original text")
        latest = self.latest(document_id)
        source = Path(latest["path"])
        staging = self.root / ".staging" / new_id("edit") / latest["name"]
        try:
            count = edit_document(source, staging, replacements)
            return self.add_revision(
                document_id,
                staging.read_bytes(),
                change_summary=change_summary or f"Applied {count} text replacement(s)",
                name=latest["name"],
                metadata={"replacements": count, "formatPreserved": True},
            )
        finally:
            shutil.rmtree(staging.parent, ignore_errors=True)

    def latest(self, document_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            """
            SELECT id FROM document_versions
            WHERE document_id=? ORDER BY version DESC LIMIT 1
            """,
            (document_id,),
        )
        if not row:
            raise KeyError(f"Document not found: {document_id}")
        return self.get_version(row["id"])

    def versions(self, document_id: str) -> list[Dict[str, Any]]:
        rows = self.store.fetchall(
            """
            SELECT id FROM document_versions
            WHERE document_id=? ORDER BY version DESC
            """,
            (document_id,),
        )
        return [self.get_version(row["id"]) for row in rows]

    def get_version(self, version_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM document_versions WHERE id=?", (version_id,)
        )
        if not row:
            raise KeyError(f"Document version not found: {version_id}")
        path = Path(row["source_path"])
        return {
            "id": row["id"],
            "documentId": row["document_id"],
            "userId": row["user_id"],
            "name": row["original_name"],
            "mediaType": row["media_type"],
            "path": row["source_path"],
            "size": path.stat().st_size if path.exists() else 0,
            "version": row["version"],
            "parentVersionId": row["parent_version_id"],
            "changeSummary": row["change_summary"],
            "metadata": json_loads(row["metadata_json"], {}),
            "createdAt": row["created_at"],
        }


COWORK_STATUSES = {"inbox", "planned", "in_progress", "blocked", "done"}
COWORK_PRIORITIES = {"low", "medium", "high", "urgent"}


class CoworkService:
    """Persistent shared-work queue with a compact audit trail."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()
        self.tasks = TaskOrchestrator(self.store)

    def create(
        self,
        user_id: str,
        title: str,
        *,
        description: str = "",
        status: str = "inbox",
        priority: str = "medium",
        assignee: Optional[str] = None,
        due_at: Optional[int] = None,
        tags: Optional[list[str]] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("Title is required")
        self._validate(status, priority)
        item_id, now = new_id("work"), utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """INSERT INTO cowork_items
                   (id,user_id,title,description,status,priority,assignee,due_at,
                    tags_json,conversation_id,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item_id,
                    user_id,
                    title,
                    description.strip(),
                    status,
                    priority,
                    assignee.strip() if assignee else None,
                    due_at,
                    json_dumps(self._clean_tags(tags)),
                    conversation_id,
                    now,
                    now,
                ),
            )
            self._activity(conn, item_id, user_id, "created", {"status": status}, now)
        return self.get(item_id, user_id)

    def list(
        self, user_id: str, *, status: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        params: list[Any] = [user_id]
        where = "user_id=?"
        if status:
            if status not in COWORK_STATUSES:
                raise ValueError("Unknown cowork status")
            where += " AND status=?"
            params.append(status)
        rows = self.store.fetchall(
            f"SELECT * FROM cowork_items WHERE {where} "
            "ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END, updated_at DESC",
            tuple(params),
        )
        return [self._decode(row) for row in rows]

    def get(self, item_id: str, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM cowork_items WHERE id=? AND user_id=?", (item_id, user_id)
        )
        if not row:
            raise KeyError(item_id)
        return self._decode(row)

    def update(
        self, item_id: str, user_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        current = self.get(item_id, user_id)
        allowed = {
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "dueAt",
            "tags",
            "conversationId",
        }
        changes = {key: value for key, value in changes.items() if key in allowed}
        if not changes:
            return current
        values = {
            "title": current["title"],
            "description": current["description"],
            "status": current["status"],
            "priority": current["priority"],
            "assignee": current["assignee"],
            "dueAt": current["dueAt"],
            "tags": current["tags"],
            "conversationId": current["conversationId"],
            **changes,
        }
        values["title"] = str(values["title"]).strip()
        if not values["title"]:
            raise ValueError("Title is required")
        self._validate(values["status"], values["priority"])
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """UPDATE cowork_items SET title=?,description=?,status=?,priority=?,
                   assignee=?,due_at=?,tags_json=?,conversation_id=?,updated_at=?
                   WHERE id=? AND user_id=?""",
                (
                    values["title"],
                    str(values["description"] or "").strip(),
                    values["status"],
                    values["priority"],
                    values["assignee"],
                    values["dueAt"],
                    json_dumps(self._clean_tags(values["tags"])),
                    values["conversationId"],
                    now,
                    item_id,
                    user_id,
                ),
            )
            self._activity(conn, item_id, user_id, "updated", changes, now)
        return self.get(item_id, user_id)

    def delete(self, item_id: str, user_id: str) -> None:
        self.get(item_id, user_id)
        active = self.store.fetchone(
            "SELECT id FROM cowork_runs WHERE item_id=? AND status IN ('queued','running') LIMIT 1",
            (item_id,),
        )
        if active:
            raise ValueError("Cancel the active Cowork run before deleting this item")
        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM cowork_items WHERE id=? AND user_id=?", (item_id, user_id)
            )

    def activity(self, item_id: str, user_id: str) -> list[Dict[str, Any]]:
        self.get(item_id, user_id)
        rows = self.store.fetchall(
            "SELECT * FROM cowork_activity WHERE item_id=? ORDER BY id DESC LIMIT 100",
            (item_id,),
        )
        return [
            {
                "id": row["id"],
                "eventType": row["event_type"],
                "detail": json_loads(row["detail_json"], {}),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def dispatch(
        self,
        item_id: str,
        user_id: str,
        *,
        mode: str = "safe",
        workspace_path: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        item = self.get(item_id, user_id)
        if mode not in {"safe", "agent"}:
            raise ValueError("Cowork run mode must be safe or agent")
        active = self.store.fetchone(
            """SELECT id FROM cowork_runs WHERE item_id=? AND user_id=?
               AND status IN ('queued','running') LIMIT 1""",
            (item_id, user_id),
        )
        if active:
            raise ValueError("This Cowork item is already running")
        resolved_workspace = None
        if workspace_path:
            resolved_workspace = str(resolve_workspace_directory(workspace_path))
        task = self.tasks.create(
            "cowork_agent",
            {
                "itemId": item_id,
                "title": item["title"],
                "description": item["description"],
                "mode": mode,
                "workspacePath": resolved_workspace,
                "effort": effort,
            },
            user_id=user_id,
            model=model,
        )
        run_id, now = new_id("coworkrun"), utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """INSERT INTO cowork_runs
                   (id,item_id,user_id,task_id,mode,workspace_path,status,started_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    item_id,
                    user_id,
                    task["id"],
                    mode,
                    resolved_workspace,
                    "queued",
                    now,
                ),
            )
            conn.execute(
                "UPDATE cowork_items SET status='in_progress',assignee='Dabba',updated_at=? WHERE id=?",
                (now, item_id),
            )
            self._activity(
                conn,
                item_id,
                user_id,
                "run.queued",
                {"runId": run_id, "mode": mode},
                now,
            )
        return self.get_run(run_id, user_id)

    def execute(
        self,
        run_id: str,
        user_id: str,
        executor: Callable[[Dict[str, Any], Dict[str, Any]], Any],
    ) -> Dict[str, Any]:
        run = self.get_run(run_id, user_id)
        if (
            run["status"] != "queued"
            or self.tasks.get(run["taskId"])["status"] == "cancelled"
        ):
            return run
        item = self.get(run["itemId"], user_id)
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE cowork_runs SET status='running' WHERE id=? AND user_id=?",
                (run_id, user_id),
            )

        def handler(
            _request: Dict[str, Any], progress: Callable[[float, str], None]
        ) -> Dict[str, Any]:
            progress(0.1, "Dabba is reviewing the work item")
            execution = executor(item, run)
            progress(0.9, "Saving Cowork result")
            details = (
                execution
                if isinstance(execution, dict)
                else {"content": str(execution)}
            )
            return {**details, "itemId": item["id"], "runId": run_id}

        task = self.tasks.run(run["taskId"], handler)
        status = task["status"]
        error = (task.get("error") or {}).get("message") if task.get("error") else None
        item_status = (
            "done"
            if status == "completed"
            else ("planned" if status == "cancelled" else "blocked")
        )
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """UPDATE cowork_runs SET status=?,output_json=?,error=?,completed_at=?
                   WHERE id=? AND user_id=?""",
                (
                    status,
                    json_dumps(task.get("result")) if task.get("result") else None,
                    error,
                    now,
                    run_id,
                    user_id,
                ),
            )
            conn.execute(
                "UPDATE cowork_items SET status=?,updated_at=? WHERE id=? AND user_id=?",
                (item_status, now, item["id"], user_id),
            )
            self._activity(
                conn,
                item["id"],
                user_id,
                f"run.{status}",
                {"runId": run_id, "taskId": task["id"]},
                now,
            )
        return self.get_run(run_id, user_id)

    def runs(self, item_id: str, user_id: str, limit: int = 50) -> list[Dict[str, Any]]:
        self.get(item_id, user_id)
        rows = self.store.fetchall(
            """SELECT * FROM cowork_runs WHERE item_id=? AND user_id=?
               ORDER BY started_at DESC LIMIT ?""",
            (item_id, user_id, max(1, min(limit, 200))),
        )
        return [self._decode_run(row) for row in rows]

    def get_run(self, run_id: str, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM cowork_runs WHERE id=? AND user_id=?", (run_id, user_id)
        )
        if not row:
            raise KeyError(run_id)
        return self._decode_run(row)

    def previous_summary(
        self, item_id: str, user_id: str, exclude_run_id: str
    ) -> Optional[str]:
        """
        Return the final summary text from this item's most recent prior run
        that produced output, so a follow-up run can continue from what was
        already done instead of rediscovering the workspace from scratch.

        Looks at completed OR failed/interrupted runs (a run that stopped at
        the step limit still did real work worth resuming from).
        """
        rows = self.store.fetchall(
            """SELECT output_json FROM cowork_runs
               WHERE item_id=? AND user_id=? AND id!=?
                 AND status IN ('completed','failed')
               ORDER BY started_at DESC LIMIT 5""",
            (item_id, user_id, exclude_run_id),
        )
        for row in rows:
            output = json_loads(row["output_json"])
            if isinstance(output, dict):
                content = str(output.get("content") or "").strip()
                if content:
                    return content
        return None

    def cancel_run(self, run_id: str, user_id: str) -> Dict[str, Any]:
        run = self.get_run(run_id, user_id)
        task = self.tasks.cancel(run["taskId"])
        if task["status"] != "cancelled":
            return run
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE cowork_runs SET status='cancelled',completed_at=? WHERE id=? AND user_id=?",
                (now, run_id, user_id),
            )
            conn.execute(
                "UPDATE cowork_items SET status='planned',updated_at=? WHERE id=? AND user_id=?",
                (now, run["itemId"], user_id),
            )
            self._activity(
                conn, run["itemId"], user_id, "run.cancelled", {"runId": run_id}, now
            )
        return self.get_run(run_id, user_id)

    def recover_orphaned_runs(self) -> int:
        """Release Cowork runs left active by a previous server process.

        Cowork execution lives in the API process.  If that process is
        restarted, persisted ``queued``/``running`` rows have no worker behind
        them and used to block the user forever with "already running".
        Mark those runs interrupted so the item can immediately be continued.
        """
        rows = self.store.fetchall(
            """SELECT r.id, r.item_id, r.user_id, r.task_id, t.status AS task_status
               FROM cowork_runs r
               JOIN tasks t ON t.id=r.task_id
               WHERE r.status IN ('queued', 'running')"""
        )
        recovered = 0
        for row in rows:
            task_status = row["task_status"]
            if task_status not in TERMINAL_TASK_STATES:
                self.tasks.transition(
                    row["task_id"],
                    "failed",
                    current_step="Interrupted by Dabba server restart",
                    error={
                        "code": "cowork_interrupted",
                        "message": "Cowork was interrupted by a server restart. Continue the task to resume.",
                    },
                )
            now = utc_ms()
            with self.store.transaction() as conn:
                conn.execute(
                    """UPDATE cowork_runs SET status='failed',
                       error=?, completed_at=? WHERE id=?""",
                    (
                        "Cowork was interrupted by a server restart. Continue the task to resume.",
                        now,
                        row["id"],
                    ),
                )
                conn.execute(
                    """UPDATE cowork_items SET status='planned',updated_at=?
                       WHERE id=? AND user_id=?""",
                    (now, row["item_id"], row["user_id"]),
                )
                self._activity(
                    conn,
                    row["item_id"],
                    row["user_id"],
                    "run.interrupted",
                    {"runId": row["id"], "taskId": row["task_id"]},
                    now,
                )
            recovered += 1
        return recovered

    # ── Subtasks (checklist) ─────────────────────────────────────────────

    def list_subtasks(self, item_id: str, user_id: str) -> list[Dict[str, Any]]:
        self.get(item_id, user_id)  # ownership check
        rows = self.store.fetchall(
            "SELECT * FROM cowork_subtasks WHERE item_id=? AND user_id=? ORDER BY position, created_at",
            (item_id, user_id),
        )
        return [self._decode_subtask(row) for row in rows]

    def add_subtask(self, item_id: str, user_id: str, title: str) -> Dict[str, Any]:
        self.get(item_id, user_id)
        title = title.strip()
        if not title:
            raise ValueError("Subtask title is required")
        sub_id, now = new_id("subtask"), utc_ms()
        row = self.store.fetchone(
            "SELECT COALESCE(MAX(position),-1)+1 AS next FROM cowork_subtasks WHERE item_id=?",
            (item_id,),
        )
        position = int(row["next"]) if row else 0
        with self.store.transaction() as conn:
            conn.execute(
                """INSERT INTO cowork_subtasks (id,item_id,user_id,title,status,position,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (sub_id, item_id, user_id, title, "pending", position, now, now),
            )
        return self._get_subtask(sub_id, user_id)

    def update_subtask(
        self, subtask_id: str, user_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        current = self._get_subtask(subtask_id, user_id)
        title = str(changes.get("title", current["title"])).strip() or current["title"]
        status = changes.get("status", current["status"])
        if status not in {"pending", "done"}:
            raise ValueError("Subtask status must be pending or done")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE cowork_subtasks SET title=?,status=?,updated_at=? WHERE id=? AND user_id=?",
                (title, status, utc_ms(), subtask_id, user_id),
            )
        return self._get_subtask(subtask_id, user_id)

    def delete_subtask(self, subtask_id: str, user_id: str) -> None:
        self._get_subtask(subtask_id, user_id)
        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM cowork_subtasks WHERE id=? AND user_id=?",
                (subtask_id, user_id),
            )

    def _get_subtask(self, subtask_id: str, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM cowork_subtasks WHERE id=? AND user_id=?",
            (subtask_id, user_id),
        )
        if not row:
            raise KeyError(subtask_id)
        return self._decode_subtask(row)

    @staticmethod
    def _decode_subtask(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "itemId": row["item_id"],
            "title": row["title"],
            "status": row["status"],
            "position": row["position"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    # ── Schedules (recurring automatic runs) ─────────────────────────────

    def list_schedules(self, item_id: str, user_id: str) -> list[Dict[str, Any]]:
        self.get(item_id, user_id)
        rows = self.store.fetchall(
            "SELECT * FROM cowork_schedules WHERE item_id=? AND user_id=? ORDER BY created_at DESC",
            (item_id, user_id),
        )
        return [self._decode_schedule(row) for row in rows]

    def create_schedule(
        self,
        item_id: str,
        user_id: str,
        *,
        cadence: str = "daily",
        interval_minutes: Optional[int] = None,
        time_of_day: Optional[str] = None,
        weekdays: Optional[list[int]] = None,
        mode: str = "agent",
        workspace_path: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        self.get(item_id, user_id)
        validate_cadence(cadence, interval_minutes, time_of_day, weekdays)
        if mode not in {"safe", "agent"}:
            raise ValueError("Schedule mode must be safe or agent")
        resolved_workspace = (
            str(resolve_workspace_directory(workspace_path)) if workspace_path else None
        )
        now, sched_id = utc_ms(), new_id("coworksched")
        next_at = compute_next_run(
            cadence, now, interval_minutes, time_of_day, weekdays
        )
        with self.store.transaction() as conn:
            conn.execute(
                """INSERT INTO cowork_schedules
                   (id,item_id,user_id,cadence,interval_minutes,time_of_day,weekdays_json,
                    mode,workspace_path,model,effort,enabled,next_run_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sched_id,
                    item_id,
                    user_id,
                    cadence,
                    interval_minutes,
                    time_of_day,
                    json_dumps(weekdays or []),
                    mode,
                    resolved_workspace,
                    model,
                    effort,
                    int(enabled),
                    next_at,
                    now,
                    now,
                ),
            )
        return self._get_schedule(sched_id, user_id)

    def update_schedule(
        self, schedule_id: str, user_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        current = self._get_schedule(schedule_id, user_id)
        allowed = {
            "cadence",
            "intervalMinutes",
            "timeOfDay",
            "weekdays",
            "mode",
            "workspacePath",
            "model",
            "effort",
            "enabled",
        }
        values = {key: current[key] for key in allowed}
        values.update({k: v for k, v in changes.items() if k in allowed})
        validate_cadence(
            values["cadence"],
            values["intervalMinutes"],
            values["timeOfDay"],
            values["weekdays"],
        )
        if values["mode"] not in {"safe", "agent"}:
            raise ValueError("Schedule mode must be safe or agent")
        workspace = (
            str(resolve_workspace_directory(values["workspacePath"]))
            if values["workspacePath"]
            else None
        )
        next_at = current["nextRunAt"]
        if any(
            k in changes
            for k in ("cadence", "intervalMinutes", "timeOfDay", "weekdays")
        ):
            next_at = compute_next_run(
                values["cadence"],
                utc_ms(),
                values["intervalMinutes"],
                values["timeOfDay"],
                values["weekdays"],
            )
        with self.store.transaction() as conn:
            conn.execute(
                """UPDATE cowork_schedules SET cadence=?,interval_minutes=?,time_of_day=?,
                   weekdays_json=?,mode=?,workspace_path=?,model=?,effort=?,enabled=?,
                   next_run_at=?,updated_at=? WHERE id=? AND user_id=?""",
                (
                    values["cadence"],
                    values["intervalMinutes"],
                    values["timeOfDay"],
                    json_dumps(values["weekdays"] or []),
                    values["mode"],
                    workspace,
                    values["model"],
                    values["effort"],
                    int(values["enabled"]),
                    next_at,
                    utc_ms(),
                    schedule_id,
                    user_id,
                ),
            )
        return self._get_schedule(schedule_id, user_id)

    def delete_schedule(self, schedule_id: str, user_id: str) -> None:
        self._get_schedule(schedule_id, user_id)
        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM cowork_schedules WHERE id=? AND user_id=?",
                (schedule_id, user_id),
            )

    def dispatch_due_schedules(self, limit: int = 25) -> list[Dict[str, Any]]:
        """
        Dispatch a Cowork run for every enabled schedule that is due, advancing
        each schedule's next_run_at. Skips (without erroring) any item that is
        already running. Returns the newly-created run dicts to execute.
        """
        now = utc_ms()
        rows = self.store.fetchall(
            "SELECT * FROM cowork_schedules WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at LIMIT ?",
            (now, max(1, min(limit, 100))),
        )
        dispatched: list[Dict[str, Any]] = []
        for row in rows:
            sched = self._decode_schedule(row)
            next_at = compute_next_run(
                sched["cadence"],
                now,
                sched["intervalMinutes"],
                sched["timeOfDay"],
                sched["weekdays"],
            )
            try:
                run = self.dispatch(
                    sched["itemId"],
                    sched["userId"],
                    mode=sched["mode"],
                    workspace_path=sched["workspacePath"],
                    model=sched["model"],
                    effort=sched["effort"],
                )
                dispatched.append(run)
                last_status = "queued"
            except ValueError:
                # Item already running (or invalid) — skip this tick, try next time.
                last_status = "skipped"
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE cowork_schedules SET next_run_at=?,last_run_at=?,last_status=?,updated_at=? WHERE id=?",
                    (next_at, now, last_status, now, sched["id"]),
                )
        return dispatched

    def _get_schedule(self, schedule_id: str, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM cowork_schedules WHERE id=? AND user_id=?",
            (schedule_id, user_id),
        )
        if not row:
            raise KeyError(schedule_id)
        return self._decode_schedule(row)

    @staticmethod
    def _decode_schedule(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "itemId": row["item_id"],
            "userId": row["user_id"],
            "cadence": row["cadence"],
            "intervalMinutes": row["interval_minutes"],
            "timeOfDay": row["time_of_day"],
            "weekdays": json_loads(row["weekdays_json"], []),
            "mode": row["mode"],
            "workspacePath": row["workspace_path"],
            "model": row["model"],
            "effort": row["effort"],
            "enabled": bool(row["enabled"]),
            "nextRunAt": row["next_run_at"],
            "lastRunAt": row["last_run_at"],
            "lastStatus": row["last_status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _validate(status: str, priority: str) -> None:
        if status not in COWORK_STATUSES:
            raise ValueError("Unknown cowork status")
        if priority not in COWORK_PRIORITIES:
            raise ValueError("Unknown cowork priority")

    @staticmethod
    def _clean_tags(tags: Optional[list[str]]) -> list[str]:
        return list(
            dict.fromkeys(str(tag).strip() for tag in (tags or []) if str(tag).strip())
        )[:20]

    @staticmethod
    def _activity(
        conn: Any,
        item_id: str,
        user_id: str,
        event_type: str,
        detail: Dict[str, Any],
        created_at: int,
    ) -> None:
        conn.execute(
            "INSERT INTO cowork_activity (item_id,user_id,event_type,detail_json,created_at) VALUES (?,?,?,?,?)",
            (item_id, user_id, event_type, json_dumps(detail), created_at),
        )

    @staticmethod
    def _decode(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "assignee": row["assignee"],
            "dueAt": row["due_at"],
            "tags": json_loads(row["tags_json"], []),
            "conversationId": row["conversation_id"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _decode_run(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "itemId": row["item_id"],
            "userId": row["user_id"],
            "taskId": row["task_id"],
            "mode": row["mode"],
            "workspacePath": row["workspace_path"],
            "status": row["status"],
            "output": json_loads(row["output_json"]),
            "error": row["error"],
            "startedAt": row["started_at"],
            "completedAt": row["completed_at"],
        }


class SkillPackageService:
    """
    Server-persisted Skills: reusable instructions plus an optional bundled
    script, replacing the old localStorage prompt-picker. find_matching()
    lets a caller auto-trigger a skill by relevance instead of requiring the
    user to pick one manually from a menu every time.
    """

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def create(
        self,
        user_id: str,
        name: str,
        instructions: str,
        *,
        description: str = "",
        script: Optional[str] = None,
    ) -> Dict[str, Any]:
        name = name.strip()
        instructions = instructions.strip()
        if not name or not instructions:
            raise ValueError("Name and instructions are required")
        skill_id, now = new_id("skill"), utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """INSERT INTO skill_packages
                   (id,user_id,name,description,instructions,script,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    skill_id,
                    user_id,
                    name,
                    description.strip(),
                    instructions,
                    script.strip() if script else None,
                    now,
                    now,
                ),
            )
        return self.get(skill_id, user_id)

    def list(self, user_id: str) -> list[Dict[str, Any]]:
        rows = self.store.fetchall(
            "SELECT * FROM skill_packages WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [self._decode(row) for row in rows]

    def get(self, skill_id: str, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM skill_packages WHERE id=? AND user_id=?", (skill_id, user_id)
        )
        if not row:
            raise KeyError(skill_id)
        return self._decode(row)

    def update(
        self, skill_id: str, user_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        current = self.get(skill_id, user_id)
        allowed_keys = {"name", "description", "instructions", "script"}
        values = {key: current[key] for key in allowed_keys}
        values.update({k: v for k, v in changes.items() if k in allowed_keys})
        name = str(values["name"]).strip()
        instructions = str(values["instructions"]).strip()
        if not name or not instructions:
            raise ValueError("Name and instructions are required")
        with self.store.transaction() as conn:
            conn.execute(
                """UPDATE skill_packages SET name=?,description=?,instructions=?,script=?,
                   updated_at=? WHERE id=? AND user_id=?""",
                (
                    name,
                    str(values["description"] or "").strip(),
                    instructions,
                    (
                        (str(values["script"]).strip() or None)
                        if values["script"]
                        else None
                    ),
                    utc_ms(),
                    skill_id,
                    user_id,
                ),
            )
        return self.get(skill_id, user_id)

    def delete(self, skill_id: str, user_id: str) -> None:
        self.get(skill_id, user_id)
        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM skill_packages WHERE id=? AND user_id=?",
                (skill_id, user_id),
            )

    def find_matching(
        self, user_id: str, message: str, min_score: int = 2
    ) -> Optional[Dict[str, Any]]:
        """
        Best-matching skill for a free-text message, by word-overlap scoring
        against each skill's name + description (same lightweight approach as
        ToolRegistry.search_tools — no embeddings, instant, dependency-free).

        Returns None if nothing scores at least min_score, so a generic
        message doesn't spuriously auto-trigger an unrelated skill.
        """
        words = [w for w in message.lower().split() if len(w) > 2]
        if not words:
            return None
        best: Optional[Dict[str, Any]] = None
        best_score = 0
        for skill in self.list(user_id):
            haystack = f"{skill['name']} {skill['description']}".lower()
            score = sum(haystack.count(w) for w in words)
            if any(w in skill["name"].lower() for w in words):
                score += 3
            if score > best_score:
                best_score, best = score, skill
        return best if best_score >= min_score else None

    @staticmethod
    def _decode(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "userId": row["user_id"],
            "name": row["name"],
            "description": row["description"],
            "instructions": row["instructions"],
            "script": row["script"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }


class AgentDefinitionService:
    """
    Named subagent types: a persisted (system_prompt, allowed_tools, model,
    effort) bundle a caller can dispatch prompts against — real personas with
    their own tool scoping, not just a raw prompt string handed to a generic
    thread-pool runner.
    """

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def create(
        self,
        user_id: str,
        name: str,
        system_prompt: str,
        *,
        description: str = "",
        allowed_tools: Optional[list[str]] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        name = name.strip()
        system_prompt = system_prompt.strip()
        if not name or not system_prompt:
            raise ValueError("Name and system prompt are required")
        def_id, now = new_id("agentdef"), utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """INSERT INTO agent_definitions
                   (id,user_id,name,description,system_prompt,allowed_tools_json,
                    model,effort,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    def_id,
                    user_id,
                    name,
                    description.strip(),
                    system_prompt,
                    json_dumps(list(allowed_tools or [])),
                    model,
                    effort,
                    now,
                    now,
                ),
            )
        return self.get(def_id, user_id)

    def list(self, user_id: str) -> list[Dict[str, Any]]:
        rows = self.store.fetchall(
            "SELECT * FROM agent_definitions WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [self._decode(row) for row in rows]

    def get(self, definition_id: str, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM agent_definitions WHERE id=? AND user_id=?",
            (definition_id, user_id),
        )
        if not row:
            raise KeyError(definition_id)
        return self._decode(row)

    def update(
        self, definition_id: str, user_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        current = self.get(definition_id, user_id)
        allowed_keys = {
            "name",
            "description",
            "systemPrompt",
            "allowedTools",
            "model",
            "effort",
        }
        values = {
            "name": current["name"],
            "description": current["description"],
            "systemPrompt": current["systemPrompt"],
            "allowedTools": current["allowedTools"],
            "model": current["model"],
            "effort": current["effort"],
        }
        values.update({k: v for k, v in changes.items() if k in allowed_keys})
        name = str(values["name"]).strip()
        system_prompt = str(values["systemPrompt"]).strip()
        if not name or not system_prompt:
            raise ValueError("Name and system prompt are required")
        with self.store.transaction() as conn:
            conn.execute(
                """UPDATE agent_definitions SET name=?,description=?,system_prompt=?,
                   allowed_tools_json=?,model=?,effort=?,updated_at=? WHERE id=? AND user_id=?""",
                (
                    name,
                    str(values["description"] or "").strip(),
                    system_prompt,
                    json_dumps(list(values["allowedTools"] or [])),
                    values["model"],
                    values["effort"],
                    utc_ms(),
                    definition_id,
                    user_id,
                ),
            )
        return self.get(definition_id, user_id)

    def delete(self, definition_id: str, user_id: str) -> None:
        self.get(definition_id, user_id)
        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM agent_definitions WHERE id=? AND user_id=?",
                (definition_id, user_id),
            )

    def dispatch_parallel(
        self,
        assignments: Dict[str, Dict[str, str]],
        user_id: str,
        run_one: Callable[[Dict[str, Any], str], Any],
        *,
        max_workers: int = 4,
    ) -> Dict[str, Any]:
        """
        Fan out {role: {"definitionId":..., "prompt":...}} in parallel.

        run_one(definition_dict, prompt) -> result is supplied by the caller
        (the API layer, which knows how to build a scoped AgentProxy/AgentLoop
        run) — this method only resolves each definition and hands the pair
        to SubagentCoordinator for bounded parallel execution.
        """
        from dabba.platform.coding import SubagentCoordinator

        resolved: Dict[str, tuple[Dict[str, Any], str]] = {}
        for role, spec in assignments.items():
            definition = self.get(spec["definitionId"], user_id)
            resolved[role] = (definition, spec.get("prompt", ""))

        def runner(role: str, _unused_prompt: str) -> Any:
            definition, prompt = resolved[role]
            return run_one(definition, prompt)

        # SubagentCoordinator.run's second positional arg to the runner is
        # unused here since resolved[] already carries the real prompt; pass
        # the role as both the dict key and value to satisfy its signature.
        return SubagentCoordinator().run(
            {role: role for role in assignments},
            runner,
            max_workers=max_workers,
        )

    @staticmethod
    def _decode(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "userId": row["user_id"],
            "name": row["name"],
            "description": row["description"],
            "systemPrompt": row["system_prompt"],
            "allowedTools": json_loads(row["allowed_tools_json"], []),
            "model": row["model"],
            "effort": row["effort"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }


class ScheduledSkillService:
    """Durable skill schedules that dispatch work into the platform task queue."""

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()
        self.tasks = TaskOrchestrator(self.store)

    def create(
        self,
        user_id: str,
        name: str,
        skill_name: str,
        instructions: str,
        *,
        cadence: str = "daily",
        interval_minutes: Optional[int] = None,
        time_of_day: Optional[str] = None,
        weekdays: Optional[list[int]] = None,
        enabled: bool = True,
        next_run_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._validate(
            name, instructions, cadence, interval_minutes, time_of_day, weekdays
        )
        now, schedule_id = utc_ms(), new_id("schedule")
        next_at = next_run_at or self._next_run(
            cadence, now, interval_minutes, time_of_day, weekdays
        )
        with self.store.transaction() as conn:
            conn.execute(
                """INSERT INTO scheduled_skills
                   (id,user_id,name,skill_name,instructions,cadence,interval_minutes,
                    time_of_day,weekdays_json,enabled,next_run_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    schedule_id,
                    user_id,
                    name.strip(),
                    skill_name.strip() or name.strip(),
                    instructions.strip(),
                    cadence,
                    interval_minutes,
                    time_of_day,
                    json_dumps(weekdays or []),
                    int(enabled),
                    next_at,
                    now,
                    now,
                ),
            )
        return self.get(schedule_id, user_id)

    def list(self, user_id: str) -> list[Dict[str, Any]]:
        rows = self.store.fetchall(
            "SELECT * FROM scheduled_skills WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [self._decode(row) for row in rows]

    def get(self, schedule_id: str, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM scheduled_skills WHERE id=? AND user_id=?",
            (schedule_id, user_id),
        )
        if not row:
            raise KeyError(schedule_id)
        return self._decode(row)

    def update(
        self, schedule_id: str, user_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        current = self.get(schedule_id, user_id)
        allowed = {
            "name",
            "skillName",
            "instructions",
            "cadence",
            "intervalMinutes",
            "timeOfDay",
            "weekdays",
            "enabled",
            "nextRunAt",
        }
        changes = {key: value for key, value in changes.items() if key in allowed}
        values = {key: current[key] for key in allowed}
        values.update(changes)
        self._validate(
            values["name"],
            values["instructions"],
            values["cadence"],
            values["intervalMinutes"],
            values["timeOfDay"],
            values["weekdays"],
        )
        if any(
            key in changes
            for key in ("cadence", "intervalMinutes", "timeOfDay", "weekdays")
        ):
            values["nextRunAt"] = self._next_run(
                values["cadence"],
                utc_ms(),
                values["intervalMinutes"],
                values["timeOfDay"],
                values["weekdays"],
            )
        with self.store.transaction() as conn:
            conn.execute(
                """UPDATE scheduled_skills SET name=?,skill_name=?,instructions=?,cadence=?,
                   interval_minutes=?,time_of_day=?,weekdays_json=?,enabled=?,next_run_at=?,updated_at=?
                   WHERE id=? AND user_id=?""",
                (
                    str(values["name"]).strip(),
                    str(values["skillName"]).strip(),
                    str(values["instructions"]).strip(),
                    values["cadence"],
                    values["intervalMinutes"],
                    values["timeOfDay"],
                    json_dumps(values["weekdays"] or []),
                    int(values["enabled"]),
                    values["nextRunAt"],
                    utc_ms(),
                    schedule_id,
                    user_id,
                ),
            )
        return self.get(schedule_id, user_id)

    def delete(self, schedule_id: str, user_id: str) -> None:
        self.get(schedule_id, user_id)
        with self.store.transaction() as conn:
            conn.execute(
                "DELETE FROM scheduled_skills WHERE id=? AND user_id=?",
                (schedule_id, user_id),
            )

    def dispatch(
        self, schedule_id: str, user_id: str, triggered_by: str = "manual"
    ) -> Dict[str, Any]:
        schedule = self.get(schedule_id, user_id)
        task = self.tasks.create(
            "scheduled_skill",
            {
                "scheduleId": schedule_id,
                "skillName": schedule["skillName"],
                "instructions": schedule["instructions"],
                "triggeredBy": triggered_by,
            },
            user_id=user_id,
            idempotency_key=(
                f"schedule:{schedule_id}:{schedule['nextRunAt']}"
                if triggered_by == "schedule"
                else None
            ),
        )
        now, run_id = utc_ms(), new_id("run")
        next_at = self._next_run(
            schedule["cadence"],
            now,
            schedule["intervalMinutes"],
            schedule["timeOfDay"],
            schedule["weekdays"],
        )
        with self.store.transaction() as conn:
            conn.execute(
                """INSERT INTO scheduled_skill_runs
                   (id,schedule_id,user_id,task_id,status,triggered_by,output_json,started_at,completed_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    schedule_id,
                    user_id,
                    task["id"],
                    "queued",
                    triggered_by,
                    json_dumps({"message": "Dispatched to durable task queue"}),
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE scheduled_skills SET last_run_at=?,last_status='queued',next_run_at=?,updated_at=? WHERE id=?",
                (now, next_at, now, schedule_id),
            )
        return self.get_run(run_id, user_id)

    def dispatch_due(self, limit: int = 25) -> list[Dict[str, Any]]:
        now = utc_ms()
        rows = self.store.fetchall(
            "SELECT id,user_id FROM scheduled_skills WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at LIMIT ?",
            (now, max(1, min(limit, 100))),
        )
        return [self.dispatch(row["id"], row["user_id"], "schedule") for row in rows]

    def execute(
        self, run_id: str, user_id: str, executor: Callable[[str], str]
    ) -> Dict[str, Any]:
        """Execute a dispatched run and mirror its outcome into task and run history."""
        run = self.get_run(run_id, user_id)
        schedule = self.get(run["scheduleId"], user_id)

        def handler(
            _request: Dict[str, Any], progress: Callable[[float, str], None]
        ) -> Dict[str, Any]:
            progress(0.2, "Running scheduled skill")
            content = executor(schedule["instructions"])
            progress(0.9, "Saving result")
            return {"content": content, "scheduleId": schedule["id"]}

        task = self.tasks.run(run["taskId"], handler)
        status = task["status"]
        error = (task.get("error") or {}).get("message") if task.get("error") else None
        with self.store.transaction() as conn:
            conn.execute(
                """UPDATE scheduled_skill_runs SET status=?,output_json=?,error=?,completed_at=?
                   WHERE id=? AND user_id=?""",
                (
                    status,
                    (
                        json_dumps(task.get("result"))
                        if task.get("result") is not None
                        else None
                    ),
                    error,
                    utc_ms(),
                    run_id,
                    user_id,
                ),
            )
            conn.execute(
                "UPDATE scheduled_skills SET last_status=?,updated_at=? WHERE id=? AND user_id=?",
                (status, utc_ms(), schedule["id"], user_id),
            )
        return self.get_run(run_id, user_id)

    def runs(
        self, user_id: str, schedule_id: Optional[str] = None, limit: int = 50
    ) -> list[Dict[str, Any]]:
        if schedule_id:
            self.get(schedule_id, user_id)
            rows = self.store.fetchall(
                "SELECT * FROM scheduled_skill_runs WHERE user_id=? AND schedule_id=? ORDER BY started_at DESC LIMIT ?",
                (user_id, schedule_id, limit),
            )
        else:
            rows = self.store.fetchall(
                "SELECT * FROM scheduled_skill_runs WHERE user_id=? ORDER BY started_at DESC LIMIT ?",
                (user_id, limit),
            )
        return [self._decode_run(row) for row in rows]

    def get_run(self, run_id: str, user_id: str) -> Dict[str, Any]:
        row = self.store.fetchone(
            "SELECT * FROM scheduled_skill_runs WHERE id=? AND user_id=?",
            (run_id, user_id),
        )
        if not row:
            raise KeyError(run_id)
        return self._decode_run(row)

    @staticmethod
    def _validate(
        name: str,
        instructions: str,
        cadence: str,
        interval_minutes: Optional[int],
        time_of_day: Optional[str],
        weekdays: Optional[list[int]],
    ) -> None:
        if not str(name).strip() or not str(instructions).strip():
            raise ValueError("Name and instructions are required")
        if cadence not in {"interval", "daily", "weekly"}:
            raise ValueError("Cadence must be interval, daily, or weekly")
        if cadence == "interval" and (not interval_minutes or interval_minutes < 5):
            raise ValueError("Interval must be at least 5 minutes")
        if cadence in {"daily", "weekly"}:
            try:
                hour, minute = map(int, str(time_of_day or "09:00").split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError("Time must use HH:MM")
        if cadence == "weekly" and not all(day in range(7) for day in (weekdays or [])):
            raise ValueError("Weekdays must be between 0 and 6")

    @staticmethod
    def _next_run(
        cadence: str,
        after_ms: int,
        interval_minutes: Optional[int],
        time_of_day: Optional[str],
        weekdays: Optional[list[int]],
    ) -> int:
        after = datetime.fromtimestamp(after_ms / 1000, tz=timezone.utc)
        if cadence == "interval":
            return int(
                (after + timedelta(minutes=interval_minutes or 60)).timestamp() * 1000
            )
        hour, minute = map(int, (time_of_day or "09:00").split(":"))
        candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        if cadence == "weekly":
            valid = set(weekdays or [0])
            while candidate.weekday() not in valid:
                candidate += timedelta(days=1)
        return int(candidate.timestamp() * 1000)

    @staticmethod
    def _decode(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "skillName": row["skill_name"],
            "instructions": row["instructions"],
            "cadence": row["cadence"],
            "intervalMinutes": row["interval_minutes"],
            "timeOfDay": row["time_of_day"],
            "weekdays": json_loads(row["weekdays_json"], []),
            "enabled": bool(row["enabled"]),
            "nextRunAt": row["next_run_at"],
            "lastRunAt": row["last_run_at"],
            "lastStatus": row["last_status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _decode_run(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "scheduleId": row["schedule_id"],
            "userId": row["user_id"],
            "taskId": row["task_id"],
            "status": row["status"],
            "triggeredBy": row["triggered_by"],
            "output": json_loads(row["output_json"], None),
            "error": row["error"],
            "startedAt": row["started_at"],
            "completedAt": row["completed_at"],
        }
