from __future__ import annotations
import json as _json
from typing import Any, Dict, List, Optional
from dabba.providers.base import (
    BaseProvider,
    ModelInfo,
    tools_to_openai_schema,
    remap_tool_role_for_provider,
)

MODELS = [
    ModelInfo(
        "gpt-6.2-astra",
        "GPT-6.2 Astra",
        "openai",
        "max",
        "Best for complex reasoning and coding",
        1050000,
        8.0,
        40.0,
        True,
        True,
        max_output_tokens=128000,
        supports_vision=True,
    ),
    ModelInfo(
        "gpt-6.2-sol",
        "GPT-6.2 Sol",
        "openai",
        "high",
        "Balanced capability and cost",
        1050000,
        2.0,
        10.0,
        True,
        True,
        max_output_tokens=128000,
        supports_vision=True,
    ),
    ModelInfo(
        "gpt-6.1-terra",
        "GPT-6.1 Terra",
        "openai",
        "medium",
        "Fast everyday model",
        1050000,
        1.0,
        5.0,
        True,
        True,
        max_output_tokens=128000,
        supports_vision=True,
    ),
    ModelInfo(
        "gpt-6-luna",
        "GPT-6 Luna",
        "openai",
        "low",
        "High-volume, cost-sensitive work",
        1050000,
        0.1,
        0.5,
        True,
        True,
        max_output_tokens=128000,
        supports_vision=True,
    ),
]

# Reasoning models reject custom temperature/top_p; their depth is set through
# reasoning.effort instead. GPT-6.x accepts low|medium|high|xhigh|max, which
# matches Dabba's effort tiers one-to-one.
GPT6_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
# Older reasoning models (gpt-5.x, o-series) only accept up to "high".
LEGACY_REASONING_EFFORTS = {"low", "medium", "high"}


def _is_reasoning_model(model: str) -> bool:
    return model.startswith(("gpt-6", "gpt-5", "o1", "o3", "o4"))


def _reasoning_effort(model: str, effort: Optional[str]) -> str:
    effort = effort or "medium"
    if model.startswith("gpt-6"):
        return effort if effort in GPT6_EFFORTS else "medium"
    # Clamp xhigh/max for older reasoning models.
    return effort if effort in LEGACY_REASONING_EFFORTS else "high"


def _to_responses_content(content: Any, role: str) -> Any:
    """Convert Chat Completions content (str or vision parts) to Responses input.

    Responses uses typed parts: input_text / input_image for user and system
    turns, output_text for assistant turns. Plain strings pass through as-is.
    """
    if not isinstance(content, list):
        return "" if content is None else content
    text_type = "output_text" if role == "assistant" else "input_text"
    parts = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            parts.append({"type": text_type, "text": part.get("text", "")})
        elif part.get("type") == "image_url" and role != "assistant":
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if url:
                parts.append({"type": "input_image", "image_url": url})
    return parts


def _function_calls_to_tags(output_items: Any) -> str:
    """Convert Responses `function_call` output items into dabba <tool_call> tags."""
    blocks = []
    for item in output_items or []:
        if getattr(item, "type", None) != "function_call":
            continue
        try:
            args = _json.loads(item.arguments) if item.arguments else {}
        except (ValueError, TypeError):
            args = {}
        payload = {"name": item.name, "arguments": args, "call_id": item.call_id}
        blocks.append(f"<tool_call>\n{_json.dumps(payload)}\n</tool_call>")
    return "\n".join(blocks)


class OpenAIProvider(BaseProvider):
    name = "openai"

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> str:
        from openai import OpenAI

        usage_out = kwargs.pop("usage_out", None)
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError("OpenAI API key not set. Run: /keys set openai <key>")

        # Explicit timeout — see anthropic_provider.py for why this matters:
        # llm_generate runs this synchronously, so an unbounded hang here
        # would freeze the whole server's event loop. max_retries=0: the SDK
        # defaults to 2 retries, silently turning one 60s timeout into up to
        # 180s of wait with no feedback — fail fast instead (UI has Retry).
        client = OpenAI(api_key=key, timeout=60.0, max_retries=0)

        # Uses the Responses API: GPT-6.x models only support tool calling
        # there, not in Chat Completions. System prompts go to `instructions`;
        # tool results are already flattened to user turns by
        # remap_tool_role_for_provider, so no call_id pairing is needed.
        instructions = []
        input_items = []
        for m in remap_tool_role_for_provider(messages):
            role = m.get("role", "user")
            if role == "system":
                content = m.get("content")
                instructions.append(
                    content if isinstance(content, str) else str(content or "")
                )
                continue
            input_items.append(
                {"role": role, "content": _to_responses_content(m.get("content"), role)}
            )

        # store=False: don't keep conversations on OpenAI's side; Dabba
        # already stores history itself.
        params: Dict[str, Any] = dict(model=model, input=input_items, store=False)
        if instructions:
            params["instructions"] = "\n\n".join(instructions)
        if max_tokens:
            params["max_output_tokens"] = max_tokens

        if _is_reasoning_model(model):
            params["reasoning"] = {
                "effort": _reasoning_effort(model, kwargs.get("effort"))
            }
        else:
            # Non-reasoning models (e.g. a saved gpt-4o selection) still take
            # sampling controls.
            if temperature is not None:
                params["temperature"] = temperature
            if kwargs.get("top_p") is not None:
                params["top_p"] = kwargs["top_p"]
        # The Responses API has no stop / presence_penalty / frequency_penalty
        # parameters, so those Chat Completions overrides are dropped here.

        # Native function-calling — makes tool use reliable regardless of
        # whether the model would have spontaneously emitted a <tool_call>
        # tag on its own (see agent_loop.py's _tool_dicts()/tools= plumbing).
        tools = kwargs.get("tools")
        if tools:
            params["tools"] = [
                {
                    "type": "function",
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "parameters": t["function"]["parameters"],
                }
                for t in tools_to_openai_schema(tools)
            ]
            params["tool_choice"] = "auto"

        resp = client.responses.create(**params)
        text = (getattr(resp, "output_text", "") or "").strip()

        usage = getattr(resp, "usage", None)
        if usage is not None and usage_out is not None:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            usage_out.update(
                {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": getattr(usage, "total_tokens", 0)
                    or input_tokens + output_tokens,
                }
            )

        tag_text = _function_calls_to_tags(getattr(resp, "output", None))
        return (text + "\n" + tag_text).strip() if tag_text else text

    def list_models(self) -> List[ModelInfo]:
        return MODELS
