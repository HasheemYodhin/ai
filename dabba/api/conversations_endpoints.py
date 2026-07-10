"""
Conversation persistence — POST/GET/DELETE /v1/conversations.

Backs the web frontend's chat history: previously conversations lived only
in the browser's localStorage (lost on clearing browser data, not shared
across devices). This stores them server-side in SQLite instead, scoped by
`user_id` — a client-generated id from the frontend's local-only auth
profile (see useAuth.tsx). There is no real authentication here: any
caller who knows a user_id can read/write that user's conversations. That
matches the frontend's "local-only profile" design (no server-side account
system) — do not reuse this pattern if real multi-user security is needed.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dabba.utils.paths import get_dabba_config_dir

DB_PATH = get_dabba_config_dir() / "conversations.db"


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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)")
    return conn


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

    @router.get("/conversations")
    async def list_conversations(user_id: str):
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
    async def upsert_conversation(conversation_id: str, body: ConversationUpsert):
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
                    body.id, body.userId, body.title, json.dumps(body.messages),
                    body.createdAt, body.updatedAt, int(body.pinned), int(body.customTitle), body.projectId,
                ),
            )
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()

    @router.delete("/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str, user_id: str):
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
