import asyncio
from unittest.mock import Mock

import httpx
from fastapi.testclient import TestClient
from dabba.api import create_app
from dabba.api.auth import authenticate_request
from dabba.api.rate_limiter import RateLimiter
from dabba.api.chat_endpoints import ChatEndpoint, _generate_response
from dabba.api.streaming_handler import StreamingHandler


def test_session_restore_accepts_expired_session_without_exposing_account_data(
    tmp_path, monkeypatch
):
    import dabba.platform.core as platform_core
    from dabba.platform.services import IdentityService

    monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(platform_core, "_default_store", None)
    app = create_app(model_engine=Mock())
    path = "/v1/platform/identity/me"
    restore_path = f"{path}?restore=true"

    identity = IdentityService()
    identity.signup("Session Tester", "session@example.com", "a-secure-password")
    session = identity.login("session@example.com", "a-secure-password")
    headers = {"Authorization": f"Bearer {session['token']}"}

    async def check():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            active = await client.get(restore_path, headers=headers)
            assert active.status_code == 200
            assert active.json() == session["user"]
            assert active.headers["Cache-Control"] == "no-store"

            with platform_core.get_platform_store().transaction() as conn:
                conn.execute("UPDATE sessions SET expires_at = 0")
            expired = await client.get(restore_path, headers=headers)
            assert expired.status_code == 200
            assert expired.json() is None
            assert expired.headers["Cache-Control"] == "no-store"
            assert (await client.get(path, headers=headers)).status_code == 401
            protected = await client.get(
                "/v1/platform/usage?restore=true", headers=headers
            )
            assert protected.status_code == 401

    asyncio.run(check())


class TestAuth:
    def test_authenticate_valid_token(self):
        auth = Mock(spec=authenticate_request)
        auth.return_value = True
        result = auth("valid_token")
        assert result is True

    def test_authenticate_invalid_token(self):
        auth = Mock(spec=authenticate_request)
        auth.return_value = False
        result = auth("invalid_token")
        assert result is False

    def test_authenticate_missing_token(self):
        auth = Mock(spec=authenticate_request)
        auth.return_value = False
        result = auth(None)
        assert result is False

    def test_authenticate_with_api_key(self):
        auth = Mock(spec=authenticate_request)
        auth.return_value = True
        result = auth(api_key="sk-abc123")
        assert result is True

    def test_auth_header_validation(self):
        auth = Mock(spec=authenticate_request)
        auth.side_effect = lambda token: token == "valid-token"
        assert auth("valid-token") is True
        assert auth("bad-token") is False


def test_local_greeting_responds_without_slow_model_engine():
    assert (
        _generate_response(
            [{"role": "user", "content": "Hi"}],
            model_engine=Mock(),
            model_name="dabba",
        )
        == "Hi! How can I help you today?"
    )


class TestRateLimiter:
    def test_allow_request_under_limit(self):
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        for _ in range(5):
            assert limiter.allow_request("user1") is True

    def test_block_request_over_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.allow_request("user2")
        assert limiter.allow_request("user2") is False

    def test_different_users_independent(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert limiter.allow_request("user_a") is True
        assert limiter.allow_request("user_a") is True
        assert limiter.allow_request("user_a") is False
        assert limiter.allow_request("user_b") is True

    def test_window_expires(self):
        limiter = RateLimiter(max_requests=1, window_seconds=0)
        # window_seconds=0 is treated as a zero-length window
        assert limiter.allow_request("user") is True
        assert limiter.allow_request("user") is False
        limiter.reset("user")
        assert limiter.allow_request("user") is True

    def test_get_remaining(self):
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        limiter.allow_request("user")
        remaining = limiter.get_remaining("user")
        assert remaining == 9

    def test_reset(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            limiter.allow_request("user")
        limiter.reset("user")
        assert limiter.get_remaining("user") == 5


class TestChatEndpoint:
    def test_chat_completion_simple(self):
        endpoint = Mock(spec=ChatEndpoint)
        endpoint.chat.return_value = {
            "id": "chat-123",
            "choices": [{"message": {"content": "Hello!", "role": "assistant"}}],
        }
        response = endpoint.chat(messages=[{"role": "user", "content": "Hi"}])
        assert response["choices"][0]["message"]["content"] == "Hello!"

    def test_chat_with_system_prompt(self):
        endpoint = Mock(spec=ChatEndpoint)
        endpoint.chat.return_value = {
            "choices": [{"message": {"content": "You are helpful. I will assist you."}}]
        }
        response = endpoint.chat(
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Help me"},
            ]
        )
        assert response["choices"][0]["message"]["content"]

    def test_chat_with_temperature(self):
        endpoint = Mock(spec=ChatEndpoint)
        endpoint.chat.return_value = {
            "choices": [{"message": {"content": "Creative response"}}]
        }
        response = endpoint.chat(
            messages=[{"role": "user", "content": "Write a poem"}], temperature=0.9
        )
        assert response is not None

    def test_chat_empty_messages(self):
        endpoint = Mock(spec=ChatEndpoint)
        endpoint.chat.side_effect = ValueError("Messages cannot be empty")
        try:
            endpoint.chat(messages=[])
            assert False
        except ValueError:
            pass

    def test_chat_max_tokens(self):
        endpoint = Mock(spec=ChatEndpoint)
        endpoint.chat.return_value = {
            "choices": [{"message": {"content": "Short reply"}}]
        }
        response = endpoint.chat(
            messages=[{"role": "user", "content": "Hello"}], max_tokens=10
        )
        assert response is not None

    def test_chat_streaming(self):
        handler = Mock(spec=StreamingHandler)
        handler.create_chunk.return_value = (
            'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
        )
        result = handler.create_chunk("Hello", index=0)
        assert "Hello" in result

    def test_streaming_handler_defaults(self):
        handler = StreamingHandler()
        assert handler is not None


class TestFastAPIApp:
    def test_app_creation(self):
        test_app = create_app(model_engine=Mock())
        assert test_app is not None

    def test_app_title(self):
        test_app = create_app(title="Dabba API", model_engine=Mock())
        assert test_app.title == "Dabba API"

    def test_health_endpoint(self):
        test_app = create_app(model_engine=Mock())
        with TestClient(test_app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert "status" in data

    def test_artifact_publish_serves_publicly_and_enforces_ownership(
        self, tmp_path, monkeypatch
    ):
        import base64
        import dabba.platform.core as platform_core

        # The platform services all share one process-wide PlatformStore
        # singleton backed by a real on-disk DB (get_platform_store()) — point
        # it at a throwaway directory for this test so it neither pollutes
        # the developer's real Dabba install nor collides with data left over
        # from a previous test run (e.g. a duplicate-email signup failure).
        monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(platform_core, "_default_store", None)

        test_app = create_app(model_engine=Mock())
        with TestClient(test_app) as client:
            signup = client.post(
                "/v1/platform/identity/signup",
                json={
                    "name": "Pub Tester",
                    "email": "artifact-pub-test@example.com",
                    "password": "a-secure-password",
                },
            )
            assert signup.status_code == 201
            headers = {"Authorization": f"Bearer {signup.json()['token']}"}

            html = b"<!doctype html><html><body>Hello from a published artifact</body></html>"
            created = client.post(
                "/v1/platform/artifacts",
                headers=headers,
                json={
                    "name": "demo.html",
                    "data": base64.b64encode(html).decode(),
                    "mediaType": "text/html",
                },
            )
            assert created.status_code == 201

            published = client.post(
                f"/v1/platform/artifacts/{created.json()['id']}/publish",
                headers=headers,
                json={"title": "Demo Page"},
            )
            assert published.status_code == 201
            slug = published.json()["slug"]

            # No Authorization header at all — this must still work.
            public = client.get(f"/v1/platform/public/artifacts/{slug}")
            assert public.status_code == 200
            assert public.headers["Content-Security-Policy"] == "sandbox allow-scripts"
            assert b"Hello from a published artifact" in public.content

            other_signup = client.post(
                "/v1/platform/identity/signup",
                json={
                    "name": "Other",
                    "email": "artifact-pub-other@example.com",
                    "password": "a-secure-password",
                },
            )
            other_headers = {"Authorization": f"Bearer {other_signup.json()['token']}"}
            forbidden = client.delete(
                f"/v1/platform/artifacts/publish/{slug}", headers=other_headers
            )
            assert forbidden.status_code == 403

            unpublished = client.delete(
                f"/v1/platform/artifacts/publish/{slug}", headers=headers
            )
            assert unpublished.status_code == 204
            assert (
                client.get(f"/v1/platform/public/artifacts/{slug}").status_code == 404
            )

    def test_protected_routes_require_a_session(self):
        app = create_app(model_engine=Mock())
        public_paths = {
            "/v1/platform/identity/signup",
            "/v1/platform/identity/login",
            "/v1/platform/public/artifacts/{slug}",
            # Free guest prompts: public on purpose, limited inside the
            # endpoint (dabba/tests/test_guest_endpoints.py covers the limits).
            "/v1/guest/chat",
            "/v1/guest/status",
        }
        client = TestClient(app)
        import re

        for route in app.routes:
            if not route.path.startswith("/v1/") or route.path in public_paths:
                continue
            path = re.sub(r"\{[^}]+\}", "test-id", route.path)
            for method in route.methods:
                assert client.request(method, path).status_code == 401, (method, path)

    def test_agent_processes_requires_admin(self, monkeypatch):
        from dabba.platform.services import IdentityService

        def authenticate(self, token):
            return {"id": token, "role": token}

        monkeypatch.setattr(IdentityService, "authenticate", authenticate)
        client = TestClient(create_app(model_engine=Mock()))
        path = "/v1/agent/processes"
        assert (
            client.get(path, headers={"X-Dabba-Session": "member"}).status_code == 403
        )
        response = client.get(path, headers={"X-Dabba-Session": "admin"})
        assert response.status_code == 200
        assert isinstance(response.json()["processes"], list)

    def test_v1_chat_completions(self):
        test_app = create_app(model_engine=Mock())
        with TestClient(test_app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "dabba-small",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 10,
                },
            )
            assert response.status_code in [200, 401, 404]

    def test_v1_completions(self):
        test_app = create_app(model_engine=Mock())
        with TestClient(test_app) as client:
            response = client.post(
                "/v1/completions",
                json={
                    "model": "dabba-small",
                    "prompt": "Hello world",
                    "max_tokens": 10,
                },
            )
            assert response.status_code in [200, 401, 404]

    def test_unauthorized(self):
        test_app = create_app(model_engine=Mock())
        with TestClient(test_app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "dabba-small",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
                headers={"Authorization": "Bearer invalid-token"},
            )
            assert response.status_code in [200, 401, 403]

    def test_missing_model(self, monkeypatch):
        from dabba.platform.services import IdentityService

        monkeypatch.setattr(
            IdentityService,
            "authenticate",
            lambda self, token: {
                "id": "test-user",
                "role": "member",
            },
        )
        monkeypatch.setattr(
            "dabba.api.chat_endpoints._create_chat_task", lambda *_: None
        )
        client = TestClient(create_app(model_engine=Mock()))
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
            headers={"X-Dabba-Session": "test-token"},
        )
        assert response.status_code == 200
        assert response.json()["model"] == "dabba"

    def test_cors_headers(self):
        client = TestClient(create_app(model_engine=Mock()))
        for origin, status in (
            ("https://example.test", 400),
            ("http://localhost:5173", 200),
        ):
            response = client.options(
                "/v1/chat/completions",
                headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
            )
            assert response.status_code == status
            assert response.headers.get("access-control-allow-origin") == (
                origin if status == 200 else None
            )

    def test_model_listing(self):
        test_app = create_app(model_engine=Mock())
        with TestClient(test_app) as client:
            response = client.get("/v1/models")
            assert response.status_code in [200, 401, 404]


def test_authenticated_stream_reports_usage_and_done(monkeypatch, tmp_path):
    from dabba.platform import core
    from dabba.platform.services import IdentityService
    from dabba.providers.base import ReasoningDelta

    monkeypatch.setattr(core, "_default_store", None)
    monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path))
    identity = IdentityService()
    email = "stream-test@example.test"
    user = identity.signup("Stream test", email, "temporary-test-password")
    session = identity.login(email, "temporary-test-password")

    async def provider_stream(request, messages, engine, usage):
        yield None
        yield ReasoningDelta("Separate thought")
        yield "Streaming reply"
        usage.update(prompt_tokens=10, completion_tokens=3, total_tokens=13)

    monkeypatch.setattr(
        "dabba.api.chat_endpoints._stream_provider_response", provider_stream
    )
    client = TestClient(create_app(model_engine=Mock()))
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {session['token']}"},
        json={
            "model": "mock-provider",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert ": keepalive\n\n" in response.text
    assert "Streaming reply" in response.text
    assert '"reasoning_content": "Separate thought"' in response.text
    assert response.text.endswith("data: [DONE]\n\n")
    usage = identity.store.fetchone(
        "SELECT prompt_tokens, completion_tokens FROM model_usage WHERE user_id=?",
        (user["id"],),
    )
    assert usage == {"prompt_tokens": 10, "completion_tokens": 3}
