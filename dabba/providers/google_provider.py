from __future__ import annotations
from typing import Dict, List
from dabba.providers.base import BaseProvider, ModelInfo


MODELS = [
    ModelInfo("gemini-2.5-pro",         "Gemini 2.5 Pro",        "google", "xhigh",  "Best Gemini, deep reasoning",   1000000, 1.25,  10.0, True,  True),
    ModelInfo("gemini-2.5-flash",       "Gemini 2.5 Flash",      "google", "high",   "Fast + thinking",               1000000, 0.30,  2.5,  True,  True),
    ModelInfo("gemini-2.5-flash-lite",  "Gemini 2.5 Flash Lite", "google", "medium", "Cheapest 2.5-gen, still fast",  1000000, 0.10,  0.40, False, True),
    ModelInfo("gemini-2.0-flash",       "Gemini 2.0 Flash",      "google", "medium", "Fast, efficient",               1000000, 0.10,  0.40, False, True),
    ModelInfo("gemini-2.0-flash-lite",  "Gemini 2.0 Lite",       "google", "low",    "Lightest, cheapest 2.0-gen",    1000000, 0.075, 0.30, False, True),
]


class GoogleProvider(BaseProvider):
    name = "google"

    def chat(self, messages, model, max_tokens=4096, temperature=0.7, **kwargs) -> str:
        import google.generativeai as genai
        key = kwargs.get("api_key", "")
        if not key:
            raise RuntimeError("Google API key not set. Run: /keys set google <key>")

        genai.configure(api_key=key)
        gmodel = genai.GenerativeModel(model_name=model)

        history, system_text = self._convert_messages(messages)

        if system_text and history:
            history[0]["parts"][0] = f"[System: {system_text}]\n\n{history[0]['parts'][0]}"

        if not history:
            return ""

        chat = gmodel.start_chat(history=history[:-1])
        last_msg = history[-1]["parts"][0]

        gen_config = genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        # Explicit timeout — see anthropic_provider.py for why this matters.
        resp = chat.send_message(
            last_msg, generation_config=gen_config, request_options={"timeout": 60},
        )
        return resp.text.strip()

    @staticmethod
    def _convert_messages(messages):
        """
        Convert OpenAI-style messages to Gemini's alternating user/model history.

        Gemini requires strict user/model alternation, so consecutive
        same-role turns (e.g. a "tool" result right after "assistant" text,
        which both need to look like additional user context) are merged
        into one turn instead of being dropped or breaking the API call.
        """
        history: List[Dict] = []
        system_text = ""

        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "") or ""

            if role == "system":
                system_text = content
                continue

            gemini_role = "model" if role == "assistant" else "user"
            # "tool" and "user" both map to "user" — label tool output so the
            # model knows it's a result, not a new user request.
            text = f"[Tool result]\n{content}" if role == "tool" else content

            if history and history[-1]["role"] == gemini_role:
                history[-1]["parts"][0] += "\n\n" + text
            else:
                history.append({"role": gemini_role, "parts": [text]})

        return history, system_text

    def list_models(self) -> List[ModelInfo]:
        return MODELS
