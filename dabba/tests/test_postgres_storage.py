"""PostgreSQL integration test. Use DABBA_TEST_POSTGRES_URL with a test database."""

import json
import os
from contextlib import closing
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dabba.api import create_app
from dabba.api import conversations_endpoints
from dabba.platform import core
from dabba.platform.migrate_sqlite import migrate
from dabba.platform.postgres import PostgresConnection, close_postgres_pool
from dabba.platform.services import IdentityService, TaskOrchestrator


@pytest.fixture
def postgres_url():
    url = os.environ.get("DABBA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set DABBA_TEST_POSTGRES_URL to run PostgreSQL integration tests")
    import psycopg

    schema = f"dabba_test_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
        try:
            yield psycopg.conninfo.make_conninfo(
                url, options=f"-c search_path={schema}"
            )
        finally:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


def test_postgres_pool_reuses_connections_and_releases_transactions(postgres_url):
    try:
        with closing(PostgresConnection(postgres_url, pooled=True)) as first:
            pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            with first:
                first.begin_write()
                first.execute("CREATE TABLE pool_transaction (id INT)")
        with closing(PostgresConnection(postgres_url, pooled=True)) as reused:
            assert (
                reused.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
                == pid
            )
            assert (
                reused.execute(
                    "SELECT COUNT(*) AS total FROM pool_transaction"
                ).fetchone()["total"]
                == 0
            )
            with pytest.raises(RuntimeError), reused:
                reused.begin_write()
                reused.execute("INSERT INTO pool_transaction VALUES (1)")
                raise RuntimeError("force rollback")
        with closing(PostgresConnection(postgres_url, pooled=True)) as reused:
            assert (
                reused.execute(
                    "SELECT COUNT(*) AS total FROM pool_transaction"
                ).fetchone()["total"]
                == 0
            )
    finally:
        close_postgres_pool()


def test_sqlite_import_and_postgres_api(tmp_path, monkeypatch, postgres_url):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    platform_path = tmp_path / "platform.db"
    conversations_path = tmp_path / "conversations.db"
    monkeypatch.setattr(conversations_endpoints, "DB_PATH", conversations_path)
    original = core.PlatformStore(platform_path)
    identity = IdentityService(original)
    user = identity.signup("Existing", "existing@example.test", "fixture-password")
    session = identity.login(user["email"], "fixture-password")
    headers = {"Authorization": f"Bearer {session['token']}"}
    tasks = TaskOrchestrator(original)
    task = tasks.create("chat", {}, user_id=user["id"], model="test")
    tasks.transition(task["id"], "running")
    tasks.transition(
        task["id"],
        "completed",
        result={"usage": {"prompt_tokens": 5, "completion_tokens": 7}},
        record_model_usage=True,
    )
    messages = [{"id": "m1", "role": "user", "content": "Find this", "timestamp": 1}]
    with closing(conversations_endpoints._get_db()) as conn, conn:
        conn.execute(
            """INSERT INTO conversations (id, user_id, title, messages, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("original", user["id"], "Imported chat", json.dumps(messages), 1, 2),
        )
        conn.execute(
            "INSERT INTO conversation_deletions (user_id, id) VALUES (?, ?)",
            (user["id"], "deleted"),
        )

    counts = migrate(platform_path, conversations_path, postgres_url)
    assert counts["users"] == counts["sessions"] == counts["conversations"] == 1
    with pytest.raises(ValueError, match="destination contains Dabba data"):
        migrate(platform_path, conversations_path, postgres_url)
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core, "_default_store", None)

    with TestClient(create_app(model_engine=Mock())) as client:
        assert client.get("/ready").is_success
        assert client.get("/v1/platform/identity/me", headers=headers).json() == user
        response = client.patch(
            "/v1/platform/identity/me",
            headers=headers,
            json={"name": "Updated", "bio": "Test"},
        )
        assert response.is_success and response.json()["name"] == "Updated"
        response = client.get("/v1/platform/usage", headers=headers)
        assert response.is_success and response.json()["totalTokens"] == 12
        assert (
            response.json()["conversationCount"] == response.json()["messageCount"] == 1
        )
        assert client.get(
            "/v1/guest/status?guestId=postgres-test", headers=headers
        ).is_success
        response = client.get(
            "/v1/conversations",
            headers=headers,
            params={"user_id": user["id"], "include_messages": False},
        )
        assert response.json()["conversations"][0]["messageCount"] == 1
        response = client.get("/v1/conversations/search?q=find", headers=headers)
        assert response.json()["matches"] == [
            {"id": "original", "snippet": "Find this", "messageId": "m1"}
        ]

        assert (
            client.put(
                "/v1/conversations/original/saved/m1", headers=headers
            ).status_code
            == 204
        )
        assert (
            client.get("/v1/conversations/saved", headers=headers).json()["items"][0][
                "message_id"
            ]
            == "m1"
        )
        share = client.post(
            "/v1/conversations/original/shares",
            headers=headers,
            json={"messageIds": ["m1"], "revision": 1},
        )
        assert share.status_code == 201
        shared_path = f"/v1/conversations/public/shares/{share.json()['id']}"
        assert client.get(shared_path).json()["messages"] == [
            {"role": "user", "content": "Find this"}
        ]
        payload = {
            **client.get("/v1/conversations/original", headers=headers).json(),
            "userId": user["id"],
            "title": "Updated chat",
        }
        assert (
            client.put(
                "/v1/conversations/original", headers=headers, json=payload
            ).json()["revision"]
            == 2
        )
        assert (
            client.put(
                "/v1/conversations/original", headers=headers, json=payload
            ).status_code
            == 409
        )
        assert client.delete("/v1/conversations", headers=headers).json() == {
            "deleted": 1
        }
        assert client.get(shared_path).status_code == 404
        assert (
            client.put(
                "/v1/conversations/deleted",
                headers=headers,
                json={**payload, "id": "deleted"},
            ).status_code
            == 409
        )
        assert client.get(
            "/v1/conversations/search?q=find", headers=headers
        ).json() == {"matches": []}

    new_tasks = TaskOrchestrator(core.get_platform_store())
    new_task = new_tasks.create("test", {}, user_id=user["id"])
    assert new_tasks.events(new_task["id"])[0]["id"] > counts["task_events"]
