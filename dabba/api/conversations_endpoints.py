"""Persist web chat history scoped to the authenticated user."""

from __future__ import annotations

import json
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from dabba.platform.core import get_platform_data_dir, get_platform_store, utc_ms
from dabba.platform.postgres import (
    PostgresConnection,
    CHAT_TOOLS_SCHEMA,
    database_url,
    initialize_postgres_conversations,
)
from dabba.platform.services import IdentityService

DB_PATH = get_platform_data_dir() / "conversations.db"


def _get_db() -> sqlite3.Connection | PostgresConnection:
    if url := database_url():
        return PostgresConnection(url, pooled=True)
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
    if conn.execute("PRAGMA user_version").fetchone()[0] < 3:
        conn.executescript(
            "BEGIN IMMEDIATE;" + CHAT_TOOLS_SCHEMA + "PRAGMA user_version=3; COMMIT;"
        )
    return conn


def _begin_write(conn: sqlite3.Connection | PostgresConnection) -> None:
    if isinstance(conn, PostgresConnection):
        conn.begin_write()
    else:
        conn.execute("BEGIN IMMEDIATE")


def conversation_usage_counts(user_id: str) -> dict[str, int]:
    conn = _get_db()
    try:
        row = conn.execute(
            """SELECT
                (SELECT COUNT(*) FROM conversations WHERE user_id=?) AS conversation_count,
                (SELECT COUNT(*) FROM messages m JOIN conversations c
                 ON c.id=m.conversation_id WHERE c.user_id=?) AS message_count""",
            (user_id, user_id),
        ).fetchone()
        return {
            "conversationCount": row["conversation_count"],
            "messageCount": row["message_count"],
        }
    finally:
        conn.close()


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


def _row_to_dict(row: sqlite3.Row | dict) -> Dict[str, Any]:
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


def _row_to_summary(row: sqlite3.Row | dict) -> Dict[str, Any]:
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


class ShareSelection(BaseModel):
    messageIds: list[str] = Field(min_length=1, max_length=50)
    revision: int


def _owned_chat(conn, user_id: str, chat_id: str):
    row = conn.execute(
        "SELECT title, messages, revision FROM conversations WHERE id=? AND user_id=?",
        (chat_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


def create_conversations_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["conversations"])
    identity = IdentityService()
    if url := database_url():
        initialize_postgres_conversations(url)

    def authenticated_user(
        request: Request, authorization: Optional[str] = Header(default=None)
    ) -> Dict[str, Any]:
        if user := getattr(request.state, "dabba_user", None):
            return user
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        user = identity.authenticate(authorization.split(" ", 1)[1].strip())
        if not user:
            raise HTTPException(status_code=401, detail="Session is invalid or expired")
        return user

    @router.get("/conversations/saved")
    def list_saved(user: Dict[str, Any] = Depends(authenticated_user)):
        user_id = user["id"]
        conn = _get_db()
        try:
            rows = conn.execute(
                """SELECT s.conversation_id, s.message_id, s.snippet, c.title
                   FROM saved_messages s JOIN conversations c
                     ON c.id=s.conversation_id AND c.user_id=s.user_id
                   WHERE s.user_id=? ORDER BY s.created_at DESC, s.message_id LIMIT 200""",
                (user_id,),
            ).fetchall()
            return {"items": [dict(row) for row in rows]}
        finally:
            conn.close()

    @router.get("/conversations/recovery")
    def recover_reply(
        request_id: str = Query(min_length=1, max_length=128),
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        user_id = user["id"]
        task = get_platform_store().fetchone(
            """SELECT status, result_json FROM tasks
               WHERE user_id=? AND idempotency_key=? AND kind='chat'""",
            (user_id, request_id),
        )
        if task is None:
            raise HTTPException(
                status_code=404, detail="No recoverable reply was found."
            )
        result = (
            json.loads(task["result_json"])
            if task["result_json"] and task["status"] == "completed"
            else None
        )
        return {"status": task["status"], "result": result}

    @router.put("/conversations/{chat_id}/saved/{message_id}", status_code=204)
    def save_message(
        chat_id: str,
        message_id: str,
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        user_id = user["id"]
        conn = _get_db()
        try:
            with conn:
                _begin_write(conn)
                chat = _owned_chat(conn, user_id, chat_id)
                message = next(
                    (
                        message
                        for message in json.loads(chat["messages"])
                        if isinstance(message, dict) and message.get("id") == message_id
                    ),
                    None,
                )
                if message is None:
                    raise HTTPException(status_code=404, detail="Message not found")
                conn.execute(
                    """INSERT INTO saved_messages (user_id, conversation_id, message_id, snippet, created_at)
                       VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, conversation_id, message_id) DO NOTHING""",
                    (
                        user_id,
                        chat_id,
                        message_id,
                        str(message.get("content") or "Attachment")[:200],
                        utc_ms(),
                    ),
                )
        finally:
            conn.close()

    @router.delete("/conversations/{chat_id}/saved/{message_id}", status_code=204)
    def unsave_message(
        chat_id: str,
        message_id: str,
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        user_id = user["id"]
        conn = _get_db()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM saved_messages WHERE user_id=? AND conversation_id=? AND message_id=?",
                    (user_id, chat_id, message_id),
                )
        finally:
            conn.close()

    @router.get("/conversations/{chat_id}/shares")
    def list_shares(chat_id: str, user: Dict[str, Any] = Depends(authenticated_user)):
        user_id = user["id"]
        conn = _get_db()
        try:
            rows = conn.execute(
                """SELECT id, created_at FROM chat_shares WHERE user_id=? AND conversation_id=?
                   ORDER BY created_at DESC LIMIT 50""",
                (user_id, chat_id),
            ).fetchall()
            return {"items": [dict(row) for row in rows]}
        finally:
            conn.close()

    @router.post("/conversations/{chat_id}/shares", status_code=201)
    def create_share(
        chat_id: str,
        body: ShareSelection,
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        user_id = user["id"]
        conn = _get_db()
        try:
            with conn:
                _begin_write(conn)
                chat = _owned_chat(conn, user_id, chat_id)
                if body.revision != chat["revision"]:
                    raise HTTPException(
                        status_code=409,
                        detail="This chat changed. Reopen the sharing preview.",
                    )
                selected = set(body.messageIds)
                messages = [
                    {"role": message["role"], "content": message["content"]}
                    for message in json.loads(chat["messages"])
                    if isinstance(message, dict)
                    and message.get("id") in selected
                    and message.get("role") in ("user", "assistant")
                    and not message.get("error")
                    and not message.get("recoveryRequestId")
                    and isinstance(message.get("content"), str)
                    and message["content"].strip()
                ]
                if len(messages) != len(selected):
                    raise HTTPException(
                        status_code=400, detail="Select saved text messages to share."
                    )
                content = json.dumps(messages, ensure_ascii=False)
                if len(content.encode("utf-8")) > 128 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail="Select fewer messages. A shared chat can contain up to 128 KB of text.",
                    )
                count = conn.execute(
                    "SELECT COUNT(*) AS total FROM chat_shares WHERE user_id=? AND conversation_id=?",
                    (user_id, chat_id),
                ).fetchone()["total"]
                if count >= 50:
                    raise HTTPException(
                        status_code=409,
                        detail="Revoke an existing link before creating another.",
                    )
                share_id = secrets.token_urlsafe(24)
                created_at = utc_ms()
                conn.execute(
                    """INSERT INTO chat_shares (id, user_id, conversation_id, title, messages, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (share_id, user_id, chat_id, chat["title"], content, created_at),
                )
            return {"id": share_id, "created_at": created_at}
        finally:
            conn.close()

    @router.delete("/conversations/{chat_id}/shares/{share_id}", status_code=204)
    def revoke_share(
        chat_id: str, share_id: str, user: Dict[str, Any] = Depends(authenticated_user)
    ):
        user_id = user["id"]
        conn = _get_db()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM chat_shares WHERE id=? AND conversation_id=? AND user_id=?",
                    (share_id, chat_id, user_id),
                )
        finally:
            conn.close()

    @router.get("/conversations/public/shares/{share_id}")
    def open_share(share_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex"
        conn = _get_db()
        try:
            row = conn.execute(
                "SELECT title, messages FROM chat_shares WHERE id=?", (share_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail="Shared chat is unavailable",
                    headers={"Cache-Control": "no-store"},
                )
            return {"title": row["title"], "messages": json.loads(row["messages"])}
        finally:
            conn.close()

    @router.get("/conversations")
    def list_conversations(
        user_id: str,
        include_messages: bool = True,
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        """List the user's conversations.

        include_messages=true (default, original shape) returns every message of
        every chat; the web app passes false to get a lightweight sidebar list
        and fetches each chat's messages via GET /conversations/{id}.
        """
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
            messages = (
                "messages::json" if isinstance(conn, PostgresConnection) else "messages"
            )
            rows = conn.execute(
                f"""
                SELECT id, title, created_at, updated_at, pinned, custom_title,
                       project_id, revision, json_array_length({messages}) AS message_count
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
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        needle = q.strip().lower()
        if not needle:
            return {"matches": []}
        conn = _get_db()
        try:
            if isinstance(conn, PostgresConnection):
                content_position = "strpos(lower(m.content), ?)"
                title_position = "strpos(lower(title), ?)"
                snippet_start = "greatest(1, " + content_position + " - 45)"
                json_object = "json_build_object"
                message_id = "c.messages::json -> m.position ->> 'id'"
            else:
                content_position = "instr(lower(m.content), ?)"
                title_position = "instr(lower(title), ?)"
                snippet_start = "max(1, " + content_position + " - 45)"
                json_object = "json_object"
                message_id = "json_extract(c.messages, '$[' || m.position || '].id')"
            rows = conn.execute(
                f"""WITH matches AS (
                       SELECT c.id, c.title, c.updated_at,
                              (SELECT CAST({json_object}(
                                   'snippet', substr(m.content, {snippet_start}, 150),
                                   'messageId', {message_id}
                               ) AS TEXT)
                               FROM messages m WHERE m.conversation_id = c.id
                                 AND {content_position} > 0
                               ORDER BY m.position DESC LIMIT 1) AS hit
                       FROM conversations c WHERE c.user_id = ?
                   )
                   SELECT id, hit FROM matches
                   WHERE hit IS NOT NULL OR {title_position} > 0
                   ORDER BY updated_at DESC, id LIMIT ? OFFSET ?""",
                (needle, needle, user["id"], needle, limit, offset),
            ).fetchall()
            return {
                "matches": [
                    {
                        "id": row["id"],
                        **(
                            json.loads(row["hit"])
                            if row["hit"]
                            else {"snippet": None, "messageId": None}
                        ),
                    }
                    for row in rows
                ]
            }
        finally:
            conn.close()

    @router.get("/conversations/{conversation_id}")
    def get_conversation(
        conversation_id: str,
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        """One full conversation, only if the session user owns it."""
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
    def upsert_conversation(
        conversation_id: str,
        body: ConversationUpsert,
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        if body.userId != user["id"]:
            raise HTTPException(
                status_code=403, detail="Cannot write another user's conversations"
            )
        if conversation_id != body.id:
            raise HTTPException(status_code=400, detail="URL id and body id must match")

        conn = _get_db()
        try:
            _begin_write(conn)
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
            kept = {
                message.get("id")
                for message in body.messages
                if isinstance(message.get("id"), str)
            }
            saved = conn.execute(
                "SELECT message_id FROM saved_messages WHERE conversation_id=? AND user_id=?",
                (conversation_id, user["id"]),
            ).fetchall()
            for row in saved:
                if row["message_id"] not in kept:
                    conn.execute(
                        "DELETE FROM saved_messages WHERE conversation_id=? AND user_id=? AND message_id=?",
                        (conversation_id, user["id"], row["message_id"]),
                    )
            conn.commit()
            return {"ok": True, "revision": existing["revision"] + 1 if existing else 1}
        finally:
            conn.close()

    @router.delete("/conversations")
    def clear_conversations(user: Dict[str, Any] = Depends(authenticated_user)):
        user_id = user["id"]
        conn = _get_db()
        try:
            with conn:
                _begin_write(conn)
                conn.execute(
                    """INSERT INTO conversation_deletions (user_id, id)
                       SELECT user_id, id FROM conversations WHERE user_id=?
                       ON CONFLICT(user_id, id) DO NOTHING""",
                    (user_id,),
                )
                deleted = conn.execute(
                    "DELETE FROM conversations WHERE user_id=?", (user_id,)
                ).rowcount
                conn.execute("DELETE FROM saved_messages WHERE user_id=?", (user_id,))
                conn.execute("DELETE FROM chat_shares WHERE user_id=?", (user_id,))
            return {"deleted": deleted}
        finally:
            conn.close()

    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(
        conversation_id: str,
        user_id: str,
        user: Dict[str, Any] = Depends(authenticated_user),
    ):
        if user_id != user["id"]:
            raise HTTPException(
                status_code=403, detail="Cannot delete another user's conversations"
            )
        conn = _get_db()
        try:
            _begin_write(conn)
            cur = conn.execute(
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Conversation not found")
            conn.execute(
                """INSERT INTO conversation_deletions (user_id, id) VALUES (?, ?)
                   ON CONFLICT(user_id, id) DO NOTHING""",
                (user_id, conversation_id),
            )
            conn.execute(
                "DELETE FROM saved_messages WHERE user_id=? AND conversation_id=?",
                (user_id, conversation_id),
            )
            conn.execute(
                "DELETE FROM chat_shares WHERE user_id=? AND conversation_id=?",
                (user_id, conversation_id),
            )
            conn.commit()
            return {"deleted": conversation_id}
        finally:
            conn.close()

    return router
