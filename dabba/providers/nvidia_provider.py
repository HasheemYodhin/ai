"""
NVIDIA NIM provider — OpenAI-compatible API at integrate.api.nvidia.com/v1
Model IDs verified against the live catalog (July 2026).
"""
from __future__ import annotations
import re
from typing import Iterator, List, Optional
from dabba.providers.base import (
    BaseProvider, ModelInfo,
    tools_to_openai_schema, openai_tool_calls_to_tags, remap_tool_role_for_provider,
)


NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TIMEOUT_SECONDS = 60.0
SLOW_REASONING_TIMEOUT_SECONDS = 300.0
# A single max_tokens budget is often not enough for a full page of code or a
# long explanation — the model hits finish_reason="length" mid-sentence with
# no error, which just looks like the app silently stopped. Bounded
# auto-continuation (re-prompt "continue where you left off" and append)
# fixes that for any completion length instead of chasing an ever-bigger
# fixed cap. Capped so a pathological model can't loop forever.
MAX_LENGTH_CONTINUATIONS = 4
_CONTINUE_PROMPT = "Continue exactly where you left off. Do not repeat any text already written."
# NVIDIA's free-tier NIM endpoints (esp. newly-added models) hit worker
# capacity limits under load — "ResourceExhausted: Worker local total
# request limit reached" — that's usually gone within a few seconds, not a
# real failure, so it's worth a few short-backoff retries before
# surfacing an error.
RESOURCE_EXHAUSTED_RETRIES = 2
RESOURCE_EXHAUSTED_BACKOFF_SECONDS = 3.0
# Capacity is transient on the NIM free tier.  Five minutes made the editor
# appear permanently stuck after one overloaded request; a short cooldown
# avoids hammering the endpoint while allowing the user to continue promptly.
CAPACITY_COOLDOWN_SECONDS = 45.0
DEFAULT_CAPACITY_FALLBACK = "qwen/qwen2.5-coder-32b-instruct"
CAPACITY_FALLBACKS = {
    "deepseek-ai/deepseek-v4-flash": "qwen/qwen2.5-coder-32b-instruct",
    "nvidia/nemotron-3-ultra-550b-a55b": DEFAULT_CAPACITY_FALLBACK,
}

MODELS = [
    # Meta Llama
    ModelInfo("meta/llama-3.3-70b-instruct",              "Llama 3.3 70B",        "nvidia", "high",   "Meta Llama 3.3 70B Instruct",          128000, 0.23, 0.23,  False, True),
    ModelInfo("meta/llama-3.1-8b-instruct",               "Llama 3.1 8B",         "nvidia", "medium", "Meta Llama 3.1 8B Instruct",           128000, 0.05, 0.05,  False, True),
    ModelInfo("meta/llama-3.2-3b-instruct",               "Llama 3.2 3B",         "nvidia", "low",    "Meta Llama 3.2 3B fast",               128000, 0.04, 0.04,  False, True),
    # NVIDIA Nemotron
    ModelInfo("nvidia/llama-3.1-nemotron-70b-instruct",   "Nemotron 70B",         "nvidia", "xhigh",  "NVIDIA Nemotron reasoning model",      128000, 0.35, 0.35,  False, True),
    ModelInfo("nvidia/llama-3.3-nemotron-super-49b-v1",   "Nemotron Super 49B",   "nvidia", "high",   "NVIDIA Nemotron Super",                128000, 0.42, 0.42,  False, True),
    ModelInfo("nvidia/nemotron-3-ultra-550b-a55b",        "Nemotron-3 Ultra 550B", "nvidia", "max",   "NVIDIA Nemotron-3 Ultra 550B model",   8192,  0.0,  0.0,   False, True),
    # DeepSeek — only the full R1 is confirmed live on NVIDIA NIM
    ModelInfo("deepseek-ai/deepseek-r1",                  "DeepSeek R1",          "nvidia", "max",    "DeepSeek R1 full reasoning model",     128000, 0.55, 2.19,  True,  True),
    ModelInfo("deepseek-ai/deepseek-r1-distill-qwen-7b",  "DeepSeek R1 Qwen 7B",  "nvidia", "high",   "DeepSeek R1 distilled (Qwen base)",    128000, 0.08, 0.08,  True,  True),
    ModelInfo("deepseek-ai/deepseek-v4-flash",             "DeepSeek V4 Flash",    "nvidia", "high",   "284B MoE, 1M context, fast coding & agents", 1000000, 0.0, 0.0, False, True),
    # Mistral
    ModelInfo("mistralai/mistral-7b-instruct-v0.3",       "Mistral 7B",           "nvidia", "medium", "Mistral 7B Instruct",                  32768,  0.04, 0.04,  False, True),
    ModelInfo("mistralai/mixtral-8x7b-instruct-v0.1",     "Mixtral 8x7B",         "nvidia", "high",   "Mixtral MoE 8x7B",                     32768,  0.24, 0.24,  False, True),
    ModelInfo("mistralai/mistral-large-2-instruct",       "Mistral Large 2",      "nvidia", "xhigh",  "Mistral Large 2",                      128000, 2.00, 6.00,  False, True),
    # Microsoft Phi
    ModelInfo("microsoft/phi-3.5-mini-instruct",          "Phi-3.5 Mini",         "nvidia", "medium", "Microsoft Phi-3.5 Mini 128K",          128000, 0.05, 0.05,  False, True),
    ModelInfo("microsoft/phi-3-medium-128k-instruct",     "Phi-3 Medium",         "nvidia", "high",   "Microsoft Phi-3 Medium 128K",          128000, 0.12, 0.12,  False, True),
    # Qwen
    ModelInfo("qwen/qwen2.5-72b-instruct",                "Qwen 2.5 72B",         "nvidia", "high",   "Qwen 2.5 72B Instruct",                32768,  0.35, 0.35,  False, True),
    ModelInfo("qwen/qwen2.5-coder-32b-instruct",          "Qwen 2.5 Coder 32B",   "nvidia", "high",   "Qwen 2.5 Coder specialized",           32768,  0.20, 0.20,  False, True),
    # Z.ai GLM — free endpoint on NVIDIA NIM (build.nvidia.com/z-ai/glm-5.2)
    ModelInfo("z-ai/glm-5.2",                             "GLM 5.2",              "nvidia", "max",    "Flagship LLM for agentic workflows, coding, and long-horizon reasoning", 1000000, 0.0, 0.0,  True,  True),
    # ThinkingMachines
    ModelInfo("thinkingmachines/inkling",                 "Inkling",              "nvidia", "max",    "ThinkingMachines Inkling model",       8192,   0.0, 0.0,  False, True),
    # MiniMax
    ModelInfo("minimaxai/minimax-m3",                     "MiniMax M3",           "nvidia", "high",   "MiniMax M3 model",                     1000000, 0.0, 0.0,  True,  True),  # 428B MoE, up to 1M context / 512K output
    # Google Gemma
    ModelInfo("google/gemma-2-2b-it",                     "Gemma-2 2B It",        "nvidia", "low",    "Google Gemma-2 2B Instruct model",     8192,   0.0, 0.0,    False, True),
    # Image generation (FLUX.1-dev via NVIDIA NIM ai.api.nvidia.com)
    ModelInfo("black-forest-labs/flux.1-dev",              "FLUX.1-dev (Image)",   "nvidia", "high",  "FLUX.1-dev image generation via NVIDIA NIM", 0, 0.0, 0.0, False, True),
]

# Models confirmed EOL on NVIDIA NIM — kept here as reference, NOT in active list:
#   google/gemma-3-27b-it       — EOL 2026-05-12
#   google/gemma-3-12b-it       — EOL 2026-05-12
#   deepseek-ai/deepseek-r1-distill-llama-8b — 404 (ID changed / removed)


class NvidiaProvider(BaseProvider):
    name = "nvidia"

    def __init__(self):
        # Per-provider circuit breaker. ProviderRegistry reuses one NVIDIA
        # instance, so a repeatedly overloaded model is not probed (and made
        # to wait through backoff) on every new chat message.
        self._capacity_blocked_until: dict[str, float] = {}

    @staticmethod
    def _capacity_fallback(model: str) -> Optional[str]:
        fallback = CAPACITY_FALLBACKS.get(model, DEFAULT_CAPACITY_FALLBACK)
        return None if fallback == model else fallback

    def _apply_capacity_cooldown(self, params: dict, model: str) -> None:
        import time as _time

        fallback = self._capacity_fallback(model)
        blocked_until = self._capacity_blocked_until.get(model, 0.0)
        if fallback and params.get("model") == model and _time.monotonic() < blocked_until:
            params["model"] = fallback

    def _mark_capacity_cooldown(self, model: str) -> None:
        import time as _time

        self._capacity_blocked_until[model] = _time.monotonic() + CAPACITY_COOLDOWN_SECONDS

    def _timeout_for_model(self, model: str) -> float:
        # Reuse _is_reasoning_model rather than a second hand-maintained list —
        # keeping two lists in sync is exactly how "nemotron" ended up reasoning
        # (long generations, needs the slow bucket) but not slow-timeout'd,
        # and every model gets a lot slower once auto-continuation can chain
        # several full-budget completions back to back.
        model_l = model.lower()
        is_slow = self._is_reasoning_model(model) or model_l == "deepseek-ai/deepseek-v4-flash"
        return SLOW_REASONING_TIMEOUT_SECONDS if is_slow else DEFAULT_TIMEOUT_SECONDS

    def _is_reasoning_model(self, model: str) -> bool:
        model_l = model.lower()
        return (
            "r1" in model_l
            or "nemotron" in model_l
            or "inkling" in model_l
            or "thinkingmachines" in model_l
            or "minimax" in model_l
            or model_l == "z-ai/glm-5.2"
        )

    def _build_params(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> dict:
        model_lower = model.lower()
        processed_messages = remap_tool_role_for_provider(messages)
        if "gemma" in model_lower:
            # Gemma models on NVIDIA NIM do not support the system role
            system_content = []
            other_messages = []
            for msg in processed_messages:
                if msg.get("role") == "system":
                    system_content.append(msg.get("content", ""))
                else:
                    other_messages.append(msg)

            if system_content:
                joined_system = "\n\n".join(system_content)
                for msg in other_messages:
                    if msg.get("role") == "user":
                        if isinstance(msg["content"], str):
                            msg["content"] = f"[System Prompt]\n{joined_system}\n\n{msg['content']}"
                        elif isinstance(msg["content"], list):
                            msg["content"].insert(0, {"type": "text", "text": f"[System Prompt]\n{joined_system}\n\n"})
                        break
                else:
                    other_messages.insert(0, {
                        "role": "user",
                        "content": f"[System Prompt]\n{joined_system}"
                    })
                processed_messages = other_messages

        params: dict = dict(model=model, messages=processed_messages, max_tokens=max_tokens)

        # NVIDIA's GLM runtime enables its long reasoning phase by default.
        # With the UI's deliberately small output limit (256 tokens), that can
        # consume the entire budget before a final answer is emitted and makes
        # an ordinary chat look stuck. Keep GLM fast at low/medium effort and
        # only enable the long thinking path when the registry explicitly asks
        # for it (high/xhigh/max effort).
        if model.lower() == "z-ai/glm-5.2":
            params["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": bool(kwargs.get("thinking", False)),
                }
            }

        # MiniMax M3 defaults to "adaptive" thinking, which — combined with a
        # large tool-schema system prompt — reliably decides to reason at
        # length even for trivial messages, blowing past the client timeout
        # before any text comes back (looks like a hang). Pin it explicitly:
        # disabled for fast low/medium-effort chat, only let it reason when
        # the registry actually asked for that via high+ effort.
        if "minimax" in model.lower():
            params["extra_body"] = {
                "chat_template_kwargs": {
                    "thinking_mode": "enabled" if kwargs.get("thinking", False) else "disabled",
                }
            }

        # Reasoning models work better without explicit temperature.
        if not self._is_reasoning_model(model):
            params["temperature"] = temperature

        tools = kwargs.get("tools")
        if tools:
            params["tools"] = tools_to_openai_schema(tools)
            params["tool_choice"] = "auto"

        return params

    def _client(self, key: str, model: str):
        from openai import OpenAI
        return OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=key,
            timeout=self._timeout_for_model(model),
            max_retries=0,
        )

    @staticmethod
    def _continuation_params(model: str, params: dict) -> dict:
        """
        Params for a "keep writing" continuation call. Continuation only
        needs to resume an in-progress code block or paragraph — letting a
        reasoning model re-enter its planning phase here risks it restating
        ("The user wants...") or re-deriving the whole plan as visible text
        instead of just continuing, which reads as duplicated/leaked
        reasoning in the final answer. Force thinking off so round 2+ only
        continues.
        """
        cont = dict(params)
        model_l = model.lower()
        if model_l == "z-ai/glm-5.2":
            cont["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        elif "minimax" in model_l:
            cont["extra_body"] = {"chat_template_kwargs": {"thinking_mode": "disabled"}}
        return cont

    @staticmethod
    def _accumulate_usage(total: dict, resp_usage) -> dict:
        """Sum token usage across continuation rounds — each round is a real,
        separately-billed API call, so the reported total must reflect all
        of them, not just the first."""
        if resp_usage is None:
            return total
        total["prompt_tokens"] = total.get("prompt_tokens", 0) + (getattr(resp_usage, "prompt_tokens", 0) or 0)
        total["completion_tokens"] = total.get("completion_tokens", 0) + (getattr(resp_usage, "completion_tokens", 0) or 0)
        total["total_tokens"] = total.get("total_tokens", 0) + (getattr(resp_usage, "total_tokens", 0) or 0)
        return total

    @staticmethod
    def _is_resource_exhausted(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "resourceexhausted" in msg or ("503" in msg and "limit reached" in msg)

    def _create_with_retries(self, client, params: dict, model: str, stream: bool = False):
        """
        client.chat.completions.create(**params[, stream=True]) with two
        transient-failure retries layered in: a max_tokens ceiling clamp
        (see _max_tokens_ceiling) and a short-backoff retry for NVIDIA's
        worker-capacity 503s (see RESOURCE_EXHAUSTED_RETRIES above). Mutates
        params["max_tokens"] in place if it clamps, so callers see the
        adjusted value. Raises the same friendly RuntimeErrors chat()/
        stream_chat() already raise for EOL/404/degraded models.
        """
        import time as _time

        self._apply_capacity_cooldown(params, model)
        attempt = 0
        while True:
            try:
                if stream:
                    return client.chat.completions.create(**params, stream=True)
                return client.chat.completions.create(**params)
            except Exception as exc:
                ceiling = self._max_tokens_ceiling(exc)
                if ceiling is not None and ceiling < params["max_tokens"]:
                    params["max_tokens"] = ceiling
                    continue

                if self._is_resource_exhausted(exc) and attempt < RESOURCE_EXHAUSTED_RETRIES:
                    attempt += 1
                    _time.sleep(RESOURCE_EXHAUSTED_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                    continue

                msg = str(exc)
                fallback = self._capacity_fallback(model)
                if self._is_resource_exhausted(exc) and fallback and params.get("model") == model:
                    self._mark_capacity_cooldown(model)
                    params["model"] = fallback
                    attempt = 0
                    continue
                if "410" in msg or "end of life" in msg.lower():
                    raise RuntimeError(
                        f"Model '{model}' is no longer available on NVIDIA NIM (EOL). "
                        "Press F2 to pick a different model."
                    ) from exc
                if "404" in msg:
                    raise RuntimeError(
                        f"Model '{model}' not found on NVIDIA NIM (404). "
                        "Press F2 to pick a different model."
                    ) from exc
                if self._is_resource_exhausted(exc):
                    raise RuntimeError(
                        f"Model '{model}' is at capacity on NVIDIA NIM right now (worker limit "
                        "reached) and stayed overloaded through a few retries. "
                        "Please try again shortly or press F2 to pick a different model."
                    ) from exc
                if "degraded" in msg.lower():
                    raise RuntimeError(
                        f"Model '{model}' is temporarily degraded/unavailable on NVIDIA NIM. "
                        "Please try again later or press F2 to pick a different model."
                    ) from exc
                raise

    def _stream_with_recovery(self, client, params: dict, model: str):
        """
        Iterate an NVIDIA stream with capacity recovery around iteration.

        The OpenAI SDK returns a lazy stream object, so NVIDIA can accept the
        initial request and only raise ResourceExhausted when the caller asks
        for the first (or a later) chunk. _create_with_retries cannot see
        those exceptions. If some text already arrived, continue from that
        exact prefix on the fallback model instead of restarting and
        duplicating the visible answer.
        """
        import time as _time

        lazy_attempt = 0
        partial_text = ""
        while True:
            stream = self._create_with_retries(client, params, model, stream=True)
            emitted_text = False
            try:
                for chunk in stream:
                    if getattr(chunk, "choices", None):
                        delta = chunk.choices[0].delta
                        text = getattr(delta, "content", None)
                        if text:
                            partial_text += text
                            emitted_text = True
                    yield chunk
                return
            except Exception as exc:
                if not self._is_resource_exhausted(exc):
                    raise

                fallback = self._capacity_fallback(model)
                can_fallback = bool(fallback and params.get("model") == model)

                if emitted_text and can_fallback:
                    self._mark_capacity_cooldown(model)
                    params["messages"] = list(params["messages"]) + [
                        {"role": "assistant", "content": partial_text},
                        {"role": "user", "content": _CONTINUE_PROMPT},
                    ]
                    params["model"] = fallback
                    lazy_attempt = 0
                    partial_text = ""
                    continue

                if not emitted_text and lazy_attempt < RESOURCE_EXHAUSTED_RETRIES:
                    lazy_attempt += 1
                    _time.sleep(RESOURCE_EXHAUSTED_BACKOFF_SECONDS * (2 ** (lazy_attempt - 1)))
                    continue

                if not emitted_text and can_fallback:
                    self._mark_capacity_cooldown(model)
                    params["model"] = fallback
                    lazy_attempt = 0
                    partial_text = ""
                    continue

                raise RuntimeError(
                    f"Model '{params.get('model', model)}' is at capacity on NVIDIA NIM "
                    "right now and stayed overloaded through automatic retries."
                ) from exc

    @staticmethod
    def _max_tokens_ceiling(exc: Exception) -> Optional[int]:
        """
        Some smaller NIM-hosted models (e.g. gemma-2-2b-it) cap completion
        length well below their advertised context window and reject an
        over-budget request with a 422 instead of silently clamping it:
            "body -> max_tokens\n Input should be less than or equal to 4096
            (type=less_than_equal; le=4096)"
        Extract that ceiling so the caller can clamp and retry once, instead
        of every model needing its own hardcoded output-length entry.
        """
        match = re.search(r"max_tokens.*?le=(\d+)", str(exc), re.DOTALL)
        return int(match.group(1)) if match else None

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> str:
        usage_out = kwargs.pop("usage_out", None)
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError(
                "NVIDIA API key not set.  In Dabba: press F2, pick any NVIDIA model, "
                "then paste your key.  Get a free key at build.nvidia.com"
            )

        # Explicit timeout — see anthropic_provider.py for why this matters.
        # max_retries=0: the SDK defaults to 2 retries, which silently turns a
        # single timeout into multiple waits with no feedback. GLM 5.2 and R1
        # can cold-start or spend longer reasoning, so they get a larger single
        # request window while ordinary NVIDIA models still fail quickly.
        client = self._client(key, model)
        params = self._build_params(messages, model, max_tokens=max_tokens, temperature=temperature, **kwargs)

        resp = self._create_with_retries(client, params, model)

        message = resp.choices[0].message
        text = (message.content or "").strip()
        if params["model"] != model:
            text = (
                f"_`{model}` is at capacity, so Dabba used `{params['model']}` for this response._\n\n"
                + text
            )
        finish_reason = resp.choices[0].finish_reason
        usage_total: dict = {}
        self._accumulate_usage(usage_total, resp.usage)

        continuation_messages = list(params["messages"])
        continuations = 0
        while finish_reason == "length" and continuations < MAX_LENGTH_CONTINUATIONS:
            if text:
                continuation_messages = continuation_messages + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": _CONTINUE_PROMPT},
                ]
            # else: thinking consumed the entire budget with nothing visible
            # to show for it — nothing to continue from, so retry the same
            # request fresh (thinking forced off below) instead of building
            # on an empty turn.
            cont_params = {**self._continuation_params(model, params), "messages": continuation_messages}
            cont_resp = self._create_with_retries(client, cont_params, model)
            more = (cont_resp.choices[0].message.content or "")
            text = (text + more).strip()
            finish_reason = cont_resp.choices[0].finish_reason
            self._accumulate_usage(usage_total, cont_resp.usage)
            continuations += 1

        if usage_out is not None:
            usage_out.update(usage_total)
        tag_text = openai_tool_calls_to_tags(message)
        return (text + "\n" + tag_text).strip() if tag_text else text

    def stream_chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> Iterator[str]:
        usage_out = kwargs.pop("usage_out", None)
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError(
                "NVIDIA API key not set.  In Dabba: press F2, pick any NVIDIA model, "
                "then paste your key.  Get a free key at build.nvidia.com"
            )

        client = self._client(key, model)
        params = self._build_params(messages, model, max_tokens=max_tokens, temperature=temperature, **kwargs)

        # include_usage: ask for a trailing usage-only chunk (empty choices,
        # populated .usage) — without it, streaming never reports real token
        # counts at all, unlike the non-streaming response.
        params["stream_options"] = {"include_usage": True}

        accumulated = ""
        finish_reason = None
        usage_total: dict = {}
        for chunk in self._stream_with_recovery(client, params, model):
            if getattr(chunk, "usage", None):
                self._accumulate_usage(usage_total, chunk.usage)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                accumulated += text
                yield text
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        continuation_messages = list(params["messages"])
        continuations = 0
        while finish_reason == "length" and continuations < MAX_LENGTH_CONTINUATIONS:
            if accumulated:
                continuation_messages = continuation_messages + [
                    {"role": "assistant", "content": accumulated},
                    {"role": "user", "content": _CONTINUE_PROMPT},
                ]
            # else: thinking consumed the entire budget with nothing visible
            # streamed — retry the same request fresh (thinking forced off
            # below) instead of continuing from an empty turn.
            cont_params = {**self._continuation_params(model, params), "messages": continuation_messages}
            finish_reason = None
            for chunk in self._stream_with_recovery(client, cont_params, model):
                if getattr(chunk, "usage", None):
                    self._accumulate_usage(usage_total, chunk.usage)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    accumulated += text
                    yield text
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
            continuations += 1

        if usage_out is not None:
            usage_out.update(usage_total)

    def list_models(self) -> List[ModelInfo]:
        return MODELS

    def generate_image(self, prompt: str, api_key: str, n: int = 1) -> dict:
        """
        Generate images via NVIDIA NIM's FLUX.1-dev endpoint.
        Correct endpoint: https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev
        (NOTE: image models use ai.api.nvidia.com/v1/genai/, NOT integrate.api.nvidia.com)
        Returns an OpenAI-compatible dict: {"created": ..., "data": [{"b64_json": ...}]}
        """
        import time
        import requests

        if not api_key:
            raise RuntimeError(
                "No NVIDIA API key configured. Set it via Settings → API Keys → NVIDIA."
            )

        # Correct NVIDIA NIM image generation endpoint
        url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
        payload = {
            "prompt": prompt,
            "seed": 0,
            "num_inference_steps": 50,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=120)

        if resp.status_code != 200:
            try:
                err = resp.json()
                msg = err.get("detail") or err.get("message") or err.get("title") or str(err)
            except Exception:
                msg = resp.text or f"HTTP {resp.status_code}"
            raise RuntimeError(f"NVIDIA NIM image generation failed: {msg}")

        data = resp.json()
        images = []
        # NVIDIA genai API returns {"artifacts": [{"base64": "..."}]} format
        for item in data.get("artifacts", []):
            b64 = item.get("base64", "")
            if b64:
                images.append({"b64_json": b64})
            if len(images) >= n:
                break

        # Fallback: standard OpenAI-compat {"data": [{"b64_json": ...}]} format
        if not images:
            for item in data.get("data", []):
                b64 = item.get("b64_json", "")
                url_val = item.get("url", "")
                entry = {}
                if b64:
                    entry["b64_json"] = b64
                if url_val:
                    entry["url"] = url_val
                if entry:
                    images.append(entry)
                if len(images) >= n:
                    break

        if not images:
            raise RuntimeError(
                f"NVIDIA NIM returned no images. Full response: {data}"
            )

        return {"created": int(time.time()), "data": images}
