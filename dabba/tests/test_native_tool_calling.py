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

import pytest
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
        loop = AgentLoop(
            registry=ToolRegistry(), config=config, llm_generate=fake_llm_generate
        )
        loop.run("create a file in the train directory")

        system_msg = next(
            m["content"] for m in captured["messages"] if m["role"] == "system"
        )
        assert "/repo/train" in system_msg
        assert captured["tools"] is not None  # tools= was passed to llm_generate

    def test_agent_loop_without_workspace_root_omits_grounding(self):
        captured = {}

        def fake_llm_generate(messages, params):
            captured["messages"] = messages
            return "ok"

        config = AgentConfig(workspace_root=None, use_planning=False)
        loop = AgentLoop(
            registry=ToolRegistry(), config=config, llm_generate=fake_llm_generate
        )
        loop.run("hello")

        system_msg = next(
            m["content"] for m in captured["messages"] if m["role"] == "system"
        )
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


class TestMalformedTextToolCalls:
    def test_repairs_duplicate_arguments_brace(self):
        response = (
            "<tool_call>\n"
            '{"name":"file_read", {"arguments":{"path":"backend/app/main.py"}}\n'
            "</tool_call>"
        )

        calls = McpHandler().parse_tool_calls(response)

        assert len(calls) == 1
        assert calls[0].tool_name == "file_read"
        assert calls[0].arguments["path"] == "backend/app/main.py"

    def test_recovers_multiple_calls_without_closing_tags(self):
        response = (
            "Working now.\n<tool_call>\n"
            '{"name":"file_write","arguments":{"path":"a.py","content":"a"}}\n'
            "<tool_call>\n"
            '{"name":"file_write","arguments":{"path":"b.py","content":"b"}}'
        )

        handler = McpHandler()
        calls = handler.parse_tool_calls(response)

        assert [call.arguments["path"] for call in calls] == ["a.py", "b.py"]
        assert handler.strip_tool_calls(response) == "Working now."

    def test_incomplete_call_remains_visible_for_completion_validation(self):
        response = '<tool_call>{"name":"file_write","arguments":{"path":"a.py"'

        assert McpHandler().parse_tool_calls(response) == []
        assert "<tool_call>" in McpHandler.strip_tool_calls(response)


class TestOpenAINativeToolCalling:
    """OpenAIProvider uses the Responses API (GPT-6.x tool calling needs it)."""

    @staticmethod
    def _fake_client(output_text="", output=None):
        fake_resp = MagicMock(output_text=output_text, output=output or [], usage=None)
        client = MagicMock()
        client.responses.create.return_value = fake_resp
        return client

    def _fake_client_with_tool_call(self):
        fake_call = MagicMock()
        fake_call.type = "function_call"
        fake_call.name = "file_write"
        fake_call.call_id = "call_1"
        fake_call.arguments = json.dumps(
            {"path": "/repo/train/x.yml", "content": "a: b"}
        )
        return self._fake_client("Creating it now.", [fake_call])

    def test_native_tool_call_converted_to_tag_and_parseable(self):
        client = self._fake_client_with_tool_call()
        with patch("openai.OpenAI", return_value=client):
            result = OpenAIProvider().chat(
                messages=[{"role": "user", "content": "make a file"}],
                model="gpt-6.2-sol",
                api_key="fake",
                tools=[
                    {
                        "name": "file_write",
                        "description": "writes a file",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
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
                model="gpt-6.2-sol",
                api_key="fake",
                tools=[{"name": "file_write", "description": "d", "parameters": {}}],
            )
        _, kwargs = client.responses.create.call_args
        assert kwargs["tool_choice"] == "auto"
        # Responses API tools are flat: name sits beside type, not under "function".
        assert kwargs["tools"][0]["type"] == "function"
        assert kwargs["tools"][0]["name"] == "file_write"

    def test_no_tools_kwarg_preserves_old_behavior(self):
        client = self._fake_client("plain text reply")
        with patch("openai.OpenAI", return_value=client):
            result = OpenAIProvider().chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-6.2-sol",
                api_key="fake",
            )
        assert result == "plain text reply"
        _, kwargs = client.responses.create.call_args
        assert "tools" not in kwargs

    def test_tool_role_messages_remapped_before_reaching_api(self):
        client = self._fake_client_with_tool_call()
        with patch("openai.OpenAI", return_value=client):
            OpenAIProvider().chat(
                messages=[
                    {"role": "user", "content": "do it"},
                    {"role": "tool", "content": "result", "tool_call_id": "x"},
                ],
                model="gpt-6.2-sol",
                api_key="fake",
            )
        _, kwargs = client.responses.create.call_args
        assert "tool" not in [m["role"] for m in kwargs["input"]]

    def test_system_prompt_sent_as_instructions(self):
        client = self._fake_client("ok")
        with patch("openai.OpenAI", return_value=client):
            OpenAIProvider().chat(
                messages=[
                    {"role": "system", "content": "Be terse."},
                    {"role": "user", "content": "hi"},
                ],
                model="gpt-6.2-sol",
                api_key="fake",
            )
        _, kwargs = client.responses.create.call_args
        assert kwargs["instructions"] == "Be terse."
        assert [m["role"] for m in kwargs["input"]] == ["user"]
        assert kwargs["store"] is False

    def test_gpt6_sends_reasoning_effort_and_no_temperature(self):
        client = self._fake_client("ok")
        with patch("openai.OpenAI", return_value=client):
            OpenAIProvider().chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-6.2-astra",
                api_key="fake",
                temperature=0.3,
                effort="xhigh",
            )
        _, kwargs = client.responses.create.call_args
        assert kwargs["reasoning"] == {"effort": "xhigh"}
        assert "temperature" not in kwargs

    def test_older_reasoning_model_clamps_effort(self):
        client = self._fake_client("ok")
        with patch("openai.OpenAI", return_value=client):
            OpenAIProvider().chat(
                messages=[{"role": "user", "content": "hi"}],
                model="o3",
                api_key="fake",
                effort="max",
            )
        _, kwargs = client.responses.create.call_args
        assert kwargs["reasoning"] == {"effort": "high"}

    def test_non_reasoning_model_keeps_temperature(self):
        client = self._fake_client("ok")
        with patch("openai.OpenAI", return_value=client):
            OpenAIProvider().chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-4o",
                api_key="fake",
                temperature=0.3,
            )
        _, kwargs = client.responses.create.call_args
        assert kwargs["temperature"] == 0.3
        assert "reasoning" not in kwargs

    def test_image_parts_converted_to_responses_format(self):
        client = self._fake_client("ok")
        with patch("openai.OpenAI", return_value=client):
            OpenAIProvider().chat(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "what is this"},
                            {"type": "image_url", "image_url": {"url": "data:x"}},
                        ],
                    }
                ],
                model="gpt-6.2-sol",
                api_key="fake",
            )
        _, kwargs = client.responses.create.call_args
        assert kwargs["input"][0]["content"] == [
            {"type": "input_text", "text": "what is this"},
            {"type": "input_image", "image_url": "data:x"},
        ]


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
                tools=[
                    {
                        "name": "file_write",
                        "description": "d",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
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
        assert kwargs["tools"][0]["input_schema"] == {
            "type": "object",
            "properties": {},
        }


class TestClaude5RequestShape:
    """Claude 5.x models 400 on temperature/top_p and thinking budget_tokens."""

    @staticmethod
    def _text_resp(text="ok"):
        block = MagicMock(type="text", text=text)
        return MagicMock(content=[block], stop_reason="end_turn", usage=None)

    def test_opus_5_5_uses_effort_and_refusal_fallbacks(self):
        client = MagicMock()
        client.beta.messages.create.return_value = self._text_resp()
        with patch("anthropic.Anthropic", return_value=client):
            AnthropicProvider().chat(
                messages=[{"role": "user", "content": "hi"}],
                model="claude-opus-5-5",
                api_key="fake",
                temperature=0.3,
                top_p=0.9,
                thinking=True,
                effort="high",
            )
        client.messages.create.assert_not_called()
        _, kwargs = client.beta.messages.create.call_args
        assert kwargs["output_config"] == {"effort": "high"}
        assert kwargs["fallbacks"] == "default"
        for rejected in ("temperature", "top_p", "thinking"):
            assert rejected not in kwargs

    def test_haiku_5_5_has_no_server_side_fallback(self):
        client = MagicMock()
        client.messages.create.return_value = self._text_resp()
        with patch("anthropic.Anthropic", return_value=client):
            AnthropicProvider().chat(
                messages=[{"role": "user", "content": "hi"}],
                model="claude-haiku-5-5",
                api_key="fake",
            )
        client.beta.messages.create.assert_not_called()
        _, kwargs = client.messages.create.call_args
        # Haiku 5.5 defaults to medium effort, so it is always sent explicitly.
        assert kwargs["output_config"] == {"effort": "medium"}
        assert "temperature" not in kwargs

    def test_refusal_raises_instead_of_empty_reply(self):
        resp = MagicMock(content=[], stop_reason="refusal")
        resp.stop_details.explanation = "declined"
        client = MagicMock()
        client.beta.messages.create.return_value = resp
        with patch("anthropic.Anthropic", return_value=client):
            with pytest.raises(RuntimeError, match="declined"):
                AnthropicProvider().chat(
                    messages=[{"role": "user", "content": "hi"}],
                    model="claude-sonnet-5-5",
                    api_key="fake",
                )
