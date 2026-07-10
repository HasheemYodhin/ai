"""
Image preprocessing pipeline for multimodal input.

Handles loading images from file paths, URLs, and raw bytes with
support for JPEG, PNG, WebP, GIF, and BMP formats. Provides
resizing, normalization, tensor conversion, and EXIF orientation
correction for both single-image and batched workflows.
"""

import io
import logging
from typing import List, Optional, Tuple, Union

import torch
import torch.nn as nn
try:
    import torchvision.transforms as T
    from torchvision.transforms import functional as F
    from torchvision.transforms import InterpolationMode
    _HAS_TORCHVISION = True
except Exception:
    _HAS_TORCHVISION = False
    T = None
    F = None
    InterpolationMode = None

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ExifTags
    HAS_PIL = True
except ImportError:
    Image = None
    ExifTags = None
    HAS_PIL = False
    logger.warning("PIL/Pillow not available. ImageProcessor will be non-functional.")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class ImageProcessor(nn.Module):
    """
    Load, preprocess, and batch images for multimodal models.

    Supports loading from:
      - Local file paths (str or pathlib.Path)
      - HTTP/HTTPS URLs
      - Raw byte buffers (bytes)
      - PIL Image objects

    Applies configurable preprocessing:
      1. EXIF orientation correction
      2. Resize to target dimensions
      3. Center crop (optional, enabled by default)
      4. Tensor conversion
      5. Normalisation with configurable mean/std

    Args:
        image_size: Target image size in pixels (square). Default 224.
        image_mean: Normalisation mean per channel. Default [0.5, 0.5, 0.5].
        image_std: Normalisation standard deviation per channel. Default [0.5, 0.5, 0.5].
        center_crop: Whether to apply a center crop after resize. Default True.
        crop_padding: Padding pixels to remove around edges via crop. Default 0.
        device: Torch device to place output tensors on. Default "cpu".
        dtype: Torch dtype for output tensors. Default torch.float32.
    """

    def __init__(
        self,
        image_size: int = 224,
        image_mean: Optional[List[float]] = None,
        image_std: Optional[List[float]] = None,
        center_crop: bool = True,
        crop_padding: int = 0,
        device: Union[str, torch.device] = "cpu",
        dtype: torch.dtype = torch.float32,
    ):
        super().__init__()
        if not _HAS_TORCHVISION:
            raise ImportError(
                "ImageProcessor requires torchvision. "
                "Install it with: pip install torchvision"
            )
        self.image_size = image_size
        self.center_crop = center_crop
        self.crop_padding = crop_padding
        self.device = torch.device(device)
        self.dtype = dtype

        mean = image_mean if image_mean is not None else [0.5, 0.5, 0.5]
        std = image_std if image_std is not None else [0.5, 0.5, 0.5]

        self.register_buffer("mean", torch.tensor(mean).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor(std).view(1, 3, 1, 1))

        transform_list = [
            T.Resize(
                (image_size, image_size),
                interpolation=InterpolationMode.BICUBIC,
                antialias=True,
            ),
        ]
        if center_crop and crop_padding > 0:
            transform_list.append(
                T.CenterCrop((image_size - 2 * crop_padding, image_size - 2 * crop_padding))
            )
        self._resize = T.Compose(transform_list)

    def _correct_exif_orientation(self, image: "Image.Image") -> "Image.Image":
        """
        Correct image orientation based on EXIF metadata.

        Many cameras and phones store orientation in EXIF rather than
        rotating the pixel data. This method applies the required
        rotation/flip so the image appears right-side-up.

        Args:
            image: A PIL Image with potential EXIF orientation metadata.

        Returns:
            Orientation-corrected PIL Image.
        """
        if not HAS_PIL:
            return image

        try:
            exif = image.getexif()
            orientation_key = next(
                (k for k in ExifTags.keys if k == "Orientation"), None
            )
            if orientation_key is None:
                for k, v in ExifTags.TAGS.items():
                    if v == "Orientation":
                        orientation_key = k
                        break

            if orientation_key is None or orientation_key not in exif:
                return image

            orientation = exif[orientation_key]
            rotations = {
                1: None,
                2: Image.FLIP_LEFT_RIGHT,
                3: Image.ROTATE_180,
                4: Image.FLIP_TOP_BOTTOM,
                5: Image.TRANSPOSE,
                6: Image.ROTATE_270,
                7: Image.TRANSVERSE,
                8: Image.ROTATE_90,
            }
            method = rotations.get(orientation)
            if method is not None:
                image = image.transpose(method)
        except Exception as exc:
            logger.debug("EXIF orientation correction failed: %s", exc)

        return image

    def load_image(
        self,
        source: Union[str, bytes, "Image.Image"],
    ) -> "Image.Image":
        """
        Load an image from a file path, URL, byte buffer, or PIL Image.

        Args:
            source: One of:
                - A string file path (local or http(s):// URL)
                - Raw bytes (e.g., from an HTTP response body)
                - A PIL Image instance (returned as-is after orientation fix)

        Returns:
            PIL Image in RGB mode.

        Raises:
            ValueError: If the source type is unsupported or loading fails.
            ImportError: If PIL is not installed.
        """
        if not HAS_PIL:
            raise ImportError(
                "PIL/Pillow is required for image processing. "
                "Install it with: pip install Pillow"
            )

        if isinstance(source, Image.Image):
            image = source
        elif isinstance(source, bytes):
            image = Image.open(io.BytesIO(source)).convert("RGB")
        elif isinstance(source, str):
            if source.startswith(("http://", "https://")):
                if not HAS_REQUESTS:
                    raise ImportError(
                        "requests is required to load images from URLs. "
                        "Install it with: pip install requests"
                    )
                response = requests.get(source, timeout=30)
                response.raise_for_status()
                image = Image.open(io.BytesIO(response.content)).convert("RGB")
            else:
                image = Image.open(source).convert("RGB")
        else:
            raise ValueError(
                f"Unsupported image source type: {type(source)}. "
                f"Expected str, bytes, or PIL.Image.Image."
            )

        return self._correct_exif_orientation(image)

    def preprocess(
        self,
        image: "Image.Image",
        return_tensor: bool = True,
    ) -> Union[torch.Tensor, "Image.Image"]:
        """
        Preprocess a single PIL Image: resize, crop, tensorise, normalise.

        Args:
            image: Input PIL Image in RGB mode.
            return_tensor: If True, return a normalised torch.Tensor.
                           If False, return the resized/cropped PIL Image.

        Returns:
            Preprocessed image as either a torch.Tensor of shape
            (1, 3, H, W) or a PIL Image.
        """
        image = self._resize(image)

        if not return_tensor:
            return image

        tensor = F.pil_to_tensor(image).unsqueeze(0).to(
            device=self.device, dtype=self.dtype
        )
        tensor = (tensor / 255.0 - self.mean) / self.std
        return tensor

    def preprocess_batch(
        self,
        images: List[Union[str, bytes, "Image.Image"]],
        return_tensor: bool = True,
    ) -> Union[torch.Tensor, List["Image.Image"]]:
        """
        Load and preprocess multiple images into a single batch tensor.

        Args:
            images: List of image sources (file paths, URLs, bytes, or PIL Images).
            return_tensor: If True, return a stacked torch.Tensor.
                           If False, return a list of preprocessed PIL Images.

        Returns:
            Batched tensor of shape (B, 3, H, W) or list of PIL Images.
        """
        processed = []
        for source in images:
            pil_image = self.load_image(source)
            processed.append(
                self.preprocess(pil_image, return_tensor=return_tensor)
            )

        if return_tensor:
            return torch.cat(processed, dim=0)
        return processed

    def forward(
        self,
        images: Union[
            Union[str, bytes, "Image.Image"],
            List[Union[str, bytes, "Image.Image"]],
        ],
    ) -> torch.Tensor:
        """
        Load and preprocess one or more images into a normalised batch tensor.

        Args:
            images: Single image source or list of image sources.

        Returns:
            Batch tensor of shape (B, 3, H, W) on the configured device.
        """
        if isinstance(images, (str, bytes, Image.Image)):
            return self.preprocess(self.load_image(images))
        return self.preprocess_batch(images)

    def load(
        self,
        source: Union[str, bytes, "Image.Image"],
    ) -> torch.Tensor:
        """Load an image from source and return as a preprocessed tensor."""
        pil = self.load_image(source)
        return self.preprocess(pil, return_tensor=True).squeeze(0)

    def image_to_tensor(
        self,
        source: Union[str, bytes, "Image.Image"],
    ) -> torch.Tensor:
        """Load an image and convert it to a tensor without normalisation."""
        pil = self.load_image(source)
        resized = self._resize(pil)
        tensor = F.pil_to_tensor(resized).to(device=self.device, dtype=self.dtype)
        return tensor / 255.0

    def resize(
        self,
        image: torch.Tensor,
        size: Tuple[int, int],
    ) -> torch.Tensor:
        """Resize a CHW tensor to (C, H, W) with given size."""
        import torch.nn.functional as _F
        h, w = size
        return _F.interpolate(image.unsqueeze(0), size=(h, w), mode="bilinear", align_corners=False).squeeze(0)

    def normalize(
        self,
        image: torch.Tensor,
    ) -> torch.Tensor:
        """Apply mean/std normalisation to a CHW tensor."""
        mean = self.mean.squeeze(0)  # (3,1,1)
        std = self.std.squeeze(0)
        return (image - mean) / std

    def to_pil(self, tensor: torch.Tensor) -> "Image.Image":
        """
        Convert a normalised tensor back to a PIL Image for inspection/saving.

        Args:
            tensor: Tensor of shape (1, 3, H, W) as produced by preprocess().

        Returns:
            PIL Image in RGB mode.
        """
        if not HAS_PIL:
            raise ImportError("PIL/Pillow is required for tensor-to-image conversion.")

        tensor = tensor.detach().cpu().float()
        tensor = tensor * self.std + self.mean
        tensor = tensor.clamp(0, 1)
        tensor = tensor.squeeze(0)
        arr = (tensor.permute(1, 2, 0).numpy() * 255).astype("uint8")
        return Image.fromarray(arr)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"image_size={self.image_size}, "
            f"center_crop={self.center_crop}, "
            f"device={self.device})"
        )
