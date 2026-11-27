import asyncio
import json
from types import SimpleNamespace

import pytest

from dabba.agent.tool_registry import ToolRegistry
from dabba.agent.tool_schema import ToolCall, ToolDefinition
from dabba.api import agent_endpoints
from dabba.cli import config as cli_config
from dabba.config.agent_config import AgentConfig
from dabba.platform import core
from dabba.platform.services import MemoryService, SecretVault


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DABBA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core, "_default_store", None)
    return tmp_path


def test_removed_key_stays_removed_after_loading_config(isolated_data, monkeypatch):
    monkeypatch.setattr(
        cli_config, "CLI_CONFIG_PATH", isolated_data / "cli_config.yaml"
    )
    config = cli_config.CliConfig(
        api_keys={"nvidia": "fixture-key", "openai": "another"}
    )
    config.save()
    assert cli_config.CliConfig.load().remove_provider_key("NVIDIA")
    assert SecretVault().get("cli", "provider:nvidia") is None
    assert cli_config.CliConfig.load().api_keys == {"openai": "another"}


def test_agent_prompt_uses_only_current_account_preferences(isolated_data):
    memory = MemoryService()
    memory.put("preference", "style", "short answers", user_id="one")
    memory.put("preference", "style", "long answers", user_id="two")
    request = agent_endpoints.AgentRequest(
        message="Hello", system_prompt="Use metric units", selection="selected text"
    )
    prompt = agent_endpoints._build_prompt(request, "one")
    assert "short answers" in prompt and "long answers" not in prompt
    assert "Use metric units" in prompt and "selected text" in prompt
    entry = memory.list(user_id="one")[0]
    memory.delete(entry["id"], "one")
    assert "short answers" not in agent_endpoints._build_prompt(request, "one")


def test_agent_overrides_reset_on_the_next_turn():
    loop = SimpleNamespace(config=AgentConfig(), context_manager=SimpleNamespace())
    agent_endpoints._configure_agent_turn(
        loop,
        agent_endpoints.AgentRequest(
            message="first",
            max_steps=7,
            use_tool_search=True,
            context_compaction_threshold=0,
        ),
    )
    assert loop.config.max_steps == 7 and loop.context_manager.compaction_threshold == 0
    agent_endpoints._configure_agent_turn(
        loop, agent_endpoints.AgentRequest(message="next")
    )
    assert loop.config.max_steps == 50 and not loop.config.use_tool_search
    assert loop.context_manager.compaction_threshold == 0.75


@pytest.mark.parametrize(
    "mode, approved, expected",
    [
        ("deny", False, False),
        ("allow", False, True),
        ("ask", False, False),
        ("ask", True, True),
    ],
)
def test_agent_permission_modes_gate_mock_tool(monkeypatch, mode, approved, expected):
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="file_write",
            description="test fixture",
            handler=lambda: calls.append("called"),
        )
    )

    async def stream(_prompt):
        yield {
            "type": "tool_call",
            "content": {"name": "file_write", "call_id": "fixture"},
        }
        result = await registry._execute_async(
            ToolCall(tool_name="file_write", call_id="fixture", arguments={})
        )
        yield {"type": "tool_result", "content": result.to_dict()}

    loop = SimpleNamespace(
        config=AgentConfig(), context_manager=SimpleNamespace(), stream_chat=stream
    )
    proxy = SimpleNamespace(
        agent_config=loop.config,
        cli_config=SimpleNamespace(api_keys={}),
        _ensure_agent_loop=lambda *_a, **_kw: loop,
    )
    monkeypatch.setattr(agent_endpoints, "_get_agent_proxy", lambda *_: proxy)
    monkeypatch.setattr(agent_endpoints, "_account_preferences", lambda _: [])

    async def check():
        async def is_disconnected():
            return False

        router = agent_endpoints.create_agent_router()
        endpoint = next(
            route.endpoint for route in router.routes if route.path == "/v1/agent"
        )
        approve = next(
            route.endpoint
            for route in router.routes
            if route.path == "/v1/agent/approve"
        )
        request = SimpleNamespace(
            state=SimpleNamespace(dabba_user={"id": "owner"}),
            is_disconnected=is_disconnected,
        )
        response = await endpoint(
            agent_endpoints.AgentRequest(
                message="check", conversation_id="fixture", permission_mode=mode
            ),
            request,
        )
        async for line in response.body_iterator:
            event = json.loads(line.removeprefix("data: "))
            if event["type"] == "approval_required":
                await approve(
                    agent_endpoints.ApprovalRequest(
                        call_id="fixture", approved=approved
                    ),
                    request,
                )

    asyncio.run(check())
    assert bool(calls) is expected


def test_mcp_status_keeps_discovery_separate_from_account_authentication(monkeypatch):
    from dabba.agent import mcp_client

    config = SimpleNamespace(command="fixture", args=[], env={})
    monkeypatch.setattr(mcp_client, "load_mcp_config", lambda: {"fixture": config})
    manager = SimpleNamespace(
        status=lambda: {
            "servers": ["fixture"],
            "tools_by_server": {"fixture": ["list_items"]},
        }
    )
    proxy = SimpleNamespace(mcp_manager=manager, _get_registry=lambda: None)
    monkeypatch.setattr(agent_endpoints, "_get_agent_proxy", lambda: proxy)
    endpoint = next(
        route.endpoint
        for route in agent_endpoints.create_agent_router().routes
        if route.path == "/v1/mcp/status"
    )
    server = asyncio.run(endpoint())["servers"][0]
    assert server["connected"] and server["processRunning"]
    assert server["tools"] == ["list_items"]
    assert not server["authenticated"]
    assert server["authenticationStatus"] == "unverified"
