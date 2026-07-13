"""
Voice input for the VSCode extension's mic button.

VS Code webviews can't reliably get microphone permission via
getUserMedia — there's no documented WebviewOptions flag for it, and the
browser's built-in SpeechRecognition API (webkitSpeechRecognition) needs
network access to a speech backend that isn't available from inside the
webview sandbox either. So recording happens on the extension host
(plain Node, full OS access) via `arecord`, and the resulting WAV is
shipped here for local transcription — no cloud audio API involved.
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

WHISPER_MODELS = {"tiny", "base", "small", "medium", "large"}
DEFAULT_VOICE = "en_US-lessac-medium"
VOICE_DIR = Path.home() / ".local" / "share" / "piper-voices"

_whisper_models: dict[str, object] = {}
_model_lock = threading.Lock()


class TranscribeRequest(BaseModel):
    audio_base64: str  # WAV file bytes, base64-encoded
    model: Optional[str] = "base"  # tiny/base/small/medium/large — see openai-whisper docs


def _get_whisper_model(model_name: str):
    cached = _whisper_models.get(model_name)
    if cached is not None:
        return cached

    # Concurrent first requests must not load the same large model twice.
    with _model_lock:
        cached = _whisper_models.get(model_name)
        if cached is None:
            import whisper
            cached = whisper.load_model(model_name)
            _whisper_models[model_name] = cached
    return cached


def _transcribe_file(path: str, model_name: str) -> str:
    model = _get_whisper_model(model_name)
    result = model.transcribe(path, fp16=False)
    return (result.get("text") or "").strip()


def create_audio_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["audio"])

    @router.get("/audio/status")
    async def audio_status():
        whisper_installed = importlib.util.find_spec("whisper") is not None
        ffmpeg_installed = shutil.which("ffmpeg") is not None
        voice_path = VOICE_DIR / f"{DEFAULT_VOICE}.onnx"
        return {
            "transcription": {
                "available": whisper_installed and ffmpeg_installed,
                "whisperInstalled": whisper_installed,
                "ffmpegInstalled": ffmpeg_installed,
                "loadedModels": sorted(_whisper_models),
            },
            "speech": {
                "available": importlib.util.find_spec("piper") is not None and voice_path.exists(),
                "piperInstalled": importlib.util.find_spec("piper") is not None,
                "defaultVoice": DEFAULT_VOICE,
                "voiceDownloaded": voice_path.exists(),
            },
        }

    @router.post("/transcribe")
    async def transcribe(req: TranscribeRequest):
        # whisper.load_audio() shells out to ffmpeg unconditionally to decode
        # audio, regardless of input format — check up front so a missing
        # ffmpeg produces one clear message instead of a raw traceback.
        if shutil.which("ffmpeg") is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "ffmpeg is required for voice transcription but was not found. "
                    "Install it with `sudo apt-get install ffmpeg` (Linux), "
                    "`brew install ffmpeg` (macOS), or download it for Windows."
                ),
            )

        model_name = (req.model or "base").strip().lower()
        if model_name not in WHISPER_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported Whisper model '{model_name}'. Choose: {', '.join(sorted(WHISPER_MODELS))}",
            )

        try:
            audio_bytes = base64.b64decode(req.audio_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid audio data: {exc}") from exc

        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="No audio recorded - check your microphone.")

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name

            text = await asyncio.to_thread(_transcribe_file, tmp_path, model_name)
            return {"text": text}
        except HTTPException:
            raise
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail="Whisper is not installed. Install the openai-whisper package to enable voice input.",
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Transcription failed: {exc}") from exc
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    return router
