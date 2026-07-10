"""
Audio transcription module using OpenAI Whisper.

Supports common audio formats (MP3, WAV, FLAC, OGG, M4A) with
configurable model sizes, language detection/filtering, and duration
limits. Safe fallback when whisper is not installed.
"""

import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

_HAS_WHISPER = False
try:
    import whisper
    _HAS_WHISPER = True
except ImportError:
    whisper = None
    logger.debug("openai-whisper not available. Audio transcription disabled.")

_HAS_TORCH = False
try:
    import torch
    _HAS_TORCH = True
except ImportError:
    torch = None

_HAS_AUDIOCLIP = False
try:
    import audioop
    _HAS_AUDIOCLIP = True
except ImportError:
    audioop = None

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    AudioSegment = None
    HAS_PYDUB = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False


class AudioProcessor:
    """
    Transcribe speech from audio files using OpenAI Whisper.

    Supports MP3, WAV, FLAC, OGG, and M4A formats. Automatically
    detects the language of the audio (or can be constrained to a
    specific language). Truncates audio exceeding the configured
    maximum duration.

    Args:
        model_size: Whisper model size. One of "tiny", "base", "small",
                   "medium", "large". Default "small".
        device: Torch device for inference. Default "cpu".
        language: ISO 639-1 language code to constrain transcription
                  (e.g., "en", "fr"). None enables auto-detection. Default None.
        max_duration_seconds: Maximum audio duration to process in seconds.
                              Longer files are truncated. Default 300.0
                              (5 minutes).
        compute_dtype: Torch dtype for inference. Default torch.float16
                       if CUDA is available, else torch.float32.
    """

    VALID_MODEL_SIZES = ("tiny", "base", "small", "medium", "large")

    def __init__(
        self,
        model_size: str = "small",
        device: Optional[Union[str, "torch.device"]] = None,
        language: Optional[str] = None,
        max_duration_seconds: float = 300.0,
        compute_dtype: Optional["torch.dtype"] = None,
    ):
        if model_size not in self.VALID_MODEL_SIZES:
            raise ValueError(
                f"model_size must be one of {self.VALID_MODEL_SIZES}, "
                f"got '{model_size}'"
            )
        self.model_size = model_size
        self.language = language
        self.max_duration_seconds = max_duration_seconds
        self._model = None

        if device is None:
            if _HAS_TORCH:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self.device = "cpu"
        else:
            self.device = str(device)

        if compute_dtype is None and _HAS_TORCH:
            self.compute_dtype = (
                torch.float16 if self.device.startswith("cuda") else torch.float32
            )
        elif compute_dtype is not None:
            self.compute_dtype = compute_dtype
        else:
            self.compute_dtype = None

    def _load_model(self):
        """
        Load the Whisper model on first use (lazy initialisation).
        """
        if self._model is not None:
            return

        if not _HAS_WHISPER:
            raise ImportError(
                "openai-whisper is required for audio transcription. "
                "Install it with: pip install openai-whisper"
            )

        logger.info(
            "Loading Whisper model '%s' on %s...", self.model_size, self.device,
        )
        self._model = whisper.load_model(self.model_size, device=self.device)
        self._model.eval()
        logger.info("Whisper model loaded successfully.")

    def _load_audio_to_array(
        self, source: Union[str, bytes, Path]
    ) -> "np.ndarray":
        """
        Load an audio file and convert to a float32 numpy array.

        Supports raw file paths, pathlib Paths, and byte buffers.
        Uses pydub for format conversion when ffmpeg is available,
        falling back to librosa or direct whisper loading.

        Args:
            source: File path, pathlib Path, or raw bytes.

        Returns:
            Audio signal as a 1-D float32 numpy array (sampled at 16 kHz).
        """
        if isinstance(source, Path):
            source = str(source)

        if isinstance(source, str):
            if not os.path.isfile(source):
                raise FileNotFoundError(f"Audio file not found: {source}")
            extension = os.path.splitext(source)[1].lower()
            if extension in (".wav",):
                return self._decode_wav(source)
            if HAS_PYDUB:
                return self._decode_pydub(source)
            if _HAS_WHISPER:
                return whisper.load_audio(source)
            raise RuntimeError(
                "Cannot decode audio. Install pydub+ffmpeg or librosa."
            )

        if isinstance(source, bytes):
            if HAS_PYDUB:
                return self._decode_pydub_bytes(source)
            if _HAS_WHISPER:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(source)
                    tmp_path = tmp.name
                try:
                    return whisper.load_audio(tmp_path)
                finally:
                    os.unlink(tmp_path)
            raise RuntimeError(
                "Cannot decode audio bytes. Install pydub+ffmpeg."
            )

        raise ValueError(f"Unsupported audio source type: {type(source)}")

    def _decode_wav(self, path: str) -> "np.ndarray":
        """Decode a WAV file directly using scipy or torchaudio."""
        if not HAS_NUMPY:
            raise ImportError("numpy is required for audio processing.")

        try:
            import scipy.io.wavfile as wavfile
            sample_rate, audio = wavfile.read(path)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max
            return self._resample(audio, sample_rate, 16000)
        except ImportError:
            pass

        try:
            import torchaudio
            audio_tensor, sample_rate = torchaudio.load(path)
            if audio_tensor.shape[0] > 1:
                audio_tensor = audio_tensor.mean(dim=0, keepdim=True)
            audio = audio_tensor.squeeze(0).numpy().astype(np.float32)
            return self._resample(audio, int(sample_rate), 16000)
        except ImportError:
            pass

        if _HAS_WHISPER:
            return whisper.load_audio(path)

        raise ImportError("Install scipy or torchaudio for WAV decoding.")

    def _resample(
        self, audio: "np.ndarray", orig_sr: int, target_sr: int
    ) -> "np.ndarray":
        """Resample audio array from orig_sr to target_sr."""
        if orig_sr == target_sr:
            return audio
        if not HAS_NUMPY:
            return audio

        try:
            import scipy.signal as signal
            ratio = target_sr / orig_sr
            new_len = int(len(audio) * ratio)
            resampled = signal.resample(audio, new_len)
            return resampled.astype(np.float32)
        except ImportError:
            pass

        if _HAS_WHISPER:
            try:
                import whisper.audio as wa
                import numpy as np
                result = np.zeros(int(len(audio) * target_sr / orig_sr), dtype=np.float32)
                wa.pad_or_trim(audio, len(result))
                return result
            except Exception:
                pass

        logger.warning("Resampling not available; returning original sample rate.")
        return audio

    def _decode_pydub(self, path: str) -> "np.ndarray":
        """Decode audio via pydub and resample to 16 kHz mono."""
        if not HAS_PYDUB:
            raise ImportError("pydub is required for non-WAV audio decoding.")
        if not HAS_NUMPY:
            raise ImportError("numpy is required for audio processing.")

        segment = AudioSegment.from_file(path)
        segment = segment.set_channels(1).set_frame_rate(16000)
        samples = np.array(segment.get_array_of_samples(), dtype=np.float32)
        samples /= 1 << (8 * segment.sample_width - 1)
        return samples

    def _decode_pydub_bytes(self, data: bytes) -> "np.ndarray":
        """Decode audio from raw bytes via pydub."""
        if not HAS_PYDUB:
            raise ImportError("pydub is required for byte-array audio decoding.")
        if not HAS_NUMPY:
            raise ImportError("numpy is required for audio processing.")

        segment = AudioSegment.from_file(io.BytesIO(data))
        segment = segment.set_channels(1).set_frame_rate(16000)
        samples = np.array(segment.get_array_of_samples(), dtype=np.float32)
        samples /= 1 << (8 * segment.sample_width - 1)
        return samples

    def _truncate_audio(
        self, audio: "np.ndarray", sample_rate: int = 16000
    ) -> "np.ndarray":
        """
        Truncate audio to the configured maximum duration.
        """
        max_samples = int(self.max_duration_seconds * sample_rate)
        if len(audio) > max_samples:
            logger.warning(
                "Audio length (%.1f s) exceeds max duration (%.1f s). Truncating.",
                len(audio) / sample_rate, self.max_duration_seconds,
            )
            audio = audio[:max_samples]
        return audio

    @property
    def sample_rate(self) -> int:
        """Default sample rate used by the Whisper pipeline (16 kHz)."""
        return 16000

    @property
    def model_name(self) -> str:
        """Return the Whisper model size identifier."""
        return f"whisper-{self.model_size}"

    def load(self, source) -> "torch.Tensor":
        """Load audio from *source* and return a 1-D float32 tensor."""
        if not _HAS_TORCH:
            raise ImportError("torch is required.")
        import numpy as np
        audio_array = self._load_audio_to_array(source)
        return torch.tensor(audio_array, dtype=torch.float32)

    def preprocess(self, audio: "torch.Tensor") -> "torch.Tensor":
        """Convert a raw waveform tensor to a log-mel spectrogram stub.

        Returns shape (1, 80, T) as a placeholder (Whisper mel features).
        """
        if not _HAS_TORCH:
            raise ImportError("torch is required.")
        n_mels, hop = 80, 160
        n_frames = max(1, audio.shape[-1] // hop)
        return torch.zeros(1, n_mels, n_frames)

    def extract_features(self, audio: "torch.Tensor") -> "torch.Tensor":
        """Return Whisper-style encoder features (1, T, 1280) stub."""
        if not _HAS_TORCH:
            raise ImportError("torch is required.")
        hop = 160
        n_frames = max(1, audio.shape[-1] // hop // 2)
        return torch.zeros(1, n_frames, 1280)

    def get_duration(self, audio: "torch.Tensor") -> float:
        """Return duration in seconds given a waveform tensor."""
        return float(audio.shape[-1]) / self.sample_rate

    def resample(self, audio: "torch.Tensor", orig_sr: int, target_sr: int) -> "torch.Tensor":
        """Resample *audio* tensor from *orig_sr* to *target_sr*."""
        if not _HAS_TORCH:
            raise ImportError("torch is required.")
        if orig_sr == target_sr:
            return audio
        ratio = target_sr / orig_sr
        new_len = max(1, int(audio.shape[-1] * ratio))
        return torch.nn.functional.interpolate(
            audio.float().view(1, 1, -1), size=new_len, mode="linear", align_corners=False
        ).view(-1)

    def transcribe(
        self,
        source: Union[str, bytes, Path],
        language: Optional[str] = None,
        **whisper_kwargs,
    ) -> str:
        """
        Transcribe an audio file to text.

        Args:
            source: File path, pathlib.Path, or raw bytes of audio data.
            language: Optional ISO 639-1 language code to constrain
                      transcription. If None, uses the instance-level
                      language setting (which may also be None for
                      auto-detection).
            **whisper_kwargs: Additional keyword arguments forwarded to
                              whisper's transcribe() method (e.g.,
                              temperature, compression_ratio_threshold,
                              no_speech_threshold, condition_on_previous_text).

        Returns:
            Transcribed text string.

        Raises:
            FileNotFoundError: If the source is a path and does not exist.
            ImportError: If openai-whisper is not installed.
            RuntimeError: If transcription fails.
        """
        self._load_model()

        lang = language or self.language

        audio = self._load_audio_to_array(source)
        audio = self._truncate_audio(audio)

        transcribe_kwargs = dict(
            audio=audio,
            language=lang,
            task="transcribe",
            verbose=False,
        )
        transcribe_kwargs.update(whisper_kwargs)

        try:
            result = self._model.transcribe(**transcribe_kwargs)
        except Exception as exc:
            raise RuntimeError(f"Whisper transcription failed: {exc}") from exc

        text = result.get("text", "").strip()
        detected_lang = result.get("language", "unknown")

        if detected_lang != "unknown":
            logger.debug(
                "Transcribed %s audio: %d chars (%.1f s)",
                detected_lang, len(text), len(audio) / 16000,
            )

        return text

    def transcribe_batch(
        self,
        sources: list,
        language: Optional[str] = None,
        **whisper_kwargs,
    ) -> list:
        """
        Transcribe multiple audio files.

        Args:
            sources: List of file paths, pathlib Paths, or byte buffers.
            language: Optional language code override.
            **whisper_kwargs: Additional whisper transcription arguments.

        Returns:
            List of transcribed text strings in the same order as inputs.
        """
        return [
            self.transcribe(s, language=language, **whisper_kwargs)
            for s in sources
        ]

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"model='{self.model_size}', "
            f"device='{self.device}', "
            f"lang={self.language})"
        )
