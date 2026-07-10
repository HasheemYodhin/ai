"""
Multimodal processing pipeline for vision, video, and audio inputs.

Provides a full stack for multimodal understanding:
  - ImageProcessor: Load, preprocess, and batch images from diverse sources
  - VisionEncoder: Extract visual features using SigLIP/ViT (with fallback)
  - VideoProcessor: Sample frames from video files uniformly or via keyframes
  - AudioProcessor: Transcribe speech to text via Whisper
  - MultimodalProjection: Project vision embeddings into LLM space
  - MultimodalCrossAttention: Cross-attend vision features with text features
  - MultimodalLLM: Full multimodal model combining all components
"""

from dabba.multimodal.image_processor import ImageProcessor
from dabba.multimodal.vision_encoder import VisionEncoder
from dabba.multimodal.video_processor import VideoProcessor
from dabba.multimodal.audio_processor import AudioProcessor
from dabba.multimodal.multimodal_projection import MultimodalProjection
from dabba.multimodal.multimodal_attention import MultimodalCrossAttention
from dabba.multimodal.multimodal_llm import MultimodalLLM

MultimodalProcessor = MultimodalLLM

__all__ = [
    "ImageProcessor",
    "VisionEncoder",
    "VideoProcessor",
    "AudioProcessor",
    "MultimodalProjection",
    "MultimodalCrossAttention",
    "MultimodalLLM",
    "MultimodalProcessor",
]
