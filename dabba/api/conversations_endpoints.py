"""Persist web chat history in SQLite, scoped to the authenticated user."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from dabba.platform.core import get_platform_data_dir
from dabba.platform.services import IdentityService

DB_PATH = get_platform_data_dir() / "conversations.db"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            messages TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0,
            custom_title INTEGER NOT NULL DEFAULT 0,
            project_id TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)"
    )
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        _initialize_message_index(conn)
    if conn.execute("PRAGMA user_version").fetchone()[0] < 2:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("PRAGMA user_version").fetchone()[0] < 2:
                conn.execute(
                    "ALTER TABLE conversations ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
                )
                conn.execute("""CREATE TABLE conversation_deletions (
                    user_id TEXT NOT NULL, id TEXT NOT NULL, PRIMARY KEY (user_id, id)
                )""")
                conn.execute("PRAGMA user_version = 2")
    return conn


def _initialize_message_index(conn: sqlite3.Connection) -> None:
    # One atomic migration, including existing conversations and all future writes.
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] >= 1:
            conn.commit()
            return
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                conversation_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                role TEXT,
                model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                timestamp INTEGER,
                content TEXT,
                PRIMARY KEY (conversation_id, position)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_model_timestamp ON messages(model, timestamp)"
        )
        columns = """
            conversation_id, position, role, model, prompt_tokens, completion_tokens,
            timestamp, content
        """
        message_fields = """
            message.key, json_extract(message.value, '$.role'),
            json_extract(message.value, '$.model'),
            json_extract(message.value, '$.usage.promptTokens'),
            json_extract(message.value, '$.usage.completionTokens'),
            json_extract(message.value, '$.timestamp'), json_extract(message.value, '$.content')
        """
        conn.execute(f"""
            INSERT INTO messages ({columns})
            SELECT conversation.id, {message_fields}
            FROM conversations AS conversation, json_each(conversation.messages) AS message
            WHERE message.type = 'object'
        """)
        for event in ("INSERT", "UPDATE OF messages"):
            trigger_name = (
                "index_message_insert" if event == "INSERT" else "index_message_update"
            )
            conn.execute(f"""
                CREATE TRIGGER {trigger_name} AFTER {event} ON conversations BEGIN
                    DELETE FROM messages WHERE conversation_id = NEW.id;
                    INSERT INTO messages ({columns})
                    SELECT NEW.id, {message_fields}
                    FROM json_each(NEW.messages) AS message WHERE message.type = 'object';
                END
            """)
        conn.execute("""
            CREATE TRIGGER index_message_delete AFTER DELETE ON conversations BEGIN
                DELETE FROM messages WHERE conversation_id = OLD.id;
            END
        """)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "messages": json.loads(row["messages"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "pinned": bool(row["pinned"]),
        "customTitle": bool(row["custom_title"]),
        "projectId": row["project_id"],
        "revision": row["revision"],
    }


def _row_to_summary(row: sqlite3.Row) -> Dict[str, Any]:
    """Sidebar entry without message bodies (messages load when a chat opens)."""
    return {
        "id": row["id"],
        "title": row["title"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "pinned": bool(row["pinned"]),
        "customTitle": bool(row["custom_title"]),
        "projectId": row["project_id"],
        "revision": row["revision"],
        "messageCount": row["message_count"],
    }


class ConversationUpsert(BaseModel):
    id: str
    userId: str
    title: str
    messages: List[Dict[str, Any]]
    createdAt: int
    updatedAt: int
    pinned: bool = False
    customTitle: bool = False
    projectId: Optional[str] = None
    revision: Optional[int] = None


def create_conversations_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["conversations"])
    identity = IdentityService()

    def authenticated_user(authorization: Optional[str]) -> Dict[str, Any]:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        user = identity.authenticate(authorization.split(" ", 1)[1].strip())
        if not user:
            raise HTTPException(status_code=401, detail="Session is invalid or expired")
        return user

    @router.get("/conversations")
    async def list_conversations(
        user_id: str,
        include_messages: bool = True,
        authorization: Optional[str] = Header(default=None),
    ):
        """List the user's conversations.

        include_messages=true (default, original shape) returns every message of
        every chat; the web app passes false to get a lightweight sidebar list
        and fetches each chat's messages via GET /conversations/{id}.
        """
        user = authenticated_user(authorization)
        if user_id != user["id"]:
            raise HTTPException(
                status_code=403, detail="Cannot read another user's conversations"
            )
        conn = _get_db()
        try:
            if include_messages:
                rows = conn.execute(
                    "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
                    (user_id,),
                ).fetchall()
                return {"conversations": [_row_to_dict(r) for r in rows]}
            # json_array_length avoids sending (or parsing in Python) the bodies.
            rows = conn.execute(
                """
                SELECT id, title, created_at, updated_at, pinned, custom_title,
                       project_id, revision, json_array_length(messages) AS message_count
                FROM conversations WHERE user_id = ? ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
            return {"conversations": [_row_to_summary(r) for r in rows]}
        finally:
            conn.close()

    @router.get("/conversations/search")
    def search_conversations(
        q: str = Query(min_length=1, max_length=120),
        limit: int = Query(default=30, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=10_000),
        authorization: Optional[str] = Header(default=None),
    ):
        user = authenticated_user(authorization)
        needle = q.strip().lower()
        if not needle:
            return {"matches": []}
        conn = _get_db()
        try:
            rows = conn.execute(
                """WITH matches AS (
                       SELECT c.id, c.title, c.updated_at,
                              (SELECT substr(m.content, max(1, instr(lower(m.content), ?) - 45), 150)
                               FROM messages m WHERE m.conversation_id = c.id
                                 AND instr(lower(m.content), ?) > 0
                               ORDER BY m.position DESC LIMIT 1) AS snippet
                       FROM conversations c WHERE c.user_id = ?
                   )
                   SELECT id, snippet FROM matches
                   WHERE snippet IS NOT NULL OR instr(lower(title), ?) > 0
                   ORDER BY updated_at DESC, id LIMIT ? OFFSET ?""",
                (needle, needle, user["id"], needle, limit, offset),
            ).fetchall()
            return {"matches": [dict(row) for row in rows]}
        finally:
            conn.close()

    @router.get("/conversations/{conversation_id}")
    async def get_conversation(
        conversation_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        """One full conversation, only if the session user owns it."""
        user = authenticated_user(authorization)
        conn = _get_db()
        try:
            # Ownership is part of the query, so another user's id gets the
            # same 404 as a missing one (no existence leak).
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user["id"]),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            return _row_to_dict(row)
        finally:
            conn.close()

    @router.put("/conversations/{conversation_id}")
    async def upsert_conversation(
        conversation_id: str,
        body: ConversationUpsert,
        authorization: Optional[str] = Header(default=None),
    ):
        user = authenticated_user(authorization)
        if body.userId != user["id"]:
            raise HTTPException(
                status_code=403, detail="Cannot write another user's conversations"
            )
        if conversation_id != body.id:
            raise HTTPException(status_code=400, detail="URL id and body id must match")

        conn = _get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM conversation_deletions WHERE user_id=? AND id=?",
                (user["id"], conversation_id),
            ).fetchone():
                raise HTTPException(
                    status_code=409, detail="Conversation was deleted on another device"
                )
            existing = conn.execute(
                "SELECT user_id, revision FROM conversations WHERE id=?",
                (conversation_id,),
            ).fetchone()
            if existing:
                if existing["user_id"] != user["id"]:
                    raise HTTPException(
                        status_code=404, detail="Conversation not found"
                    )
                if body.revision != existing["revision"]:
                    raise HTTPException(
                        status_code=409, detail="Conversation changed on another device"
                    )
            elif body.revision:
                raise HTTPException(
                    status_code=409, detail="Conversation no longer exists"
                )
            conn.execute(
                """
                INSERT INTO conversations
                    (id, user_id, title, messages, created_at, updated_at, pinned, custom_title, project_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    messages=excluded.messages,
                    updated_at=excluded.updated_at,
                    pinned=excluded.pinned,
                    custom_title=excluded.custom_title,
                    project_id=excluded.project_id,
                    revision=conversations.revision + 1
                WHERE conversations.user_id = excluded.user_id
                """,
                (
                    body.id,
                    body.userId,
                    body.title,
                    json.dumps(body.messages),
                    body.createdAt,
                    body.updatedAt,
                    int(body.pinned),
                    int(body.customTitle),
                    body.projectId,
                ),
            )
            conn.commit()
            return {"ok": True, "revision": existing["revision"] + 1 if existing else 1}
        finally:
            conn.close()

    @router.delete("/conversations")
    def clear_conversations(authorization: Optional[str] = Header(default=None)):
        user_id = authenticated_user(authorization)["id"]
        conn = _get_db()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """INSERT OR IGNORE INTO conversation_deletions (user_id, id)
                       SELECT user_id, id FROM conversations WHERE user_id=?""",
                    (user_id,),
                )
                deleted = conn.execute(
                    "DELETE FROM conversations WHERE user_id=?", (user_id,)
                ).rowcount
            return {"deleted": deleted}
        finally:
            conn.close()

    @router.delete("/conversations/{conversation_id}")
    async def delete_conversation(
        conversation_id: str,
        user_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        user = authenticated_user(authorization)
        if user_id != user["id"]:
            raise HTTPException(
                status_code=403, detail="Cannot delete another user's conversations"
            )
        conn = _get_db()
        try:
            cur = conn.execute(
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Conversation not found")
            conn.execute(
                "INSERT OR IGNORE INTO conversation_deletions (user_id, id) VALUES (?, ?)",
                (user_id, conversation_id),
            )
            conn.commit()
            return {"deleted": conversation_id}
        finally:
            conn.close()

    return router
