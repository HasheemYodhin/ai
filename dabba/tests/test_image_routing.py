import asyncio
from types import SimpleNamespace

import pytest
import requests
from fastapi import HTTPException

from dabba.api import agent_endpoints
from dabba.api.image_endpoints import ImageGenerationRequest, create_image_router
from dabba.providers.nvidia_provider import FLUX_IMAGE_MODEL
from dabba.providers.registry import ProviderRegistry


@pytest.mark.parametrize("status", [200, 403])
def test_explicit_flux_uses_render_key_and_image_api(monkeypatch, status):
    registry = ProviderRegistry.__new__(ProviderRegistry)
    registry.config = SimpleNamespace(api_keys={"openai": "unrelated-test"})
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-test")
    proxy = SimpleNamespace(_get_provider_registry=lambda: registry)
    monkeypatch.setattr(agent_endpoints, "_get_agent_proxy", lambda: proxy)

    def generate(url, *, headers, json, timeout):
        assert url == f"https://ai.api.nvidia.com/v1/genai/{FLUX_IMAGE_MODEL}"
        assert headers["Authorization"] == "Bearer nvidia-test"
        assert json == {"prompt": "A mountain", "seed": 0, "steps": 50}
        return SimpleNamespace(
            status_code=status,
            json=lambda: (
                {"artifacts": [{"base64": "image"}]}
                if status == 200
                else {"detail": "upstream error with sensitive data"}
            ),
        )

    monkeypatch.setattr(requests, "post", generate)
    generate_images = create_image_router().routes[0].endpoint
    request = ImageGenerationRequest(prompt="A mountain", model=FLUX_IMAGE_MODEL)
    if status == 200:
        assert asyncio.run(generate_images(request))["data"] == [{"b64_json": "image"}]
    else:
        with pytest.raises(
            HTTPException, match="NVIDIA rejected the image request"
        ) as error:
            asyncio.run(generate_images(request))
        assert error.value.status_code == 401
        assert "sensitive data" not in error.value.detail
