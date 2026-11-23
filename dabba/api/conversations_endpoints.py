"""Persist web chat history in SQLite, scoped to the authenticated user."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
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
        authorization: Optional[str] = Header(default=None),
    ):
        user = authenticated_user(authorization)
        if user_id != user["id"]:
            raise HTTPException(
                status_code=403, detail="Cannot read another user's conversations"
            )
        conn = _get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            return {"conversations": [_row_to_dict(r) for r in rows]}
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
                    project_id=excluded.project_id
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
            return {"ok": True}
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
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Conversation not found")
            return {"deleted": conversation_id}
        finally:
            conn.close()

    return router
