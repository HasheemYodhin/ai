"""
Video frame extraction module for multimodal input processing.

Supports uniform frame sampling and keyframe extraction from common
video formats (MP4, AVI, MOV, MKV, WebM). Uses OpenCV as the primary
backend with a safe fallback when cv2 is unavailable.
"""

import logging
import os
import tempfile
from typing import List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

_HAS_CV2 = False
try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    logger.debug("OpenCV (cv2) not available. Video processing disabled.")

_HAS_PIL = False
try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    Image = None

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False


class VideoProcessor:
    """
    Extract frames from video files for multimodal processing.

    Supports both uniform frame sampling (evenly spaced throughout the
    video duration) and keyframe-based extraction (I-frames). Handles
    MP4, AVI, MOV, MKV, and WebM formats via OpenCV.

    Args:
        fps: Frames per second to extract (uniform sampling). Default 1.0.
        max_frames: Maximum number of frames to return. Default 32.
        min_frames: Minimum number of frames required. Default 4.
        sampling: Sampling strategy: "uniform" or "keyframe". Default "uniform".
        target_size: Resize extracted frames to this size (square). Default 224.
        device: Device for output tensors. Default "cpu".
        dtype: Torch dtype for output tensors. Default torch.float32.
    """

    def __init__(
        self,
        fps: float = 1.0,
        max_frames: int = 32,
        min_frames: int = 4,
        sampling: str = "uniform",
        target_size: int = 224,
        device: Union[str, "torch.device"] = "cpu",
        dtype: "torch.dtype" = None,  # noqa: F821
    ):
        self.fps = fps
        self.max_frames = max_frames
        self.min_frames = min_frames
        self.sampling = sampling
        self.target_size = target_size
        self.device = device

        if dtype is None:
            import torch
            dtype = torch.float32
        self.dtype = dtype

        if sampling not in ("uniform", "keyframe"):
            raise ValueError(
                f"sampling must be 'uniform' or 'keyframe', got '{sampling}'"
            )

    def _probe_video(self, video_path: str) -> Tuple[float, int, int]:
        """
        Probe a video file to extract metadata.

        Args:
            video_path: Path to the video file.

        Returns:
            Tuple of (duration_seconds, total_frame_count, fps_native).
        """
        if not _HAS_CV2:
            raise ImportError("OpenCV (cv2) is required for video processing.")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Unable to open video file: {video_path}")

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps_native = cap.get(cv2.CAP_PROP_FPS)
            duration = total_frames / fps_native if fps_native > 0 else 0.0
        finally:
            cap.release()

        return duration, total_frames, fps_native

    def _extract_frames_uniform(
        self, video_path: str,
    ) -> List["np.ndarray"]:
        """
        Extract frames evenly spaced throughout the video duration.

        Args:
            video_path: Path to the video file.

        Returns:
            List of numpy arrays (H, W, 3) in RGB order.
        """
        duration, total_frames, fps_native = self._probe_video(video_path)

        if duration <= 0 or total_frames <= 0:
            logger.warning("Video '%s' appears empty or corrupt.", video_path)
            return []

        target_count = max(
            self.min_frames,
            min(self.max_frames, int(duration * self.fps)),
        )

        if target_count >= total_frames:
            step = 1
        else:
            step = max(1, total_frames // target_count)

        cap = cv2.VideoCapture(video_path)
        frames: List["np.ndarray"] = []

        try:
            for i in range(0, total_frames, step):
                if len(frames) >= self.max_frames:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if ret:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frames.append(rgb)
        finally:
            cap.release()

        if len(frames) < self.min_frames and total_frames > 0:
            logger.warning(
                "Only %d frames extracted from '%s' (min %d required).",
                len(frames), video_path, self.min_frames,
            )

        return frames

    def _extract_frames_keyframe(
        self, video_path: str,
    ) -> List["np.ndarray"]:
        """
        Extract keyframes (I-frames) from the video.

        Uses OpenCV's property flag to seek to keyframes. Falls back
        to uniform sampling if keyframe extraction is not supported.

        Args:
            video_path: Path to the video file.

        Returns:
            List of numpy arrays (H, W, 3) in RGB order.
        """
        if not _HAS_CV2:
            raise ImportError("OpenCV (cv2) is required for video processing.")

        cap = cv2.VideoCapture(video_path)
        frames: List["np.ndarray"] = []
        frame_count = 0

        try:
            while len(frames) < self.max_frames:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_count += 1
                is_keyframe = False
                try:
                    flag = cap.get(cv2.CAP_PROP_POS_FRAMES)
                    if flag is not None and frame_count == int(flag):
                        is_keyframe = True
                except Exception:
                    pass

                if is_keyframe or frame_count == 1:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frames.append(rgb)
        finally:
            cap.release()

        if len(frames) < self.min_frames and frame_count > 0:
            logger.warning(
                "Only %d keyframes found in '%s'. Falling back to uniform sampling.",
                len(frames), video_path,
            )
            return self._extract_frames_uniform(video_path)

        return frames

    def _resize_frame(self, frame: "np.ndarray") -> "np.ndarray":
        """
        Resize a single frame to the target size using cv2.
        """
        if _HAS_CV2:
            return cv2.resize(
                frame, (self.target_size, self.target_size),
                interpolation=cv2.INTER_LINEAR,
            )
        if HAS_NUMPY:
            from PIL import Image
            pil_img = Image.fromarray(frame)
            pil_img = pil_img.resize(
                (self.target_size, self.target_size), Image.BILINEAR
            )
            return np.array(pil_img)
        return frame

    def extract_frames(
        self,
        video_path: str,
        return_tensors: bool = False,
    ) -> Union[List["Image.Image"], "torch.Tensor"]:
        """
        Extract frames from a video file.

        Args:
            video_path: Path to the video file. Supports mp4, avi, mov, mkv, webm.
            return_tensors: If True, return a batched torch.Tensor of shape
                           (num_frames, 3, H, W). If False, return a list of PIL Images.

        Returns:
            Extracted frames as either a tensor or a list of PIL Images.

        Raises:
            FileNotFoundError: If the video file does not exist.
            ImportError: If OpenCV is not installed.
            ValueError: If the video cannot be opened or decoded.
        """
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        if not _HAS_CV2:
            raise ImportError(
                "OpenCV (cv2) is required for video processing. "
                "Install it with: pip install opencv-python"
            )

        if self.sampling == "uniform":
            raw_frames = self._extract_frames_uniform(video_path)
        else:
            raw_frames = self._extract_frames_keyframe(video_path)

        if not raw_frames:
            logger.warning("No frames extracted from '%s'.", video_path)
            if return_tensors:
                import torch
                return torch.zeros(0, 3, self.target_size, self.target_size)
            return []

        resized = [self._resize_frame(f) for f in raw_frames]

        if not return_tensors:
            if not _HAS_PIL:
                raise ImportError("PIL/Pillow is required to return PIL Images.")
            return [Image.fromarray(f) for f in resized]

        import torch
        tensor = torch.from_numpy(np.stack(resized, axis=0)).float()
        tensor = tensor.permute(0, 3, 1, 2).to(device=self.device, dtype=self.dtype)
        tensor = tensor / 255.0
        return tensor

    def extract_frames_batch(
        self,
        video_paths: List[str],
        return_tensors: bool = False,
    ) -> List[Union[List["Image.Image"], "torch.Tensor"]]:
        """
        Extract frames from multiple video files.

        Args:
            video_paths: List of paths to video files.
            return_tensors: If True, return tensors; else PIL Image lists.

        Returns:
            List of results, one per input video.
        """
        return [
            self.extract_frames(p, return_tensors=return_tensors)
            for p in video_paths
        ]

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"fps={self.fps}, max_frames={self.max_frames}, "
            f"sampling='{self.sampling}', target_size={self.target_size})"
        )
