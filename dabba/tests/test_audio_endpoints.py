import base64

import pytest
from fastapi import HTTPException

from dabba.api import audio_endpoints


def _endpoint(path: str, method: str):
    router = audio_endpoints.create_audio_router()
    return next(
        route.endpoint
        for route in router.routes
        if route.path == path and method in route.methods
    )


@pytest.mark.asyncio
async def test_audio_status_reports_both_capabilities():
    result = await _endpoint("/v1/audio/status", "GET")()

    assert "transcription" in result
    assert "speech" in result


@pytest.mark.asyncio
async def test_transcribe_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr(audio_endpoints.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    request = audio_endpoints.TranscribeRequest(
        audio_base64=base64.b64encode(b"audio").decode(),
        model="unknown",
    )

    with pytest.raises(HTTPException, match="Unsupported Whisper model") as error:
        await _endpoint("/v1/transcribe", "POST")(request)

    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_rejects_invalid_base64(monkeypatch):
    monkeypatch.setattr(audio_endpoints.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    request = audio_endpoints.TranscribeRequest(audio_base64="not valid base64!", model="base")

    with pytest.raises(HTTPException, match="Invalid audio data") as error:
        await _endpoint("/v1/transcribe", "POST")(request)

    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_runs_worker_and_returns_text(monkeypatch):
    monkeypatch.setattr(audio_endpoints.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(audio_endpoints, "_transcribe_file", lambda path, model: "hello from audio")
    request = audio_endpoints.TranscribeRequest(
        audio_base64=base64.b64encode(b"fake audio container").decode(),
        model="base",
    )

    result = await _endpoint("/v1/transcribe", "POST")(request)

    assert result == {"text": "hello from audio"}
