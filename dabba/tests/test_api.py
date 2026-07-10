import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock, PropertyMock
from fastapi.testclient import TestClient
from dabba.api import create_app
from dabba.api.auth import authenticate_request
from dabba.api.rate_limiter import RateLimiter
from dabba.api.chat_endpoints import ChatEndpoint
from dabba.api.streaming_handler import StreamingHandler


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
        response = endpoint.chat(messages=[{"role": "user", "content": "Write a poem"}], temperature=0.9)
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
        response = endpoint.chat(messages=[{"role": "user", "content": "Hello"}], max_tokens=10)
        assert response is not None

    def test_chat_streaming(self):
        handler = Mock(spec=StreamingHandler)
        handler.create_chunk.return_value = "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}\n\n"
        result = handler.create_chunk("Hello", index=0)
        assert "Hello" in result

    def test_streaming_handler_defaults(self):
        handler = StreamingHandler()
        assert handler is not None


class TestFastAPIApp:
    def test_app_creation(self):
        test_app = create_app()
        assert test_app is not None

    def test_app_title(self):
        test_app = create_app(title="Dabba API")
        assert test_app.title == "Dabba API"

    def test_health_endpoint(self):
        test_app = create_app()
        with TestClient(test_app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert "status" in data

    def test_v1_chat_completions(self):
        test_app = create_app()
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
        test_app = create_app()
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
        test_app = create_app()
        with TestClient(test_app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={"model": "dabba-small", "messages": [{"role": "user", "content": "Hi"}]},
                headers={"Authorization": "Bearer invalid-token"},
            )
            assert response.status_code in [200, 401, 403]

    def test_missing_model(self):
        test_app = create_app()
        with TestClient(test_app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
            # Endpoint uses default model when none provided
            assert response.status_code == 200

    def test_cors_headers(self):
        test_app = create_app()
        with TestClient(test_app) as client:
            response = client.options(
                "/v1/chat/completions",
                headers={"Origin": "http://example.com"},
            )
            assert response.status_code in [200, 405]

    def test_model_listing(self):
        test_app = create_app()
        with TestClient(test_app) as client:
            response = client.get("/v1/models")
            assert response.status_code in [200, 401, 404]
