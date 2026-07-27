import asyncio

from dabba.agent.agent_loop import AgentLoop
from dabba.agent.tool_registry import ToolRegistry
from dabba.agent.tool_schema import ToolCall, ToolDefinition, ToolParameter
from dabba.config.agent_config import AgentConfig


def _make_registry():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="write_thing", description="Write a file",
        parameters=[ToolParameter(name="path", type="string")],
        handler=lambda path: f"wrote {path}",
    ))
    registry.register(ToolDefinition(
        name="dangerous_thing", description="A tool this subagent should never see",
        parameters=[ToolParameter(name="x", type="string")],
        handler=lambda x: "boom",
    ))
    return registry


def test_unrestricted_config_advertises_every_tool():
    loop = AgentLoop(registry=_make_registry(), config=AgentConfig(), llm_generate=lambda m, p: "n/a")
    names = {t["name"] for t in loop._tool_dicts()}
    assert names == {"write_thing", "dangerous_thing"}


def test_allowed_tools_restricts_advertised_schema():
    config = AgentConfig(allowed_tools=["write_thing"])
    loop = AgentLoop(registry=_make_registry(), config=config, llm_generate=lambda m, p: "n/a")
    names = [t["name"] for t in loop._tool_dicts()]
    assert names == ["write_thing"]


def test_allowed_tools_blocks_disallowed_call_before_execution():
    config = AgentConfig(allowed_tools=["write_thing"])
    loop = AgentLoop(registry=_make_registry(), config=config, llm_generate=lambda m, p: "n/a")

    results = asyncio.run(loop._execute_tool_calls(
        [ToolCall(tool_name="dangerous_thing", arguments={"x": "y"}, call_id="c1")]
    ))
    assert results[0].success is False
    assert "not in this agent's allowed tool list" in results[0].error
