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


def test_find_ffmpeg_prefers_the_explicit_path(monkeypatch, tmp_path):
    fake = tmp_path / "my-ffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("DABBA_FFMPEG", str(fake))
    monkeypatch.setattr(audio_endpoints.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    assert audio_endpoints.find_ffmpeg() == str(fake)


def test_find_ffmpeg_checks_common_folders_when_path_is_short(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.delenv("DABBA_FFMPEG", raising=False)
    monkeypatch.setattr(audio_endpoints.shutil, "which", lambda _: None)
    monkeypatch.setitem(__import__("sys").modules, "imageio_ffmpeg", None)  # simulate not installed
    monkeypatch.setattr(audio_endpoints, "_FFMPEG_FALLBACK_DIRS", (str(tmp_path),))

    assert audio_endpoints.find_ffmpeg() == str(fake)


def test_find_ffmpeg_returns_none_when_nothing_is_installed(monkeypatch, tmp_path):
    monkeypatch.delenv("DABBA_FFMPEG", raising=False)
    monkeypatch.setattr(audio_endpoints.shutil, "which", lambda _: None)
    monkeypatch.setitem(__import__("sys").modules, "imageio_ffmpeg", None)
    monkeypatch.setattr(audio_endpoints, "_FFMPEG_FALLBACK_DIRS", (str(tmp_path),))

    assert audio_endpoints.find_ffmpeg() is None


def test_ensure_ffmpeg_on_path_exposes_the_plain_name(monkeypatch, tmp_path):
    odd_name = tmp_path / "ffmpeg-linux-x86_64-v7"
    odd_name.write_text("#!/bin/sh\n")
    odd_name.chmod(0o755)
    monkeypatch.setenv("DABBA_FFMPEG", str(odd_name))
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(audio_endpoints, "_ffmpeg_alias_dir", None)

    assert audio_endpoints.ensure_ffmpeg_on_path() == str(odd_name)
    # whisper runs the bare name `ffmpeg`, which must now resolve.
    assert audio_endpoints.shutil.which("ffmpeg") is not None


@pytest.mark.asyncio
async def test_transcribe_explains_a_missing_ffmpeg(monkeypatch):
    monkeypatch.setattr(audio_endpoints, "ensure_ffmpeg_on_path", lambda: None)
    request = audio_endpoints.TranscribeRequest(
        audio_base64=base64.b64encode(b"audio").decode(), model="base"
    )

    with pytest.raises(HTTPException, match="ffmpeg is required") as error:
        await _endpoint("/v1/transcribe", "POST")(request)

    assert error.value.status_code == 503


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
    request = audio_endpoints.TranscribeRequest(
        audio_base64="not valid base64!", model="base"
    )

    with pytest.raises(HTTPException, match="Invalid audio data") as error:
        await _endpoint("/v1/transcribe", "POST")(request)

    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_runs_worker_and_returns_text(monkeypatch):
    monkeypatch.setattr(audio_endpoints.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        audio_endpoints, "_transcribe_file", lambda path, model: "hello from audio"
    )
    request = audio_endpoints.TranscribeRequest(
        audio_base64=base64.b64encode(b"fake audio container").decode(),
        model="base",
    )

    result = await _endpoint("/v1/transcribe", "POST")(request)

    assert result == {"text": "hello from audio"}
