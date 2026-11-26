"""Conversation list/detail endpoints: lightweight list, ownership, compat."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import dabba.api.conversations_endpoints as conversations_endpoints
import dabba.platform.core as platform_core
from dabba.api import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate both SQLite stores from the developer's real Dabba data.
    monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(platform_core, "_default_store", None)
    monkeypatch.setattr(
        conversations_endpoints, "DB_PATH", tmp_path / "conversations.db"
    )
    with TestClient(create_app(model_engine=Mock())) as test_client:
        yield test_client


def _signup(client, email):
    response = client.post(
        "/v1/platform/identity/signup",
        json={"name": "Tester", "email": email, "password": "a-secure-password"},
    )
    assert response.status_code == 201
    body = response.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['token']}"}


def _save(client, headers, user_id, conv_id, messages):
    response = client.put(
        f"/v1/conversations/{conv_id}",
        headers=headers,
        json={
            "id": conv_id,
            "userId": user_id,
            "title": "Chat",
            "messages": messages,
            "createdAt": 1,
            "updatedAt": 2,
        },
    )
    assert response.status_code == 200


MESSAGES = [
    {"id": "m1", "role": "user", "content": "hi", "timestamp": 1},
    {"id": "m2", "role": "assistant", "content": "hello", "timestamp": 2},
]


def test_summary_list_omits_messages_and_counts_them(client):
    user_id, headers = _signup(client, "summary@example.com")
    _save(client, headers, user_id, "c1", MESSAGES)

    response = client.get(
        f"/v1/conversations?user_id={user_id}&include_messages=false", headers=headers
    )
    assert response.status_code == 200
    [summary] = response.json()["conversations"]
    assert "messages" not in summary
    assert summary["messageCount"] == 2
    assert summary["id"] == "c1"


def test_default_list_keeps_original_shape(client):
    user_id, headers = _signup(client, "compat@example.com")
    _save(client, headers, user_id, "c1", MESSAGES)

    response = client.get(f"/v1/conversations?user_id={user_id}", headers=headers)
    assert response.json()["conversations"][0]["messages"] == MESSAGES


def test_get_one_conversation_only_for_its_owner(client):
    owner_id, owner_headers = _signup(client, "owner@example.com")
    _, other_headers = _signup(client, "other@example.com")
    _save(client, owner_headers, owner_id, "c1", MESSAGES)

    mine = client.get("/v1/conversations/c1", headers=owner_headers)
    assert mine.status_code == 200
    assert mine.json()["messages"] == MESSAGES

    # Another user's chat looks exactly like a missing one.
    assert client.get("/v1/conversations/c1", headers=other_headers).status_code == 404
    assert (
        client.get("/v1/conversations/missing", headers=owner_headers).status_code
        == 404
    )
    assert client.get("/v1/conversations/c1").status_code == 401


def test_security_headers_on_api_responses(client):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    # Plain http in tests: no HSTS, and JSON responses carry no CSP.
    assert "strict-transport-security" not in response.headers
    assert "content-security-policy" not in response.headers


def test_hsts_when_proxy_reports_https(client):
    response = client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")


def test_stale_save_and_deleted_chat_cannot_overwrite_history(client):
    user_id, headers = _signup(client, "revision@example.com")
    _save(client, headers, user_id, "revision-chat", MESSAGES)
    path = "/v1/conversations/revision-chat"
    payload = {
        **client.get(path, headers=headers).json(),
        "userId": user_id,
        "title": "Newer chat",
        "updatedAt": 3,
    }
    assert client.put(path, headers=headers, json=payload).json()["revision"] == 2
    assert client.put(path, headers=headers, json=payload).status_code == 409
    assert client.get(path, headers=headers).json()["title"] == "Newer chat"
    assert (
        client.delete(f"{path}?user_id={user_id}", headers=headers).status_code == 200
    )
    assert client.put(path, headers=headers, json=payload).status_code == 409


def test_search_matches_message_text_only_in_the_callers_account(client):
    owner, owner_headers = _signup(client, "search-owner@example.com")
    _, other_headers = _signup(client, "search-other@example.com")
    _save(client, owner_headers, owner, "search-chat", MESSAGES)
    path = "/v1/conversations/search?q=hello"
    result = client.get(path, headers=owner_headers).json()["matches"]
    assert result == [{"id": "search-chat", "snippet": "hello", "messageId": "m2"}]
    assert client.get(path, headers=other_headers).json()["matches"] == []


def test_clear_conversations_is_account_scoped_and_preserves_deletion_markers(client):
    owner, owner_headers = _signup(client, "clear-owner@example.com")
    other, other_headers = _signup(client, "clear-other@example.com")
    _save(client, owner_headers, owner, "owner-chat", MESSAGES)
    _save(client, other_headers, other, "other-chat", MESSAGES)
    path = "/v1/conversations/owner-chat"
    stale = {**client.get(path, headers=owner_headers).json(), "userId": owner}
    assert client.delete("/v1/conversations", headers=owner_headers).json() == {
        "deleted": 1
    }
    assert client.put(path, headers=owner_headers, json=stale).status_code == 409
    assert (
        client.get("/v1/conversations/other-chat", headers=other_headers).status_code
        == 200
    )
