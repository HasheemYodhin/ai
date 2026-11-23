"""Guest chat: free prompts for signed-out visitors, enforced on the server."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dabba.api.guest_endpoints import GUEST_MODEL, GuestUsage, create_guest_router
from dabba.platform.core import PlatformStore

GUEST = "guest_abcdefgh1234"


class FakeRegistry:
    def __init__(self, key="nv-key", fail=False):
        self.key, self.fail, self.calls = key, fail, []

    def resolve_api_key(self, model):
        return (self.key, "NVIDIA_API_KEY") if self.key else ("", None)

    def chat(self, messages, model=None, **kwargs):
        self.calls.append((model, messages))
        if self.fail:
            raise RuntimeError("provider down")
        return "Hello from Auto"


@pytest.fixture()
def usage(tmp_path):
    return GuestUsage(PlatformStore(tmp_path / "platform.db"))


def make_client(usage, registry):
    app = FastAPI()
    app.include_router(create_guest_router(usage, registry_factory=lambda: registry))
    return TestClient(app)


def send(client, text="hi", guest=GUEST):
    return client.post("/v1/guest/chat", json={"guestId": guest, "messages": [{"role": "user", "content": text}]})


def event(response):
    line = next(row for row in response.text.splitlines() if row.startswith("data: "))
    return json.loads(line[len("data: "):])


def test_five_free_prompts_then_limit(usage):
    registry = FakeRegistry()
    client = make_client(usage, registry)
    for expected_left in (4, 3, 2, 1, 0):
        response = send(client)
        assert response.status_code == 200
        assert event(response) == {"content": "Hello from Auto", "remaining": expected_left}
    sixth = send(client)
    assert sixth.status_code == 429
    assert sixth.json()["code"] == "guest_limit_reached"
    # Always the fixed model, with no tools passed.
    assert {model for model, _ in registry.calls} == {GUEST_MODEL}


def test_new_guest_id_from_same_ip_is_capped_daily(usage, monkeypatch):
    monkeypatch.setenv("DABBA_GUEST_IP_DAILY_LIMIT", "7")
    client = make_client(usage, FakeRegistry())
    for _ in range(5):
        assert send(client, guest="guest_first0001").status_code == 200
    # Clearing storage gives a new guest id, but the IP allowance still applies.
    assert send(client, guest="guest_second001").status_code == 200
    assert send(client, guest="guest_second001").status_code == 200
    assert send(client, guest="guest_second001").status_code == 429


def test_failed_reply_does_not_use_a_prompt(usage):
    client = make_client(usage, FakeRegistry(fail=True))
    payload = event(send(client))
    assert "error" in payload
    assert payload["remaining"] == 5
    status = client.get("/v1/guest/status", params={"guestId": GUEST}).json()
    assert status["remaining"] == 5


def test_unavailable_without_server_key(usage):
    client = make_client(usage, FakeRegistry(key=""))
    assert send(client).status_code == 503
    assert client.get("/v1/guest/status", params={"guestId": GUEST}).json()["available"] is False


def test_rejects_bad_input(usage):
    client = make_client(usage, FakeRegistry())
    assert send(client, guest="bad id!").status_code == 422
    bad_role = client.post("/v1/guest/chat", json={"guestId": GUEST, "messages": [{"role": "system", "content": "x"}]})
    assert bad_role.status_code == 422
    last_assistant = client.post("/v1/guest/chat", json={"guestId": GUEST, "messages": [{"role": "assistant", "content": "x"}]})
    assert last_assistant.status_code == 422


def test_can_be_turned_off(usage, monkeypatch):
    monkeypatch.setenv("DABBA_GUEST_CHAT", "0")
    assert send(make_client(usage, FakeRegistry())).status_code == 404
