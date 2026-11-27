import asyncio
import json
from threading import Event
from types import SimpleNamespace

import httpx
import openai
import pytest

from dabba.agent.mcp_handler import McpHandler
from dabba.api import agent_endpoints
from dabba.platform import core
from dabba.providers.base import ReasoningDelta
from dabba.providers.registry import ProviderRegistry


@pytest.fixture(
    params=[
        (
            "vyceai/glm-5.3-flash",
            "glm-5.3-flash",
            "https://vyceai.com/v1",
            "VYCEAI_API_KEY",
        ),
        (
            "gemini-4-hydrogen",
            "gemini-4-hydrogen",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "GEMINI_API_KEY",
        ),
    ]
)
def hosted(request, monkeypatch, tmp_path):
    model, upstream_model, base_url, env = request.param
    monkeypatch.setenv(env, "test-key")
    monkeypatch.setattr(
        core,
        "_default_store",
        core.PlatformStore(tmp_path / "platform.db", postgres_url=""),
    )
    registry = ProviderRegistry(
        SimpleNamespace(
            api_endpoint="http://localhost:8080", api_keys={}, default_model=model
        ),
    )
    requests = []
    real_client = openai.OpenAI

    def handle(request):
        assert str(request.url) == f"{base_url}/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        requests.append(body)
        expected = upstream_model
        if model.startswith("gemini") and body["messages"] == [
            {"role": "user", "content": "Reply OK."}
        ]:
            expected = "gemini-3.5-flash-lite"
        assert body["model"] == expected
        common = {"id": "response", "created": 1, "model": body["model"]}
        usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        if not body.get("stream"):
            return httpx.Response(
                200,
                json={
                    **common,
                    "object": "chat.completion",
                    "usage": usage,
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "OK"},
                        }
                    ],
                },
            )
        deltas = [
            {"reasoning_content": "Working"},
            {"content": "Checking"},
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": '},
                    }
                ]
            },
            {"tool_calls": [{"index": 0, "function": {"arguments": '"Paris"}'}}]},
        ]
        if not body.get("tools"):
            deltas = deltas[:2]
        frames = [
            {
                **common,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": delta}],
            }
            for delta in deltas
        ]
        frames.append(
            {**common, "object": "chat.completion.chunk", "choices": [], "usage": usage}
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames)
            + "data: [DONE]\n\n",
        )

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: real_client(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        ),
    )
    return registry, model, requests


def test_hosted_provider_catalog_and_chat(hosted, monkeypatch):
    registry, model, requests = hosted
    proxy = SimpleNamespace(
        _get_provider_registry=lambda: registry, cli_config=registry.config
    )
    monkeypatch.setattr(agent_endpoints, "_get_agent_proxy", lambda: proxy)
    routes = {
        route.endpoint.__name__: route.endpoint
        for route in agent_endpoints.create_agent_router().routes
    }
    catalog = asyncio.run(routes["agent_models"]())["models"]
    entry = next(item for item in catalog if item["id"] == model)
    assert entry["has_key"] and entry["provider"] == registry.provider_name(model)
    assert not {"gemini-2.0-flash", "gemini-2.5-pro"} & {item["id"] for item in catalog}
    assert registry.provider_name("gemini-2.5-pro") == "google"

    usage = {}
    assert (
        registry.chat([{"role": "user", "content": "Hello"}], model, usage_out=usage)
        == "OK"
    )
    assert usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert requests[0].get("reasoning_effort") == (
        "medium" if model.startswith("gemini") else None
    )

    registry.config.api_keys = {entry["provider"]: "test-key"}
    verified = asyncio.run(
        routes["test_api_key"](
            agent_endpoints.VerifyApiKeyRequest(provider=entry["provider"])
        )
    )
    assert verified["model"].startswith(("gemini-", "vyceai/"))


def test_hosted_provider_streaming_tool_call(hosted):
    registry, model, requests = hosted
    usage = {}
    output = list(
        registry.stream_chat(
            [
                {"role": "system", "content": "Instructions"},
                {"role": "user", "content": "Weather?"},
            ],
            model,
            tools=[{"name": "get_weather"}],
            include_reasoning=True,
            usage_out=usage,
        )
    )
    assert isinstance(output[0], ReasoningDelta)
    assert output[1] == "Checking"
    assert '"arguments": {"city": "Paris"}' in output[2]
    assert McpHandler().parse_tool_calls(output[2])[0].tool_name == "get_weather"
    assert requests[0]["messages"][0]["role"] == "system"
    assert (
        requests[0]["stream"]
        and requests[0]["tools"][0]["function"]["name"] == "get_weather"
    )
    assert usage["total_tokens"] == 5

    cancel = Event()
    cancel.set()
    assert list(registry.stream_chat([], model, cancel_event=cancel)) == []
    assert len(requests) == 1
