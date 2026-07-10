"""
Text-to-speech — POST /v1/speech.

Powers the web frontend's spoken replies (auto-played after a voice-input
turn, or on-demand via the play button on any assistant message). Uses
Piper (https://github.com/OHF-Voice/piper1-gpl) — a small, fully offline
neural TTS engine — instead of a cloud API, matching the rest of Dabba's
"local first" design (same reasoning as Whisper for speech-to-text in
audio_endpoints.py).

The voice model (~63MB ONNX file) is downloaded once via
`python3 -m piper.download_voices <voice>` and cached under
~/.local/share/piper-voices/ — see get_dabba_config_dir() sibling
convention, though Piper manages its own cache dir rather than dabba's.
"""
from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

DEFAULT_VOICE = "en_US-lessac-medium"
VOICE_DIR = Path.home() / ".local" / "share" / "piper-voices"

_voice_cache: dict[str, object] = {}


class SpeechRequest(BaseModel):
    text: str
    voice: Optional[str] = None


def _load_voice(voice_name: str):
    if voice_name in _voice_cache:
        return _voice_cache[voice_name]

    model_path = VOICE_DIR / f"{voice_name}.onnx"
    if not model_path.exists():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Voice '{voice_name}' not downloaded. Run: "
                f"python3 -m piper.download_voices {voice_name}"
            ),
        )

    from piper import PiperVoice
    voice = PiperVoice.load(str(model_path))
    _voice_cache[voice_name] = voice
    return voice


def create_tts_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["speech"])

    @router.post("/speech")
    async def synthesize_speech(req: SpeechRequest):
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text cannot be empty")
        # Piper has no hard limit, but a runaway-long reply would take a long
        # time to synthesize and produce an unreasonably large WAV — cap it
        # to something a spoken reply would plausibly need.
        if len(text) > 4000:
            text = text[:4000]

        import asyncio

        def _synthesize() -> bytes:
            voice = _load_voice(req.voice or DEFAULT_VOICE)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)
            return buffer.getvalue()

        try:
            # Piper's synthesis is CPU-bound and blocking — same reasoning as
            # the chat providers' asyncio.to_thread() calls, so one slow
            # synthesis can't stall the whole server's event loop.
            wav_bytes = await asyncio.to_thread(_synthesize)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Speech synthesis failed: {exc}")

        return Response(content=wav_bytes, media_type="audio/wav")

    return router
