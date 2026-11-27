from dabba.providers.base import ModelInfo
from dabba.providers.chat_completions_provider import ChatCompletionsProvider


def _gemini(model, name, tier, description, cost_input, cost_output, max_output=65_536):
    return ModelInfo(
        model,
        f"Gemini {name}",
        "google",
        tier,
        description,
        1_048_576,
        cost_input,
        cost_output,
        supports_thinking=True,
        max_output_tokens=max_output,
        supports_vision=True,
    )


MODELS = [
    _gemini(
        "gemini-3.5-flash-lite",
        "3.5 Flash-Lite",
        "low",
        "Efficient everyday chat.",
        0.30,
        2.50,
    ),
    _gemini(
        "gemini-4-hydrogen",
        "4 Hydrogen",
        "medium",
        "Fast multimodal chat and coding.",
        1.50,
        7.50,
        1_048_576,
    ),
    _gemini(
        "gemini-3.8-flash",
        "3.8 Flash",
        "high",
        "Multimodal coding and reasoning.",
        1.50,
        7.50,
    ),
    _gemini(
        "gemini-4-argon",
        "4 Argon",
        "high",
        "Efficient advanced reasoning.",
        4.00,
        20.00,
        1_048_576,
    ),
    _gemini(
        "gemini-4-neon",
        "4 Neon",
        "xhigh",
        "Complex coding and multimodal tasks.",
        3.00,
        15.00,
        1_048_576,
    ),
    _gemini(
        "gemini-4-carbon",
        "4 Carbon",
        "max",
        "Advanced reasoning for complex tasks.",
        4.00,
        20.00,
        1_048_576,
    ),
    _gemini(
        "gemini-2.5-flash-lite",
        "2.5 Flash-Lite",
        "low",
        "Lightweight Gemini 2.5 model.",
        0.10,
        0.40,
    ),
]


class GoogleProvider(ChatCompletionsProvider):
    name = "google"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    key_env = "GEMINI_API_KEY"
    stream_usage = True

    def _params(self, messages, model, max_tokens, temperature, options):
        params = super()._params(messages, model, max_tokens, temperature, options)
        if model.startswith(("gemini-3.", "gemini-4-")):
            effort = options.get("effort") or "medium"
            if effort in {"xhigh", "max"}:
                effort = (
                    "xhigh"
                    if model in {"gemini-4-neon", "gemini-4-hydrogen"}
                    else "high"
                )
            elif effort == "low" and not model.startswith("gemini-4-"):
                effort = "minimal"
            params["reasoning_effort"] = effort
        return params

    def list_models(self):
        return MODELS
