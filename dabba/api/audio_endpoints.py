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
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

WHISPER_MODELS = {"tiny", "base", "small", "medium", "large"}

# Folders checked for ffmpeg when it is not on PATH. A server started from a
# service, desktop launcher or IDE often has a shorter PATH than a terminal.
_FFMPEG_FALLBACK_DIRS = (
    "/usr/local/bin",
    "/usr/bin",
    "/opt/homebrew/bin",
    "/opt/local/bin",
    "~/.local/bin",
    "~/bin",
)
_ffmpeg_alias_dir: Optional[str] = None

# Hosted transcription is OFF unless the server owner turns it on. It sends the
# recording to OpenAI, so it is never a silent fallback.
HOSTED_TRANSCRIPTION_ENV = "DABBA_HOSTED_TRANSCRIPTION"
HOSTED_TRANSCRIBE_MODEL_ENV = "DABBA_TRANSCRIBE_MODEL"
MAX_HOSTED_AUDIO_BYTES = 24 * 1024 * 1024  # the hosted API accepts up to 25 MB


def hosted_transcription_enabled() -> bool:
    """True when the owner set DABBA_HOSTED_TRANSCRIPTION=openai."""
    return os.environ.get(HOSTED_TRANSCRIPTION_ENV, "").strip().lower() == "openai"


def _hosted_api_key() -> str:
    """The OpenAI key saved in the app or set in the host's environment, or ''."""
    from dabba.api.agent_endpoints import _get_agent_proxy

    key, _source = _get_agent_proxy()._get_provider_registry().resolve_api_key(
        "gpt-transcribe"
    )
    return key


def _audio_suffix(data: bytes) -> str:
    """A file extension for the recording, so the hosted service knows its format."""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"
    if data[4:8] == b"ftyp":
        return ".m4a"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    return ".webm"  # what browsers record by default


def _transcribe_hosted(audio: bytes, api_key: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=90.0, max_retries=1)
    result = client.audio.transcriptions.create(
        model=os.environ.get(HOSTED_TRANSCRIBE_MODEL_ENV, "").strip() or "whisper-1",
        file=(f"recording{_audio_suffix(audio)}", audio),
    )
    return (getattr(result, "text", "") or "").strip()


def _is_executable_file(path) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_ffmpeg() -> Optional[str]:
    """Locate an ffmpeg executable, or None.

    Order: ``DABBA_FFMPEG`` (explicit path), PATH, the static build that the
    ``imageio-ffmpeg`` package ships, then common install folders.
    """
    explicit = os.environ.get("DABBA_FFMPEG", "").strip()
    if explicit and _is_executable_file(explicit):
        return explicit
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg  # optional; bundles a static ffmpeg binary

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and _is_executable_file(bundled):
            return bundled
    except Exception:  # noqa: BLE001 - package missing or no bundled binary
        pass
    for folder in _FFMPEG_FALLBACK_DIRS:
        candidate = Path(folder).expanduser() / "ffmpeg"
        if _is_executable_file(candidate):
            return str(candidate)
    return None


def ensure_ffmpeg_on_path() -> Optional[str]:
    """Find ffmpeg and make the plain name ``ffmpeg`` resolve for whisper.

    whisper decodes audio by running ``ffmpeg`` by name, so a binary found
    off PATH (or named differently, like imageio's) is exposed under that name
    in a private temp folder that is added to PATH. Returns the executable
    path, or None when no ffmpeg exists.
    """
    global _ffmpeg_alias_dir
    exe = find_ffmpeg()
    if exe is None:
        return None
    if shutil.which("ffmpeg"):
        return exe
    if _ffmpeg_alias_dir is None:
        # mkdtemp is private (0700), so no other user can plant a binary here.
        _ffmpeg_alias_dir = tempfile.mkdtemp(prefix="dabba-ffmpeg-")
    link = Path(_ffmpeg_alias_dir) / "ffmpeg"
    if not link.exists():
        try:
            link.symlink_to(exe)
        except OSError:
            return exe  # cannot alias; the caller may still run it by full path
    os.environ["PATH"] = _ffmpeg_alias_dir + os.pathsep + os.environ.get("PATH", "")
    return exe
DEFAULT_VOICE = "en_US-lessac-medium"
VOICE_DIR = Path.home() / ".local" / "share" / "piper-voices"

_whisper_models: dict[str, object] = {}
_model_lock = threading.Lock()


class TranscribeRequest(BaseModel):
    audio_base64: str  # WAV file bytes, base64-encoded
    model: Optional[str] = (
        "base"  # tiny/base/small/medium/large — see openai-whisper docs
    )


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
        ffmpeg_installed = ensure_ffmpeg_on_path() is not None
        voice_path = VOICE_DIR / f"{DEFAULT_VOICE}.onnx"
        hosted_enabled = hosted_transcription_enabled()
        try:
            hosted_ready = hosted_enabled and bool(_hosted_api_key())
        except Exception:  # noqa: BLE001 - no usable key or provider setup
            hosted_ready = False
        return {
            "transcription": {
                "available": (whisper_installed and ffmpeg_installed) or hosted_ready,
                "whisperInstalled": whisper_installed,
                "ffmpegInstalled": ffmpeg_installed,
                "hostedEnabled": hosted_enabled,
                "hostedReady": hosted_ready,
                "loadedModels": sorted(_whisper_models),
            },
            "speech": {
                "available": importlib.util.find_spec("piper") is not None
                and voice_path.exists(),
                "piperInstalled": importlib.util.find_spec("piper") is not None,
                "defaultVoice": DEFAULT_VOICE,
                "voiceDownloaded": voice_path.exists(),
            },
        }

    async def transcribe_hosted(req: TranscribeRequest):
        try:
            audio = base64.b64decode(req.audio_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid audio data: {exc}") from exc
        if not audio:
            raise HTTPException(status_code=400, detail="No audio recorded - check your microphone.")
        if len(audio) > MAX_HOSTED_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="That recording is too long. Try a shorter one.")
        try:
            api_key = _hosted_api_key()
        except Exception:  # noqa: BLE001
            api_key = ""
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="Hosted transcription is turned on but no OpenAI API key is available.",
            )
        try:
            return {"text": await asyncio.to_thread(_transcribe_hosted, audio, api_key)}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}") from exc

    @router.post("/transcribe")
    async def transcribe(req: TranscribeRequest):
        whisper_installed = importlib.util.find_spec("whisper") is not None
        ffmpeg_found = ensure_ffmpeg_on_path() is not None
        # Only when the owner opted in, and only if this machine can't transcribe itself.
        if hosted_transcription_enabled() and not (whisper_installed and ffmpeg_found):
            return await transcribe_hosted(req)

        # whisper.load_audio() shells out to ffmpeg unconditionally to decode
        # audio, regardless of input format — check up front so a missing
        # ffmpeg produces one clear message instead of a raw traceback.
        if not ffmpeg_found:
            raise HTTPException(
                status_code=503,
                detail=(
                    "ffmpeg is required for voice transcription but was not found. "
                    "Install it with `sudo apt-get install ffmpeg` (Linux), "
                    "`brew install ffmpeg` (macOS), or download it for Windows, "
                    "or set DABBA_FFMPEG to the full path of an ffmpeg binary."
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
            raise HTTPException(
                status_code=400, detail=f"Invalid audio data: {exc}"
            ) from exc

        if len(audio_bytes) == 0:
            raise HTTPException(
                status_code=400, detail="No audio recorded - check your microphone."
            )

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
            raise HTTPException(
                status_code=422, detail=f"Transcription failed: {exc}"
            ) from exc
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    return router
