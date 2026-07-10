"""
Vision encoder module for extracting visual features from images.

Wraps pre-trained vision models (SigLIP, ViT, or ResNet) to produce
patch-level embeddings suitable for downstream fusion with language
model hidden states. Provides automatic fallback from transformer-based
encoders to ResNet when ViT libraries are unavailable.
"""

import logging
import math
from typing import Optional, Tuple, Union

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

_HAS_TIMM = False
_HAS_TORCHVISION_MODELS = False

try:
    import timm
    _HAS_TIMM = True
except ImportError:
    timm = None
    logger.debug("timm not available; will try torchvision or fallback.")

try:
    from torchvision.models import (
        resnet50,
        ResNet50_Weights,
    )
    _HAS_TORCHVISION_MODELS = True
except Exception:
    resnet50 = None
    ResNet50_Weights = None


class ResNetEmbeddingWrapper(nn.Module):
    """
    Wrapper around a ResNet model to produce patch-style embeddings.

    Strips the classification head and pooling layer, returning
    spatial feature maps reshaped to (batch, num_patches, hidden_dim)
    to match the interface of ViT-based encoders.

    Args:
        hidden_size: Output feature dimension. Default 2048 (ResNet50).
        dropout: Dropout applied to output features. Default 0.0.
    """

    def __init__(self, hidden_size: int = 2048, dropout: float = 0.0):
        super().__init__()
        if not _HAS_TORCHVISION_MODELS:
            raise ImportError(
                "torchvision is required for the ResNet fallback encoder. "
                "Install it with: pip install torchvision"
            )

        resnet = resnet50(weights=ResNet50_Weights.DEFAULT)
        self.stem = nn.Sequential(
            resnet.conv1,
            resnet.bn1,
            resnet.relu,
            resnet.maxpool,
        )
        self.layer1 = resnet.layer1
        self.layer2 = resnet.layer2
        self.layer3 = resnet.layer3
        self.layer4 = resnet.layer4
        self.hidden_size = hidden_size

        self._patch_size = 16
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract patch embeddings from a batch of images.

        Args:
            x: Input tensor of shape (batch_size, 3, 224, 224).

        Returns:
            Tensor of shape (batch_size, num_patches, hidden_size).
        """
        x = self.stem(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        batch_size, channels, h, w = x.shape
        x = x.flatten(2).transpose(1, 2)
        x = self.dropout(x)
        return x


class VisionEncoder(nn.Module):
    """
    Vision encoder that extracts image patch embeddings for multimodal fusion.

    Supports multiple backends in order of preference:
      1. timm (preferred for SigLIP, ViT, and other transformer models)
      2. torchvision (ResNet fallback)
      3. A simple convolutional baseline (always available)

    The encoder always returns a tensor of shape
    (batch_size, num_patches, hidden_size).

    Args:
        model_name: Name of the pretrained vision model.
                    Examples: "google/siglip-base-patch16-224",
                              "vit_base_patch16_224",
                              "resnet50" (uses torchvision fallback).
                    Default "google/siglip-base-patch16-224".
        image_size: Input image size in pixels. Default 224.
        hidden_size: Output feature dimension. Default 768.
        device: Torch device for model parameters. Default "cpu".
        dtype: Torch dtype for computation. Default torch.float32.
        trainable: Whether to keep backbone parameters trainable. Default False.
        output_patches: If True, return raw patch embeddings. If False,
                        return a mean-pooled CLS-style vector (1, hidden).
                        Default True.
    """

    def __init__(
        self,
        model_name: str = "google/siglip-base-patch16-224",
        image_size: int = 224,
        hidden_size: int = 768,
        device: Union[str, torch.device] = "cpu",
        dtype: torch.dtype = torch.float32,
        trainable: bool = False,
        output_patches: bool = True,
    ):
        super().__init__()
        self.model_name = model_name
        self.image_size = image_size
        self.hidden_size = hidden_size
        self.device = torch.device(device)
        self.dtype = dtype
        self.output_patches = output_patches

        self._num_patches: int = 0
        self._encoder = self._build_encoder(trainable=trainable)

    def _build_encoder(self, trainable: bool) -> nn.Module:
        """
        Construct the vision encoder using the best available backend.

        Priority: timm ViT > timm other > torchvision ResNet > fallback.

        Args:
            trainable: Whether to set backbone parameters as trainable.

        Returns:
            A callable nn.Module that maps (B, 3, H, W) -> (B, N, D).
        """
        encoder = None
        patch_size = 16

        if _HAS_TIMM:
            try:
                model_kwargs = dict(
                    model_name=self.model_name,
                    pretrained=True,
                    num_classes=0,
                )
                if "vit" in self.model_name.lower() or "siglip" in self.model_name.lower():
                    model_kwargs["img_size"] = self.image_size

                model = timm.create_model(**model_kwargs)

                if hasattr(model, "patch_embed"):
                    patch_size = model.patch_embed.patch_size
                    if isinstance(patch_size, tuple):
                        patch_size = patch_size[0]
                    num_patches = model.patch_embed.num_patches
                elif hasattr(model, "num_features"):
                    num_patches = (self.image_size // patch_size) ** 2
                else:
                    num_patches = (self.image_size // patch_size) ** 2

                self._num_patches = num_patches

                if hasattr(model, "forward_features"):
                    encoder = model.forward_features
                else:
                    encoder = model.forward

                logger.info(
                    "Loaded timm encoder '%s' with %d patches, hidden=%d",
                    self.model_name, num_patches, self.hidden_size,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load timm model '%s': %s. Trying torchvision.",
                    self.model_name, exc,
                )

        if encoder is None and _HAS_TORCHVISION_MODELS:
            try:
                model = ResNetEmbeddingWrapper(hidden_size=self.hidden_size)
                self._num_patches = (self.image_size // 32) ** 2
                encoder = model.forward
                self.hidden_size = model.hidden_size
                logger.info(
                    "Loaded torchvision ResNet fallback encoder with %d patches",
                    self._num_patches,
                )
            except Exception as exc:
                logger.warning(
                    "torchvision fallback failed: %s", exc,
                )

        if encoder is None:
            encoder = self._build_fallback_encoder()
            self._num_patches = (self.image_size // 16) ** 2
            logger.info(
                "Using fallback CNN encoder with %d patches", self._num_patches,
            )

        module = nn.Module()
        module.forward = encoder

        if not trainable:
            for param in module.parameters():
                param.requires_grad = False

        return module

    def _build_fallback_encoder(self) -> nn.Module:
        """
        Create a simple convolutional encoder as last-resort fallback.

        Produces spatially-structured output compatible with the
        (batch, num_patches, hidden_size) interface.

        Returns:
            A callable nn.Module.
        """
        patch_size = 16
        num_patches = (self.image_size // patch_size) ** 2

        fallback = nn.Sequential(
            nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3, bias=False),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.Conv2d(128, self.hidden_size, kernel_size=3, stride=1, padding=1, bias=False),
            nn.BatchNorm2d(self.hidden_size),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((int(math.sqrt(num_patches)), int(math.sqrt(num_patches)))),
        )

        def forward_fn(x: torch.Tensor) -> torch.Tensor:
            x = fallback(x)
            batch_size, channels, h, w = x.shape
            return x.flatten(2).transpose(1, 2)

        return forward_fn

    @property
    def num_patches(self) -> int:
        """Number of image patches produced by the encoder."""
        return self._num_patches

    def forward(
        self,
        pixel_values: torch.Tensor,
        output_patches: Optional[bool] = None,
    ) -> torch.Tensor:
        """
        Extract image patch embeddings from preprocessed pixel values.

        Args:
            pixel_values: Tensor of shape (batch_size, 3, H, W) with
                          normalised image data (matching the preprocessing
                          used during training).
            output_patches: Override the default output_patches setting.
                            If True, return (B, N, D) patch embeddings.
                            If False, return (B, D) pooled embeddings.

        Returns:
            Patch embeddings of shape (batch_size, num_patches, hidden_size)
            or pooled embeddings of shape (batch_size, hidden_size).
        """
        output_patches = (
            output_patches if output_patches is not None
            else self.output_patches
        )

        pixel_values = pixel_values.to(device=self.device, dtype=self.dtype)
        features = self._encoder(pixel_values)

        if not output_patches and features.dim() == 3:
            features = features.mean(dim=1)

        return features

    def forward_with_pooler(
        self,
        pixel_values: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass returning both patch embeddings and pooled representation.

        Args:
            pixel_values: Tensor of shape (batch_size, 3, H, W).

        Returns:
            Tuple of (patch_embeddings, pooled_embedding).
        """
        patch_embeds = self.forward(pixel_values, output_patches=True)
        pooled = patch_embeds.mean(dim=1)
        return patch_embeds, pooled

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"model='{self.model_name}', "
            f"num_patches={self.num_patches}, "
            f"hidden_size={self.hidden_size}, "
            f"device={self.device})"
        )
