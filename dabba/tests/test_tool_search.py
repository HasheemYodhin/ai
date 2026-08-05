import asyncio

from dabba.agent.agent_loop import AgentLoop
from dabba.agent.tool_registry import ToolRegistry
from dabba.agent.tool_schema import ToolCall, ToolDefinition, ToolParameter
from dabba.config.agent_config import AgentConfig


def _make_registry():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="deploy_to_kubernetes",
            description="Deploy a container image to a Kubernetes cluster",
            parameters=[ToolParameter(name="image", type="string")],
            handler=lambda image: f"deployed {image}",
        )
    )
    registry.register(
        ToolDefinition(
            name="send_slack_message",
            description="Post a message to a Slack channel",
            parameters=[ToolParameter(name="text", type="string")],
            handler=lambda text: f"sent {text}",
        )
    )
    return registry


def test_search_tools_ranks_by_relevance():
    registry = _make_registry()
    matches = registry.search_tools("kubernetes deploy")
    assert matches[0]["name"] == "deploy_to_kubernetes"

    assert registry.search_tools("slack")[0]["name"] == "send_slack_message"
    assert registry.search_tools("nonexistent capability xyz") == []


def test_default_config_advertises_every_tool_immediately():
    loop = AgentLoop(
        registry=_make_registry(), config=AgentConfig(), llm_generate=lambda m, p: "n/a"
    )
    names = {t["name"] for t in loop._tool_dicts()}
    assert names == {"deploy_to_kubernetes", "send_slack_message"}


def test_tool_search_mode_hides_tools_until_activated():
    config = AgentConfig(use_tool_search=True)
    loop = AgentLoop(
        registry=_make_registry(), config=config, llm_generate=lambda m, p: "n/a"
    )

    initial = {t["name"] for t in loop._tool_dicts()}
    assert initial == {"tool_search"}

    results = asyncio.run(
        loop._execute_tool_calls(
            [
                ToolCall(
                    tool_name="tool_search",
                    arguments={"query": "kubernetes"},
                    call_id="c1",
                )
            ]
        )
    )
    assert results[0].success is True
    assert "deploy_to_kubernetes" in results[0].output

    after_search = {t["name"] for t in loop._tool_dicts()}
    assert after_search == {"tool_search", "deploy_to_kubernetes"}
    assert "send_slack_message" not in after_search


def test_tool_search_respects_allowed_tools_scope():
    config = AgentConfig(
        use_tool_search=True, allowed_tools=["tool_search", "send_slack_message"]
    )
    loop = AgentLoop(
        registry=_make_registry(), config=config, llm_generate=lambda m, p: "n/a"
    )

    results = asyncio.run(
        loop._execute_tool_calls(
            [
                ToolCall(
                    tool_name="tool_search",
                    arguments={"query": "kubernetes deploy slack"},
                    call_id="c1",
                )
            ]
        )
    )
    # deploy_to_kubernetes matches the query but is outside the allowlist, so
    # search must not surface or activate it.
    assert "deploy_to_kubernetes" not in results[0].output
    assert "send_slack_message" in results[0].output
    assert "deploy_to_kubernetes" not in loop._activated_tools
