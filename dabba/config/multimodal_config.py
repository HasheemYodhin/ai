"""
Multimodal configuration for vision, audio, and video processing.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class MultimodalConfig:
    """
    Configuration for multimodal input processing: image encoding,
    video frame extraction, audio transcription, and vision-text projection.

    Controls all aspects of the multimodal pipeline from input preprocessing
    through vision encoding to cross-attentional fusion with the LLM.
    """

    # Vision
    vision_encoder: str = "google/siglip-base-patch16-224"
    image_size: int = 224
    image_mean: List[float] = field(default_factory=lambda: [0.5, 0.5, 0.5])
    image_std: List[float] = field(default_factory=lambda: [0.5, 0.5, 0.5])
    vision_hidden_size: int = 768
    vision_num_patches: int = 196
    vision_projection_dim: int = 768
    vision_device: str = "cpu"
    max_images_per_message: int = 10

    # Video
    video_frames_per_second: float = 1.0
    video_max_frames: int = 32
    video_min_frames: int = 4
    video_sampling: str = "uniform"  # "uniform", "keyframe"
    video_target_size: int = 224

    # Audio
    whisper_model_size: str = "small"  # tiny, base, small, medium, large
    audio_device: str = "cpu"
    audio_language: Optional[str] = None  # None = auto-detect
    audio_max_duration_seconds: float = 300.0

    # Projection (vision -> LLM embedding space)
    projection_input_dim: int = 768
    projection_output_dim: int = 768
    projection_hidden_dim: int = 2048

    # Cross-attention
    cross_attention_heads: int = 8
    cross_attention_dropout: float = 0.1

    # Text
    image_placeholder_token: str = "<image>"

    # Supported formats
    supported_image_formats: List[str] = field(
        default_factory=lambda: ["jpg", "jpeg", "png", "webp", "gif", "bmp"]
    )
    supported_video_formats: List[str] = field(
        default_factory=lambda: ["mp4", "avi", "mov", "mkv", "webm"]
    )
    supported_audio_formats: List[str] = field(
        default_factory=lambda: ["mp3", "wav", "flac", "ogg", "m4a"]
    )
    supported_document_formats: List[str] = field(
        default_factory=lambda: ["pdf", "txt", "md", "json", "csv"]
    )

    max_file_size_mb: int = 100
    temp_dir: str = "./tmp/uploads"

    def __post_init__(self):
        import os
        os.makedirs(self.temp_dir, exist_ok=True)
