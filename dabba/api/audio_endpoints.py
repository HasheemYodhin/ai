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

import base64
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

_whisper_model = None


class TranscribeRequest(BaseModel):
    audio_base64: str  # WAV file bytes, base64-encoded
    model: Optional[str] = "base"  # tiny/base/small/medium/large — see openai-whisper docs


def _get_whisper_model(model_name: str):
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model(model_name)
    return _whisper_model


def create_audio_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/transcribe")
    async def transcribe(req: TranscribeRequest):
        # whisper.load_audio() shells out to ffmpeg unconditionally to decode
        # audio, regardless of input format — check up front so a missing
        # ffmpeg produces one clear message instead of a raw traceback.
        if shutil.which("ffmpeg") is None:
            return {
                "error": (
                    "ffmpeg is required for voice transcription but was not found. "
                    "Install it with `sudo apt-get install ffmpeg` (Linux), "
                    "`brew install ffmpeg` (macOS), or download it for Windows."
                )
            }

        try:
            audio_bytes = base64.b64decode(req.audio_base64)
        except Exception as exc:
            return {"error": f"Invalid audio data: {exc}"}

        if len(audio_bytes) == 0:
            return {"error": "No audio recorded — check your microphone."}

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name

            model = _get_whisper_model(req.model or "base")
            result = model.transcribe(tmp_path, fp16=False)
            return {"text": (result.get("text") or "").strip()}
        except Exception as exc:
            return {"error": f"Transcription failed: {exc}"}
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    return router
