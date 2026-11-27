from dabba.providers.base import ModelInfo
from dabba.providers.chat_completions_provider import ChatCompletionsProvider

MODELS = [
    ModelInfo(
        "vyceai/glm-5.3-flash",
        "GLM 5.3 Flash",
        "vyceai",
        "high",
        "Reasoning and tool calling via the VyceAI promo pool.",
        500_000,
        supports_thinking=True,
    ),
    ModelInfo(
        "vyceai/nemotron-3.5-super-vl",
        "Nemotron 3.5 Super VL",
        "vyceai",
        "high",
        "Multimodal reasoning via the VyceAI promo pool.",
        1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        "vyceai/gpt-oss-120b",
        "GPT-OSS 120B",
        "vyceai",
        "high",
        "Coding and reasoning via the VyceAI promo pool.",
        128_000,
        supports_thinking=True,
    ),
    ModelInfo(
        "vyceai/wave",
        "Wave",
        "vyceai",
        "low",
        "Basic chat via the VyceAI promo pool.",
        128_000,
    ),
]


class VyceAIProvider(ChatCompletionsProvider):
    name = "vyceai"
    base_url = "https://vyceai.com/v1"
    key_env = "VYCEAI_API_KEY"

    def _params(self, messages, model, max_tokens, temperature, options):
        return super()._params(
            messages, model.removeprefix("vyceai/"), max_tokens, temperature, options
        )

    def list_models(self):
        return MODELS
