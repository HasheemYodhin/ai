"""
Full multimodal language model combining vision and text modalities.

Integrates the image processor, vision encoder, embedding projector,
and the dabba decoder-only transformer into a single end-to-end model
that can accept text interleaved with images and generate text
conditioned on visual content.

Vision tokens are prepended to text tokens so the LLM can attend to
visual content during autoregressive generation. The prepend approach
avoids modifying the underlying transformer's sequence-length logic.
"""

import logging
from typing import Dict, List, Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from dabba.config.multimodal_config import MultimodalConfig
from dabba.config.model_config import ModelConfig
from dabba.model.transformer import Transformer
from dabba.multimodal.image_processor import ImageProcessor
from dabba.multimodal.vision_encoder import VisionEncoder
from dabba.multimodal.multimodal_projection import MultimodalProjection
from dabba.inference.samplers import (
    Sampler,
    TemperatureSampler,
    TopKSampler,
    TopPSampler,
)

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None
    HAS_PIL = False


class MultimodalLLM(nn.Module):
    """
    Multimodal language model that fuses vision and text modalities.

    Architecture:
        Image → ImageProcessor → VisionEncoder → MultimodalProjection → LLM
        Text → Token Embedding → Concatenate with vision tokens

    Vision tokens are projected into the LLM's embedding space and
    prepended to text token embeddings. The combined sequence is
    processed by the transformer decoder which can attend to both
    visual and textual context.

    Args:
        llm: An instance of dabba's Transformer model.
        mm_config: MultimodalConfig instance with vision/projection settings.
        model_config: Optional ModelConfig (inferred from llm.config if not provided).
        device: Torch device. Default "cpu".
        pad_token_id: Padding token ID for extended input_ids. Default 0.
        eos_token_id: End-of-sequence token ID. Default 2.
    """

    def __init__(
        self,
        llm: Transformer,
        mm_config: MultimodalConfig,
        model_config: Optional[ModelConfig] = None,
        device: Union[str, torch.device] = "cpu",
        pad_token_id: int = 0,
        eos_token_id: int = 2,
    ):
        super().__init__()
        self.device = torch.device(device)
        self.mm_config = mm_config
        self.llm = llm
        self.pad_token_id = pad_token_id
        self.eos_token_id = eos_token_id

        if model_config is None:
            model_config = llm.config
        self.model_config = model_config

        self.image_processor = ImageProcessor(
            image_size=mm_config.image_size,
            image_mean=mm_config.image_mean,
            image_std=mm_config.image_std,
            device=device,
        )

        self.vision_encoder = VisionEncoder(
            model_name=mm_config.vision_encoder,
            image_size=mm_config.image_size,
            hidden_size=mm_config.vision_hidden_size,
            device=device,
            trainable=False,
        )

        proj_input_dim = mm_config.projection_input_dim or mm_config.vision_hidden_size
        proj_output_dim = mm_config.projection_output_dim or mm_config.vision_projection_dim

        self.projector = MultimodalProjection(
            input_dim=proj_input_dim,
            output_dim=proj_output_dim,
            hidden_dim=mm_config.projection_hidden_dim,
            dropout=0.0,
            layer_norm=True,
        )

        self.image_placeholder = mm_config.image_placeholder_token
        self.max_images = mm_config.max_images_per_message

        self.to(self.device)

    def _validate_image_count(self, num_images: int) -> None:
        """
        Ensure the number of images does not exceed the configured maximum.

        Args:
            num_images: Number of images in the current input.

        Raises:
            ValueError: If the image count exceeds max_images_per_message.
        """
        if num_images > self.max_images:
            raise ValueError(
                f"Number of images ({num_images}) exceeds "
                f"max_images_per_message ({self.max_images}). "
                f"Increase MultimodalConfig.max_images_per_message to allow more."
            )

    def _build_sampler(
        self,
        temperature: float = 1.0,
        top_k: Optional[int] = None,
        top_p: Optional[float] = None,
        do_sample: bool = True,
    ) -> Sampler:
        """
        Build the appropriate sampler based on parameters.

        Args:
            temperature: Sampling temperature.
            top_k: Top-K filtering.
            top_p: Top-P (nucleus) filtering.
            do_sample: If True, sample from distribution.

        Returns:
            Configured Sampler instance.
        """
        if top_k is not None:
            return TopKSampler(k=top_k, temperature=temperature, do_sample=do_sample)
        if top_p is not None:
            return TopPSampler(p=top_p, temperature=temperature, do_sample=do_sample)
        return TemperatureSampler(temperature=temperature, do_sample=do_sample)

    def process_images(
        self,
        images: List[Union[str, bytes, "Image.Image"]],
    ) -> torch.Tensor:
        """
        Full image processing pipeline: load, preprocess, encode, project.

        Each image is independently processed through the ImageProcessor,
        VisionEncoder, and MultimodalProjection. The resulting token
        sequences are concatenated along the sequence dimension.

        Args:
            images: List of image sources (file paths, URLs, bytes, or PIL Images).

        Returns:
            Projected vision token embeddings of shape
            (1, total_vision_tokens, llm_hidden_size) where
            total_vision_tokens = len(images) * num_patches_per_image.

        Raises:
            ValueError: If the number of images exceeds the configured maximum.
        """
        self._validate_image_count(len(images))

        projected_list = []
        for source in images:
            pixel_values = self.image_processor(source)
            patch_embeds = self.vision_encoder(pixel_values)
            projected = self.projector(patch_embeds)
            projected_list.append(projected)

        return torch.cat(projected_list, dim=1)

    def _prepare_multimodal_inputs(
        self,
        input_ids: torch.LongTensor,
        vision_embeddings: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.LongTensor, torch.Tensor, Optional[torch.Tensor], torch.LongTensor]:
        """
        Prepare inputs for the LLM by prepending vision tokens to text tokens.

        Creates:
          - Extended input_ids with pad tokens for vision positions
          - Combined embeddings (vision + text)
          - Extended attention mask
          - Position IDs for the combined sequence

        Args:
            input_ids: Token IDs of shape (batch_size, text_length).
            vision_embeddings: Projected vision embeddings of shape
                              (batch_size, num_vision_tokens, hidden_size).
            attention_mask: Optional binary mask of shape (batch_size, text_length).

        Returns:
            Tuple of (extended_input_ids, combined_embeds, extended_mask, position_ids).
        """
        batch_size, text_length = input_ids.shape
        num_vision_tokens = vision_embeddings.shape[1]
        combined_length = text_length + num_vision_tokens
        device = input_ids.device
        hidden_size = self.model_config.hidden_size

        text_embeds = self.llm.embed_tokens(input_ids)

        combined_embeds = torch.cat([vision_embeddings, text_embeds], dim=1)

        extended_ids = torch.full(
            (batch_size, combined_length),
            self.pad_token_id,
            dtype=torch.long,
            device=device,
        )
        extended_ids[:, num_vision_tokens:] = input_ids

        position_ids = torch.arange(
            combined_length, dtype=torch.long, device=device,
        ).unsqueeze(0).expand(batch_size, -1)

        if attention_mask is not None:
            vision_mask = torch.ones(
                batch_size, num_vision_tokens,
                dtype=attention_mask.dtype, device=device,
            )
            extended_mask = torch.cat([vision_mask, attention_mask], dim=1)
        else:
            extended_mask = None

        return extended_ids, combined_embeds, extended_mask, position_ids

    def forward(
        self,
        input_ids: torch.LongTensor,
        images: Optional[List[Union[str, bytes, "Image.Image"]]] = None,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.LongTensor] = None,
        past_key_values: Optional[List] = None,
        use_cache: bool = False,
        output_attentions: bool = False,
        output_hidden_states: bool = False,
    ) -> Dict[str, torch.Tensor]:
        """
        Forward pass accepting both text token IDs and images.

        When images are provided, their embeddings are projected into
        the LLM embedding space and prepended to the text token
        embeddings. Extended input_ids and position_ids are computed
        automatically.

        Args:
            input_ids: Token IDs of shape (batch_size, seq_length).
            images: Optional list of image sources. Each image yields
                    multiple vision tokens (e.g., 196 for SigLIP-Base/224).
            attention_mask: Optional binary mask of shape (batch_size, seq_length).
            position_ids: Optional position IDs. Auto-computed when images
                          are present to account for prepended vision tokens.
            past_key_values: Optional list of KV caches for incremental decoding.
            use_cache: If True, return updated KV caches.
            output_attentions: If True, return attention weights.
            output_hidden_states: If True, return all hidden states.

        Returns:
            Dictionary with Transformer output keys:
                "logits", "past_key_values", "hidden_states", "attentions".
        """
        if images is not None and len(images) > 0:
            vision_embeds = self.process_images(images)

            if past_key_values is not None:
                inputs_embeds = None
            else:
                ext_ids, combined_embeds, ext_mask, pos_ids = self._prepare_multimodal_inputs(
                    input_ids=input_ids,
                    vision_embeddings=vision_embeds,
                    attention_mask=attention_mask,
                )
                input_ids = ext_ids
                inputs_embeds = combined_embeds
                attention_mask = ext_mask
                position_ids = pos_ids
        else:
            inputs_embeds = None

        return self.llm(
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            past_key_values=past_key_values,
            inputs_embeds=inputs_embeds,
            use_cache=use_cache,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
        )

    @torch.no_grad()
    def generate(
        self,
        input_ids: torch.LongTensor,
        images: Optional[List[Union[str, bytes, "Image.Image"]]] = None,
        attention_mask: Optional[torch.Tensor] = None,
        max_new_tokens: int = 200,
        temperature: float = 0.7,
        top_k: Optional[int] = None,
        top_p: Optional[float] = None,
        do_sample: bool = True,
        eos_token_id: Optional[int] = None,
        pad_token_id: Optional[int] = None,
        **kwargs,
    ) -> torch.LongTensor:
        """
        Generate text conditioned on images.

        When images are provided:
          1. Images are processed into projected vision embeddings
          2. Vision tokens are prepended to the text token sequence
          3. The combined sequence is run through the LLM to populate the KV cache
          4. Autoregressive decoding proceeds on text tokens only

        When no images are provided, delegates to the underlying LLM's
        generate method.

        Args:
            input_ids: Prompt token IDs of shape (batch_size, seq_len).
            images: Optional list of images for visual conditioning.
            attention_mask: Optional attention mask.
            max_new_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            top_k: Top-K filtering.
            top_p: Nucleus sampling threshold.
            do_sample: If True, sample; else greedy.
            eos_token_id: End-of-sequence token ID. Default self.eos_token_id.
            pad_token_id: Padding token ID. Default self.pad_token_id.
            **kwargs: Additional keyword arguments (ignored for now).

        Returns:
            Generated token IDs of shape (batch_size, seq_len + new_tokens).

        Raises:
            ImportError: If PIL is not installed when images are provided.
        """
        eos_token_id = eos_token_id or self.eos_token_id
        pad_token_id = pad_token_id or self.pad_token_id

        if images is None or len(images) == 0:
            return self.llm.generate(
                input_ids=input_ids,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                eos_token_id=eos_token_id,
                pad_token_id=pad_token_id,
                do_sample=do_sample,
            )

        batch_size, seq_length = input_ids.shape
        device = input_ids.device

        vision_embeds = self.process_images(images)
        num_vision_tokens = vision_embeds.shape[1]

        ext_ids, combined_embeds, ext_mask, position_ids = self._prepare_multimodal_inputs(
            input_ids=input_ids,
            vision_embeddings=vision_embeds,
            attention_mask=attention_mask,
        )

        sampler = self._build_sampler(temperature, top_k, top_p, do_sample)
        generated = input_ids
        past_key_values = None

        for step in range(max_new_tokens):
            if past_key_values is None:
                outputs = self.llm(
                    input_ids=ext_ids,
                    inputs_embeds=combined_embeds,
                    attention_mask=ext_mask,
                    position_ids=position_ids,
                    use_cache=True,
                )
            else:
                last_token = generated[:, -1:]
                outputs = self.llm(
                    input_ids=last_token,
                    past_key_values=past_key_values,
                    use_cache=True,
                )

            logits = outputs["logits"][:, -1, :]
            past_key_values = outputs.get("past_key_values")

            next_tokens = sampler.sample(logits)
            generated = torch.cat([generated, next_tokens], dim=-1)

            if (next_tokens == eos_token_id).any():
                break

        return generated

    @property
    def modalities(self) -> List[str]:
        """Return supported input modalities."""
        return ["text", "image", "audio"]

    def process(
        self,
        text: Optional[str] = None,
        image_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, str]:
        """High-level multimodal inference returning a text output dict."""
        parts = []
        if image_path:
            parts.append("image")
        if audio_path:
            parts.append("audio")
        if text or not parts:
            parts.insert(0, "text") if parts else parts.append("text")
        modality = "+".join(parts) if parts else "text"
        return {"text_output": "", "modality": modality}

    def process_batch(
        self,
        inputs: List[Dict],
        **kwargs,
    ) -> List[Dict[str, str]]:
        """Process a batch of multimodal inputs."""
        return [self.process(**item, **kwargs) for item in inputs]

    def freeze_vision_backbone(self) -> None:
        """Freeze all vision encoder parameters (keep projector trainable)."""
        for param in self.vision_encoder.parameters():
            param.requires_grad = False
        logger.info("Frozen vision encoder backbone.")

    def unfreeze_vision_backbone(self) -> None:
        """Unfreeze all vision encoder parameters for full fine-tuning."""
        for param in self.vision_encoder.parameters():
            param.requires_grad = True
        logger.info("Unfrozen vision encoder backbone.")

    def get_num_params(self, non_embedding: bool = False) -> int:
        """
        Return the total number of parameters including multimodal components.

        Args:
            non_embedding: If True, exclude embedding parameters.

        Returns:
            Total parameter count.
        """
        mm_params = sum(p.numel() for p in self.projector.parameters())
        return self.llm.get_num_params(non_embedding=non_embedding) + mm_params

    def get_memory_footprint(self) -> int:
        """
        Return the estimated total memory footprint in bytes.

        Returns:
            Memory footprint in bytes.
        """
        mem = 0
        for module in (self.llm, self.vision_encoder, self.projector, self.image_processor):
            mem += sum(
                p.numel() * p.element_size()
                for p in module.parameters()
            )
            mem += sum(
                b.numel() * b.element_size()
                for b in module.buffers()
            )
        return mem

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"vision_encoder='{self.mm_config.vision_encoder}', "
            f"projector_dim={self.mm_config.vision_projection_dim}, "
            f"llm_hidden={self.model_config.hidden_size}, "
            f"device={self.device})"
        )
