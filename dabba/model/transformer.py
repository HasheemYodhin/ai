"""
Full decoder-only transformer language model.

Stacks multiple DecoderBlock layers with input embeddings, position
embeddings (RoPE), and the output language model head.

Supports:
    - Configurable depth (num_layers) from small to very large models
    - Pre-norm or post-norm architecture
    - Weight tying between input embeddings and output head
    - Gradient checkpointing for memory efficiency
    - KV cache for autoregressive generation
    - Multiple attention modes (MHA, GQA, MQA)
"""

from typing import Dict, List, Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from dabba.model.embedding import TokenEmbedding
from dabba.model.decoder_block import DecoderBlock
from dabba.model.output_head import OutputHead
from dabba.model.kv_cache import KVCache
from dabba.config.model_config import ModelConfig


class Transformer(nn.Module):
    """
    Decoder-only transformer language model.

    Architecture:
        Token Embedding → [DecoderBlock × N] → Output Head → Logits

    The model uses Rotary Position Embeddings (RoPE) instead of learned
    absolute position embeddings, and supports Grouped Query Attention
    (GQA) for efficient inference.

    Args:
        config: ModelConfig instance with all hyperparameters.
    """

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config

        self.embed_tokens = TokenEmbedding(
            vocab_size=config.vocab_size,
            hidden_size=config.hidden_size,
            padding_idx=0,
            dropout=config.embedding_dropout,
        )

        self.layers = nn.ModuleList([
            DecoderBlock(
                hidden_size=config.hidden_size,
                num_attention_heads=config.num_attention_heads,
                num_key_value_heads=config.num_key_value_heads,
                head_dim=config.head_dim,
                intermediate_size=config.intermediate_size,
                hidden_act=config.hidden_act,
                rms_norm_eps=config.rms_norm_eps,
                use_rms_norm=config.use_rms_norm,
                pre_norm=config.pre_norm,
                max_position_embeddings=config.max_position_embeddings,
                rope_theta=config.rope_theta,
                rope_scaling=config.rope_scaling,
                partial_rotary_factor=config.partial_rotary_factor,
                attention_dropout=config.attention_dropout,
                ffn_dropout=config.ffn_dropout,
                use_flash_attention=config.use_flash_attention,
                sliding_window=config.sliding_window,
                bias=False,
                layer_idx=i,
            )
            for i in range(config.num_layers)
        ])

        NormClass = (
            RMSNorm if config.use_rms_norm else LayerNorm
        )
        self.norm = NormClass(config.hidden_size, eps=config.rms_norm_eps)

        embed_weight = self.embed_tokens.weight if config.tie_word_embeddings else None
        self.lm_head = OutputHead(
            hidden_size=config.hidden_size,
            vocab_size=config.vocab_size,
            weight=embed_weight,
            bias=False,
        )

        self.gradient_checkpointing = False

    def forward(
        self,
        input_ids: Optional[torch.LongTensor] = None,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.LongTensor] = None,
        past_key_values: Optional[List[KVCache]] = None,
        inputs_embeds: Optional[torch.FloatTensor] = None,
        use_cache: bool = False,
        output_attentions: bool = False,
        output_hidden_states: bool = False,
    ) -> Dict[str, torch.Tensor]:
        """
        Forward pass for the transformer model.

        Args:
            input_ids: Token IDs of shape (batch_size, seq_length).
            attention_mask: Optional mask of shape (batch, 1, seq, total_seq).
            position_ids: Optional position IDs of shape (batch, seq_length).
            past_key_values: Optional list of KV caches, one per layer.
            inputs_embeds: Optional pre-computed embeddings.
            use_cache: If True, return KV caches for all layers.
            output_attentions: If True, return attention weights.
            output_hidden_states: If True, return all hidden states.

        Returns:
            Dictionary with keys:
                - "logits": Output logits of shape (batch, seq, vocab)
                - "past_key_values": List of KV caches if use_cache
                - "hidden_states": List of hidden states if output_hidden_states
                - "attentions": List of attention weights if output_attentions
        """
        batch_size, seq_length = input_ids.shape

        if position_ids is None:
            past_length = past_key_values[0].size if past_key_values else 0
            position_ids = torch.arange(
                past_length, past_length + seq_length,
                dtype=torch.long, device=input_ids.device
            ).unsqueeze(0).expand(batch_size, -1)

        if inputs_embeds is None:
            hidden_states = self.embed_tokens(input_ids)
        else:
            hidden_states = inputs_embeds

        if attention_mask is not None and attention_mask.dim() == 2:
            attention_mask = self._make_causal_mask(
                attention_mask, past_key_values is not None
            )

        if past_key_values is None:
            past_key_values = [None] * len(self.layers)

        all_hidden_states = [] if output_hidden_states else None
        all_attentions = [] if output_attentions else None
        new_past_key_values = [] if use_cache else None

        for i, layer in enumerate(self.layers):
            if output_hidden_states:
                all_hidden_states.append(hidden_states)

            if self.gradient_checkpointing and self.training:
                hidden_states, kv_cache = self._gradient_checkpointing_forward(
                    layer, hidden_states, attention_mask, position_ids,
                    past_key_values[i], use_cache, output_attentions
                )
            else:
                hidden_states, kv_cache = layer(
                    hidden_states=hidden_states,
                    attention_mask=attention_mask,
                    position_ids=position_ids,
                    past_key_value=past_key_values[i],
                    use_cache=use_cache,
                    output_attentions=output_attentions,
                )

            if use_cache:
                new_past_key_values.append(kv_cache)

        hidden_states = self.norm(hidden_states)

        if output_hidden_states:
            all_hidden_states.append(hidden_states)

        logits = self.lm_head(hidden_states)

        output = {"logits": logits}
        if use_cache:
            output["past_key_values"] = new_past_key_values
        if output_hidden_states:
            output["hidden_states"] = all_hidden_states
        if output_attentions:
            output["attentions"] = all_attentions

        return output

    def _make_causal_mask(
        self,
        attention_mask: torch.Tensor,
        has_past: bool = False,
    ) -> torch.Tensor:
        """
        Create a causal attention mask with support for padding tokens.

        Args:
            attention_mask: Binary mask of shape (batch, seq_len).
            has_past: Whether we have past key values.

        Returns:
            Causal mask of shape (batch, 1, seq_len, total_len).
        """
        batch_size, seq_length = attention_mask.shape
        device = attention_mask.device

        causal_mask = torch.triu(
            torch.full((seq_length, seq_length), float("-inf"), device=device),
            diagonal=1,
        )

        if has_past:
            causal_mask = torch.cat(
                [torch.zeros(seq_length, 0, device=device), causal_mask],
                dim=1,
            )

        padding_mask = attention_mask.unsqueeze(1).unsqueeze(2)
        causal_mask = causal_mask.unsqueeze(0).unsqueeze(0)
        mask = padding_mask * causal_mask

        return mask

    def _gradient_checkpointing_forward(self, layer, *args, **kwargs):
        """
        Run a layer with gradient checkpointing to save memory.

        Args:
            layer: The layer to run.
            *args, **kwargs: Arguments for the layer.

        Returns:
            Layer output.
        """
        from torch.utils.checkpoint import checkpoint
        return checkpoint(layer, *args, use_reentrant=False, **kwargs)

    def enable_gradient_checkpointing(self) -> None:
        """Enable gradient checkpointing for memory-efficient training."""
        self.gradient_checkpointing = True

    def disable_gradient_checkpointing(self) -> None:
        """Disable gradient checkpointing."""
        self.gradient_checkpointing = False

    @torch.no_grad()
    def generate(
        self,
        input_ids: torch.LongTensor,
        max_new_tokens: int = 100,
        temperature: float = 1.0,
        top_k: Optional[int] = None,
        top_p: Optional[float] = None,
        eos_token_id: int = 2,
        pad_token_id: int = 0,
        do_sample: bool = True,
        **kwargs,
    ) -> torch.LongTensor:
        """
        Generate text using the model.

        Args:
            input_ids: Prompt token IDs of shape (batch_size, seq_len).
            max_new_tokens: Maximum number of tokens to generate.
            temperature: Sampling temperature (>1 = more random, <1 = more deterministic).
            top_k: If set, only sample from top-k highest probability tokens.
            top_p: If set, nucleus sampling (cumulative probability threshold).
            eos_token_id: End-of-sequence token ID.
            pad_token_id: Padding token ID.
            do_sample: If True, sample from distribution. If False, greedy decode.

        Returns:
            Generated token IDs including the prompt.
        """
        from dabba.inference.generator import Generator
        generator = Generator(self)
        return generator.generate(
            input_ids=input_ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            eos_token_id=eos_token_id,
            do_sample=do_sample,
        )

    def get_num_params(self, non_embedding: bool = False) -> int:
        """
        Return the number of parameters in the model.

        Args:
            non_embedding: If True, exclude embedding parameters.

        Returns:
            Parameter count.
        """
        num_params = sum(p.numel() for p in self.parameters())
        if non_embedding:
            num_params -= sum(
                p.numel()
                for p in self.embed_tokens.parameters()
            )
        return num_params

    def get_memory_footprint(self) -> int:
        """
        Return the estimated memory footprint in bytes.

        Returns:
            Memory footprint in bytes.
        """
        mem = sum(
            p.numel() * p.element_size()
            for p in self.parameters()
        )
        if hasattr(self, "buffers"):
            mem += sum(
                b.numel() * b.element_size()
                for b in self.buffers()
            )
        return mem


from dabba.model.normalizations import RMSNorm, LayerNorm
