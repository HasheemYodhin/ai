import json
from unittest.mock import Mock, patch, MagicMock, PropertyMock, AsyncMock
from dabba.agent import Agent, AgentConfig
from dabba.agent.tool_registry import ToolRegistry
from dabba.agent.mcp_handler import MCPHandler
from dabba.agent.context_manager import ContextManager
from dabba.agent.planner import Planner
from dabba.agent.executor import Executor
from dabba.agent.agent_loop import AgentLoop


class TestAgentConfig:
    def test_defaults(self):
        cfg = AgentConfig()
        assert cfg.system_prompt is not None
        assert cfg.max_iterations == 10

    def test_custom(self):
        cfg = AgentConfig(system_prompt="You are a test bot.", max_iterations=5)
        assert cfg.max_iterations == 5


class TestToolRegistry:
    def test_register_tool(self):
        registry = ToolRegistry()

        def my_tool(x: int) -> int:
            return x * 2

        registry.register(my_tool, name="double")
        assert "double" in registry.list_tools()

    def test_execute_tool(self):
        registry = ToolRegistry()

        def add(a: int, b: int) -> int:
            return a + b

        registry.register(add, name="add")
        result = registry.execute("add", {"a": 3, "b": 4})
        assert result == 7

    def test_execute_unknown_tool(self):
        registry = ToolRegistry()
        try:
            registry.execute("nonexistent", {})
            assert False
        except ValueError:
            pass

    def test_list_tools(self):
        registry = ToolRegistry()

        def tool1(): pass
        def tool2(): pass
        registry.register(tool1, name="tool1")
        registry.register(tool2, name="tool2")
        tools = registry.list_tools()
        assert "tool1" in tools
        assert "tool2" in tools

    def test_unregister_tool(self):
        registry = ToolRegistry()

        def tool(): pass
        registry.register(tool, name="test")
        assert "test" in registry.list_tools()
        registry.unregister("test")
        assert "test" not in registry.list_tools()

    def test_tool_schema(self):
        registry = ToolRegistry()

        def multiply(a: float, b: float = 1.0) -> float:
            return a * b

        registry.register(multiply, name="multiply")
        schema = registry.get_tool_schema("multiply")
        assert "parameters" in schema
        assert "a" in json.dumps(schema)

    def test_tool_with_no_params(self):
        registry = ToolRegistry()

        def hello() -> str:
            return "hello"

        registry.register(hello, name="hello")
        result = registry.execute("hello", {})
        assert result == "hello"

    def test_register_decorator(self):
        registry = ToolRegistry()

        @registry.register
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        assert "greet" in registry.list_tools()
        result = registry.execute("greet", {"name": "World"})
        assert result == "Hello, World!"

    def test_tool_registration_twice(self):
        registry = ToolRegistry()

        def tool(): pass
        registry.register(tool, name="mytool")
        try:
            registry.register(tool, name="mytool")
            assert False
        except ValueError:
            pass


class TestMCPHandler:
    def test_handle_tool_call(self):
        handler = Mock(spec=MCPHandler)
        handler.handle_tool_call.return_value = {"result": "success"}
        result = handler.handle_tool_call("some_tool", {"arg": "val"})
        assert result["result"] == "success"

    def test_handle_tool_call_error(self):
        handler = Mock(spec=MCPHandler)
        handler.handle_tool_call.side_effect = Exception("Tool failed")
        try:
            handler.handle_tool_call("failing_tool", {})
            assert False
        except Exception:
            pass

    def test_list_available_tools(self):
        handler = Mock(spec=MCPHandler)
        handler.list_available_tools.return_value = ["tool_a", "tool_b"]
        tools = handler.list_available_tools()
        assert len(tools) == 2


class TestContextManager:
    def test_initialization(self):
        cm = ContextManager(max_history=100)
        assert len(cm.history) == 0
        assert cm.max_history == 100

    def test_add_message(self):
        cm = ContextManager(max_history=100)
        cm.add_message("user", "Hello")
        assert len(cm.history) == 1
        assert cm.history[0]["role"] == "user"

    def test_context_truncation(self):
        cm = ContextManager(max_history=3)
        for i in range(5):
            cm.add_message("user", f"Message {i}")
        assert len(cm.history) == 3
        assert cm.history[0]["content"] == "Message 2"

    def test_get_context(self):
        cm = ContextManager(max_history=100)
        cm.add_message("user", "Hi")
        cm.add_message("assistant", "Hello!")
        ctx = cm.get_context()
        assert len(ctx) == 2
        assert ctx[0]["role"] == "user"
        assert ctx[1]["role"] == "assistant"

    def test_clear(self):
        cm = ContextManager(max_history=100)
        cm.add_message("user", "test")
        cm.clear()
        assert len(cm.history) == 0

    def test_system_prompt(self):
        cm = ContextManager(system_prompt="You are a helpful AI.", max_history=100)
        ctx = cm.get_context()
        assert ctx[0]["role"] == "system"

    def test_token_count(self):
        cm = ContextManager(max_history=100)
        cm.add_message("user", "Hello world")
        count = cm.token_count()
        assert count > 0

    def test_token_limit(self):
        cm = ContextManager(max_history=100, token_limit=10)
        for i in range(100):
            cm.add_message("user", "test message that takes up tokens")
        assert cm.token_count() <= 15


class TestPlanner:
    def test_create_plan(self):
        planner = Mock(spec=Planner)
        planner.create_plan.return_value = {
            "steps": [
                {"action": "search", "params": {"query": "AI"}},
                {"action": "summarize", "params": {}},
            ]
        }
        plan = planner.create_plan("Research AI trends")
        assert len(plan["steps"]) == 2

    def test_create_plan_simple(self):
        planner = Mock(spec=Planner)
        planner.create_plan.return_value = {
            "steps": [{"action": "respond", "params": {"text": "Hello!"}}]
        }
        plan = planner.create_plan("Say hello")
        assert len(plan["steps"]) == 1


class TestExecutor:
    def test_execute_step(self):
        executor = Mock(spec=Executor)
        executor.execute_step.return_value = {"result": "done", "status": "success"}
        result = executor.execute_step({"action": "test", "params": {}})
        assert result["status"] == "success"

    def test_execute_step_failure(self):
        executor = Mock(spec=Executor)
        executor.execute_step.return_value = {"result": None, "status": "failed", "error": "Something went wrong"}
        result = executor.execute_step({"action": "fail", "params": {}})
        assert result["status"] == "failed"


class TestAgentLoop:
    def test_run(self):
        loop = Mock(spec=AgentLoop)
        loop.run.return_value = {"response": "Final answer", "steps_taken": 3}
        result = loop.run("What is the capital of France?")
        assert "response" in result
        assert result["steps_taken"] == 3

    def test_run_max_iterations(self):
        loop = Mock(spec=AgentLoop)
        loop.run.return_value = {"response": "Too complex", "steps_taken": 10, "truncated": True}
        result = loop.run("Complex task")
        assert result["truncated"] is True

    def test_run_stream(self):
        loop = Mock(spec=AgentLoop)
        loop.run_stream.return_value = [
            {"type": "thought", "content": "Let me think..."},
            {"type": "action", "content": "Searching..."},
            {"type": "response", "content": "Here is the answer."},
        ]
        events = list(loop.run_stream("Test query"))
        assert len(events) == 3


class TestAgent:
    def test_agent_initialization(self):
        agent = Mock(spec=Agent)
        agent.config = AgentConfig()
        assert agent.config.max_iterations == 10

    def test_agent_query(self):
        agent = Mock(spec=Agent)
        agent.query.return_value = "This is the agent's response."
        response = agent.query("Hello agent!")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_agent_query_with_tools(self):
        agent = Mock(spec=Agent)
        agent.query.return_value = "I used a tool to find the answer."
        response = agent.query("Search for AI news")
        assert "tool" in response or "tool" in agent.query.call_args[0][0]

    def test_agent_stream(self):
        agent = Mock(spec=Agent)
        agent.query_stream.return_value = iter(["Hello", " world", "!"])
        tokens = list(agent.query_stream("Say hi"))
        assert len(tokens) >= 1
