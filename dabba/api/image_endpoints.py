"""
Image generation endpoint — OpenAI-compatible POST /v1/images/generations.

Provider priority (first with a configured key wins):
  1. NVIDIA NIM (FLUX.1-dev) — uses the existing NVIDIA API key, no extra signup needed.
  2. Google Imagen 3           — high quality, requires a Google AI Studio key.
  3. OpenAI DALL-E / gpt-image-1  — classic fallback (if billing not exhausted).
  4. Hugging Face              — free-tier fallback.

HF model priority (first actively-served wins):
  1. black-forest-labs/FLUX.1-dev
  2. stabilityai/stable-diffusion-xl-base-1.0
  3. stabilityai/stable-diffusion-3.5-medium
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class ImageGenerationRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    size: Optional[
        Literal[
            "auto",
            "256x256",
            "512x512",
            "1024x1024",
            "1024x1792",
            "1792x1024",
            "1024x1536",
            "1536x1024",
        ]
    ] = "1024x1024"
    n: int = 1


# ── NVIDIA NIM Image (FLUX.1-dev via NvidiaProvider) ─────────────────────────


def _generate_via_nvidia(prompt: str, api_key: str, n: int) -> dict:
    """
    Delegates to NvidiaProvider.generate_image() — single source of truth.
    """
    from dabba.providers.nvidia_provider import NvidiaProvider

    return NvidiaProvider().generate_image(prompt, api_key, n)


# ── Google Imagen ─────────────────────────────────────────────────────────────


def _generate_via_google_imagen(prompt: str, api_key: str, n: int) -> dict:
    """
    Generate images via Google's Imagen 3 model using the Gemini API.
    """
    import requests

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"imagen-3.0-generate-002:predict?key={api_key}"
    )
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": max(1, min(n, 4))},
    }
    resp = requests.post(url, json=payload, timeout=90)

    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message", resp.text)
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"
        raise RuntimeError(f"Google Imagen error: {msg}")

    data = resp.json()
    images = []
    for prediction in data.get("predictions", []):
        b64 = prediction.get("bytesBase64Encoded", "")
        if b64:
            images.append({"b64_json": b64})

    if not images:
        raise RuntimeError("Google Imagen returned no images")

    return {"created": int(time.time()), "data": images}


# ── OpenAI DALL-E ─────────────────────────────────────────────────────────────


def _generate_via_openai(
    prompt: str, api_key: str, model: str, size: str, n: int
) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=60.0)
    resp = client.images.generate(model=model, prompt=prompt, size=size, n=n)

    images = []
    for item in resp.data:
        entry = {}
        b64 = getattr(item, "b64_json", None)
        url = getattr(item, "url", None)
        if b64:
            entry["b64_json"] = b64
        if url:
            entry["url"] = url
        images.append(entry)
    return {"created": resp.created, "data": images}


# ── Hugging Face fallback ─────────────────────────────────────────────────────

_HF_IMAGE_MODEL_PRIORITY = [
    "black-forest-labs/FLUX.1-dev",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "stabilityai/stable-diffusion-3.5-medium",
]


def _generate_via_huggingface(prompt: str, hf_token: str, model: str) -> dict:
    import requests

    resp = requests.post(
        f"https://router.huggingface.co/models/{model}",
        headers={"Authorization": f"Bearer {hf_token}"},
        json={"inputs": prompt, "provider": "auto"},
        timeout=120,
    )

    content_type = resp.headers.get("content-type", "")
    if resp.status_code == 200 and content_type.startswith("image/"):
        b64 = base64.b64encode(resp.content).decode("ascii")
        return {"created": int(time.time()), "data": [{"b64_json": b64}]}

    try:
        err = resp.json()
        message = err.get("error") or str(err)
        if err.get("estimated_time"):
            message += (
                f" (model cold-starting, retry in ~{int(err['estimated_time'])}s)"
            )
    except Exception:
        message = resp.text or f"HTTP {resp.status_code}"
    raise RuntimeError(message)


def _generate_via_huggingface_with_fallbacks(
    prompt: str, hf_token: str, requested_model: str | None
) -> dict:
    candidates = []
    if requested_model:
        candidates.append(requested_model)
    for m in _HF_IMAGE_MODEL_PRIORITY:
        if m not in candidates:
            candidates.append(m)

    errors = []
    for model in candidates:
        try:
            return _generate_via_huggingface(prompt, hf_token, model)
        except RuntimeError as exc:
            errors.append(f"{model}: {exc}")

    raise RuntimeError("All HF models failed: " + " | ".join(errors))


# ── Router ────────────────────────────────────────────────────────────────────


def create_image_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["images"])

    @router.post("/images/generations")
    async def generate_images(req: ImageGenerationRequest):
        prompt = req.prompt.strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt cannot be empty")

        from dabba.api.agent_endpoints import _get_agent_proxy

        proxy = _get_agent_proxy()
        keys = getattr(proxy.cli_config, "api_keys", {}) or {}
        # Model-specific FLUX key takes priority over the generic NVIDIA key
        nvidia_key = keys.get("black-forest-labs/flux.1-dev", "") or keys.get(
            "nvidia", ""
        )
        google_key = keys.get("google", "")
        openai_key = keys.get("openai", "")
        hf_key = keys.get("huggingface", "")

        if not nvidia_key and not google_key and not openai_key and not hf_key:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No image-generation provider configured. "
                    "Your NVIDIA key will be used automatically — "
                    "set it via Settings → API Keys → NVIDIA."
                ),
            )

        errors = []
        is_explicit_hf = req.model and req.model.startswith("hf/")
        is_explicit_openai = req.model and (
            req.model.startswith("dall-e") or req.model.startswith("gpt-image")
        )

        # 1. NVIDIA NIM FLUX.1-dev — uses existing NVIDIA key, no extra signup
        if nvidia_key and not is_explicit_hf and not is_explicit_openai:
            try:
                return await asyncio.to_thread(
                    _generate_via_nvidia, prompt, nvidia_key, max(1, min(req.n, 1))
                )
            except Exception as exc:
                errors.append(f"NVIDIA (FLUX.1-dev): {exc}")

        # 2. Google Imagen 3 — best quality (needs Google AI Studio key)
        if google_key and not is_explicit_hf and not is_explicit_openai:
            try:
                return await asyncio.to_thread(
                    _generate_via_google_imagen,
                    prompt,
                    google_key,
                    max(1, min(req.n, 4)),
                )
            except Exception as exc:
                errors.append(f"Google Imagen: {exc}")

        # 3. OpenAI DALL-E / gpt-image-1
        if openai_key and not is_explicit_hf:
            try:
                return await asyncio.to_thread(
                    _generate_via_openai,
                    prompt,
                    openai_key,
                    req.model or "gpt-image-1",
                    req.size or "1024x1024",
                    max(1, min(req.n, 4)),
                )
            except Exception as exc:
                errors.append(f"OpenAI: {exc}")

        # 4. Hugging Face — free-tier fallback
        if hf_key:
            explicit_hf_model = req.model[3:] if is_explicit_hf else None
            try:
                return await asyncio.to_thread(
                    _generate_via_huggingface_with_fallbacks,
                    prompt,
                    hf_key,
                    explicit_hf_model,
                )
            except Exception as exc:
                errors.append(f"Hugging Face: {exc}")

        raise HTTPException(
            status_code=502, detail="Image generation failed — " + " | ".join(errors)
        )

    return router
