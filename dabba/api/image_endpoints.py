"""
Image generation endpoint — OpenAI-compatible POST /v1/images/generations.

Dabba's own model is a small text transformer with no image-generation
capability, so this proxies to whichever image-capable provider has a
configured, working key. Tries OpenAI (gpt-image-1 / DALL-E) first, then
falls back to Hugging Face's Inference Providers router (FLUX.1-schnell) —
useful when the OpenAI account has hit a billing limit but an HF token is
still configured (the same token that powers hf/ chat models like Llama
3.1 8B — note Llama itself is text-only; HF just also hosts real image
models behind the same router).
"""
from __future__ import annotations

import asyncio
import base64
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class ImageGenerationRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    size: Optional[str] = "1024x1024"
    n: int = 1


def _generate_via_openai(prompt: str, api_key: str, model: str, size: str, n: int) -> dict:
    from openai import OpenAI
    # Same 60s timeout convention as the chat providers — an unbounded hang
    # here would freeze the request indefinitely.
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


def _generate_via_huggingface(prompt: str, hf_token: str, model: str) -> dict:
    """
    Calls HF's unified Inference Providers router for a text-to-image model
    (the same router.huggingface.co host the chat provider uses — see
    huggingface_provider.py; the older api-inference.huggingface.co host is
    deprecated and doesn't even resolve in some network environments).
    Returns raw image bytes on success (Content-Type: image/*), or a JSON
    error body (e.g. {"error": "...", "estimated_time": ...} while a cold
    model loads).
    """
    import requests

    resp = requests.post(
        f"https://router.huggingface.co/hf-inference/models/{model}",
        headers={"Authorization": f"Bearer {hf_token}"},
        json={"inputs": prompt},
        timeout=90,
    )

    content_type = resp.headers.get("content-type", "")
    if resp.status_code == 200 and content_type.startswith("image/"):
        b64 = base64.b64encode(resp.content).decode("ascii")
        return {"created": int(time.time()), "data": [{"b64_json": b64}]}

    try:
        err = resp.json()
        message = err.get("error") or str(err)
        if err.get("estimated_time"):
            message += f" (model is cold-starting, retry in ~{int(err['estimated_time'])}s)"
    except Exception:
        message = resp.text or f"HTTP {resp.status_code}"
    raise RuntimeError(message)


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
        openai_key = keys.get("openai", "")
        hf_key = keys.get("huggingface", "")

        if not openai_key and not hf_key:
            raise HTTPException(
                status_code=400,
                detail="No image-generation provider configured. Set a key: /keys set openai <key> or /keys set huggingface <key>",
            )

        errors = []

        if openai_key and (req.model is None or not req.model.startswith("hf/")):
            try:
                return await asyncio.to_thread(
                    _generate_via_openai, prompt, openai_key,
                    req.model or "gpt-image-1", req.size or "1024x1024", max(1, min(req.n, 4)),
                )
            except Exception as exc:
                errors.append(f"OpenAI: {exc}")

        if hf_key:
            hf_model = (req.model[3:] if req.model and req.model.startswith("hf/")
                        else "black-forest-labs/FLUX.1-schnell")
            try:
                return await asyncio.to_thread(_generate_via_huggingface, prompt, hf_key, hf_model)
            except Exception as exc:
                errors.append(f"Hugging Face ({hf_model}): {exc}")

        raise HTTPException(status_code=502, detail="Image generation failed — " + " | ".join(errors))

    return router
