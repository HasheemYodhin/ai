"""
Regression tests for two bugs found in a user-reported Dabba transcript:

1. GPT-4o (and other capable models) would narrate file operations in prose
   instead of ever emitting a real tool call, because dabba only recognized
   tool intent via a prompted "<tool_call>{json}</tool_call>" text
   convention with no native function-calling backing it up.
2. Neither the CLI nor the VS Code extension path ever told the model what
   absolute directory "the X directory" should resolve against, so it had
   to guess from conversation history alone.

See dabba/providers/base.py's native-function-calling-adapter docstring and
dabba/agent/agent_loop.py's _workspace_info()/_tool_dicts() for the fix.
"""
import json
from unittest.mock import MagicMock, patch

from dabba.agent.agent_loop import AgentLoop
from dabba.agent.mcp_handler import McpHandler
from dabba.agent.tool_registry import ToolRegistry
from dabba.config.agent_config import AgentConfig
from dabba.providers.base import remap_tool_role_for_provider
from dabba.providers.openai_provider import OpenAIProvider
from dabba.providers.anthropic_provider import AnthropicProvider


class TestWorkspaceGrounding:
    def test_system_prompt_requires_persistent_verified_engineering_work(self):
        prompt = McpHandler().build_system_prompt("  - tool1: desc", "")
        normalized = " ".join(prompt.split())

        assert "autonomous software-engineering agent inside VS Code" in normalized
        assert "Read before editing" in normalized
        assert "Continue until the user's goal is genuinely handled" in normalized
        assert "run the most relevant type checks, tests, builds" in normalized
        assert "Do not claim success" in normalized

    def test_no_workspace_root_omits_section(self):
        h = McpHandler()
        prompt = h.build_system_prompt("  - tool1: desc", "")
        assert "working directory" not in prompt

    def test_workspace_root_appears_in_system_prompt(self):
        h = McpHandler()
        prompt = h.build_system_prompt(
            "  - tool1: desc",
            "Your current working directory / workspace root is: /repo/train",
        )
        assert "/repo/train" in prompt
        assert "working directory" in prompt

    def test_agent_loop_injects_configured_workspace_root(self):
        captured = {}

        def fake_llm_generate(messages, params):
            captured["messages"] = messages
            captured["tools"] = params.get("tools")
            return "ok, no tool needed"

        config = AgentConfig(workspace_root="/repo/train", use_planning=False)
        loop = AgentLoop(registry=ToolRegistry(), config=config, llm_generate=fake_llm_generate)
        loop.run("create a file in the train directory")

        system_msg = next(m["content"] for m in captured["messages"] if m["role"] == "system")
        assert "/repo/train" in system_msg
        assert captured["tools"] is not None  # tools= was passed to llm_generate

    def test_agent_loop_without_workspace_root_omits_grounding(self):
        captured = {}

        def fake_llm_generate(messages, params):
            captured["messages"] = messages
            return "ok"

        config = AgentConfig(workspace_root=None, use_planning=False)
        loop = AgentLoop(registry=ToolRegistry(), config=config, llm_generate=fake_llm_generate)
        loop.run("hello")

        system_msg = next(m["content"] for m in captured["messages"] if m["role"] == "system")
        assert "working directory" not in system_msg


class TestRoleRemap:
    def test_tool_role_becomes_user_with_marker(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do it"},
            {"role": "assistant", "content": "doing it"},
            {"role": "tool", "content": "result text", "tool_call_id": "abc"},
        ]
        remapped = remap_tool_role_for_provider(messages)
        assert [m["role"] for m in remapped] == ["system", "user", "assistant", "user"]
        assert remapped[-1]["content"] == "[Tool Result]\nresult text"
        assert "tool_call_id" not in remapped[-1]

    def test_non_tool_messages_pass_through_unchanged(self):
        messages = [{"role": "user", "content": "hi"}]
        assert remap_tool_role_for_provider(messages) == messages


class TestOpenAINativeToolCalling:
    def _fake_client_with_tool_call(self):
        fake_tool_call = MagicMock()
        fake_tool_call.id = "call_1"
        fake_tool_call.function.name = "file_write"
        fake_tool_call.function.arguments = json.dumps({"path": "/repo/train/x.yml", "content": "a: b"})

        fake_message = MagicMock(content="Creating it now.", tool_calls=[fake_tool_call])
        fake_resp = MagicMock(choices=[MagicMock(message=fake_message)])
        client = MagicMock()
        client.chat.completions.create.return_value = fake_resp
        return client

    def test_native_tool_call_converted_to_tag_and_parseable(self):
        client = self._fake_client_with_tool_call()
        with patch("openai.OpenAI", return_value=client):
            result = OpenAIProvider().chat(
                messages=[{"role": "user", "content": "make a file"}],
                model="gpt-4o",
                api_key="fake",
                tools=[{"name": "file_write", "description": "writes a file", "parameters": {"type": "object", "properties": {}}}],
            )

        assert "<tool_call>" in result
        parsed = McpHandler().parse_tool_calls(result)
        assert len(parsed) == 1
        assert parsed[0].tool_name == "file_write"
        assert parsed[0].arguments == {"path": "/repo/train/x.yml", "content": "a: b"}
        assert parsed[0].call_id == "call_1"

    def test_tools_and_tool_choice_actually_sent_to_api(self):
        client = self._fake_client_with_tool_call()
        with patch("openai.OpenAI", return_value=client):
            OpenAIProvider().chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-4o",
                api_key="fake",
                tools=[{"name": "file_write", "description": "d", "parameters": {}}],
            )
        _, kwargs = client.chat.completions.create.call_args
        assert kwargs["tool_choice"] == "auto"
        assert kwargs["tools"][0]["function"]["name"] == "file_write"

    def test_no_tools_kwarg_preserves_old_behavior(self):
        fake_message = MagicMock(content="plain text reply", tool_calls=None)
        fake_resp = MagicMock(choices=[MagicMock(message=fake_message)])
        client = MagicMock()
        client.chat.completions.create.return_value = fake_resp
        with patch("openai.OpenAI", return_value=client):
            result = OpenAIProvider().chat(
                messages=[{"role": "user", "content": "hi"}], model="gpt-4o", api_key="fake",
            )
        assert result == "plain text reply"
        _, kwargs = client.chat.completions.create.call_args
        assert "tools" not in kwargs

    def test_tool_role_messages_remapped_before_reaching_api(self):
        client = self._fake_client_with_tool_call()
        with patch("openai.OpenAI", return_value=client):
            OpenAIProvider().chat(
                messages=[
                    {"role": "user", "content": "do it"},
                    {"role": "tool", "content": "result", "tool_call_id": "x"},
                ],
                model="gpt-4o",
                api_key="fake",
            )
        _, kwargs = client.chat.completions.create.call_args
        assert "tool" not in [m["role"] for m in kwargs["messages"]]


class TestAnthropicNativeToolCalling:
    def test_native_tool_use_converted_to_tag_and_parseable(self):
        fake_block = MagicMock()
        fake_block.type = "tool_use"
        fake_block.name = "file_write"
        fake_block.input = {"path": "/repo/train/x.yml"}
        fake_block.id = "toolu_1"
        # hasattr(b, "text") must be False for this block so it's not treated as a text block
        del fake_block.text

        fake_resp = MagicMock(content=[fake_block])
        client = MagicMock()
        client.messages.create.return_value = fake_resp
        with patch("anthropic.Anthropic", return_value=client):
            result = AnthropicProvider().chat(
                messages=[{"role": "user", "content": "make a file"}],
                model="claude-sonnet-5",
                api_key="fake",
                tools=[{"name": "file_write", "description": "d", "parameters": {"type": "object", "properties": {}}}],
            )

        assert "<tool_call>" in result
        parsed = McpHandler().parse_tool_calls(result)
        assert len(parsed) == 1
        assert parsed[0].tool_name == "file_write"
        assert parsed[0].arguments == {"path": "/repo/train/x.yml"}

    def test_tools_actually_sent_to_api(self):
        fake_block = MagicMock()
        fake_block.type = "tool_use"
        fake_block.name = "file_write"
        fake_block.input = {}
        fake_block.id = "toolu_1"
        del fake_block.text
        fake_resp = MagicMock(content=[fake_block])
        client = MagicMock()
        client.messages.create.return_value = fake_resp
        with patch("anthropic.Anthropic", return_value=client):
            AnthropicProvider().chat(
                messages=[{"role": "user", "content": "hi"}],
                model="claude-sonnet-5",
                api_key="fake",
                tools=[{"name": "file_write", "description": "d", "parameters": {}}],
            )
        _, kwargs = client.messages.create.call_args
        assert kwargs["tools"][0]["name"] == "file_write"
        # An empty {} parameters dict is falsy, so tools_to_anthropic_schema's
        # `or {...default...}` fallback kicks in — this is intentional (an
        # empty JSON Schema object would confuse the API), not a bug.
        assert kwargs["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
