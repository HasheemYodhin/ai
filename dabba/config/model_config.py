"""
Model configuration dataclass. Defines all hyperparameters for the
decoder-only transformer architecture, supporting model sizes from
10M to 7B+ parameters.
"""

from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class ModelConfig:
    """
    Configuration for the decoder-only transformer model.

    Predefined presets:
        - tiny (10M params)
        - small (50M params)
        - base (125M params)
        - medium (350M params)
        - large (1B params)
        - xl (3B params)
        - xxl (7B params)

    Custom configs can be created by specifying any subset of parameters.
    """

    # Vocabulary and embeddings
    vocab_size: int = 32000
    hidden_size: int = 768
    embedding_dropout: float = 0.1

    # Transformer blocks
    num_layers: int = 12
    num_attention_heads: int = 12
    num_key_value_heads: Optional[int] = None  # None = MHA, < num_heads = GQA
    head_dim: Optional[int] = None  # Auto-computed if None

    # Feed-forward network
    intermediate_size: Optional[int] = None  # Auto-computed if None
    hidden_act: str = "silu"  # "silu" for SwiGLU, "gelu" for GELU
    ffn_dropout: float = 0.0

    # Normalization
    rms_norm_eps: float = 1e-6
    use_rms_norm: bool = True
    pre_norm: bool = True  # Pre-norm vs post-norm

    # RoPE
    rope_theta: float = 10000.0
    rope_scaling: Optional[dict] = None  # e.g., {"type": "linear", "factor": 2.0}
    partial_rotary_factor: float = 1.0  # fraction of head dims to rotate

    # Attention
    attention_dropout: float = 0.0
    sliding_window: Optional[int] = None  # Sliding window attention size
    use_flash_attention: bool = False
    use_sdpa: bool = True  # PyTorch scaled dot product attention

    # Context
    max_position_embeddings: int = 2048

    # KV cache
    kv_cache_dtype: str = "float16"

    # Weight tying
    tie_word_embeddings: bool = True

    # Model size presets
    _presets = {
        "tiny": {
            "vocab_size": 32000,
            "hidden_size": 256,
            "num_layers": 6,
            "num_attention_heads": 8,
            "num_key_value_heads": 4,
            "intermediate_size": 768,
            "max_position_embeddings": 2048,
        },
        "small": {
            "vocab_size": 32000,
            "hidden_size": 512,
            "num_layers": 12,
            "num_attention_heads": 8,
            "num_key_value_heads": 4,
            "intermediate_size": 1536,
            "max_position_embeddings": 4096,
        },
        "base": {
            "vocab_size": 32000,
            "hidden_size": 768,
            "num_layers": 12,
            "num_attention_heads": 12,
            "num_key_value_heads": 4,
            "intermediate_size": 3072,
            "max_position_embeddings": 4096,
        },
        "medium": {
            "vocab_size": 32000,
            "hidden_size": 1024,
            "num_layers": 24,
            "num_attention_heads": 16,
            "num_key_value_heads": 8,
            "intermediate_size": 4096,
            "max_position_embeddings": 8192,
        },
        "large": {
            "vocab_size": 32000,
            "hidden_size": 2048,
            "num_layers": 24,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "intermediate_size": 8192,
            "max_position_embeddings": 8192,
        },
        "xl": {
            "vocab_size": 32000,
            "hidden_size": 3200,
            "num_layers": 32,
            "num_attention_heads": 40,
            "num_key_value_heads": 10,
            "intermediate_size": 12800,
            "max_position_embeddings": 16384,
        },
        "xxl": {
            "vocab_size": 32000,
            "hidden_size": 4096,
            "num_layers": 32,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "intermediate_size": 16384,
            "max_position_embeddings": 16384,
        },
    }

    def __post_init__(self):
        if self.num_key_value_heads is None:
            self.num_key_value_heads = self.num_attention_heads
        if self.head_dim is None:
            self.head_dim = self.hidden_size // self.num_attention_heads
        if self.intermediate_size is None:
            self.intermediate_size = int(self.hidden_size * 8 / 3)
            self.intermediate_size = (
                (self.intermediate_size + 63) // 64 * 64
            )
        assert self.hidden_size % self.num_attention_heads == 0, (
            f"hidden_size ({self.hidden_size}) must be divisible by "
            f"num_attention_heads ({self.num_attention_heads})"
        )
        assert self.num_attention_heads % self.num_key_value_heads == 0, (
            f"num_attention_heads ({self.num_attention_heads}) must be "
            f"divisible by num_key_value_heads ({self.num_key_value_heads})"
        )

    @property
    def num_key_value_groups(self) -> int:
        return self.num_attention_heads // self.num_key_value_heads

    @property
    def num_params(self) -> int:
        """Estimate total parameter count."""
        n = 0
        n += self.vocab_size * self.hidden_size * 2 if self.tie_word_embeddings else self.vocab_size * self.hidden_size
        kv_mult = self.num_key_value_heads / self.num_attention_heads
        for _ in range(self.num_layers):
            n += 4 * self.hidden_size  # RMSNorm x2 (approx)
            n += self.hidden_size * self.hidden_size // self.num_attention_heads * self.num_attention_heads  # Q
            n += self.hidden_size * self.hidden_size // self.num_attention_heads * self.num_key_value_heads * 2  # K, V
            n += self.hidden_size * self.hidden_size  # O
            n += self.hidden_size * self.intermediate_size * 2  # gate + up in SwiGLU
            n += self.intermediate_size * self.hidden_size  # down
        return n

    @classmethod
    def from_preset(cls, name: str, **overrides) -> "ModelConfig":
        """Create a ModelConfig from a named preset with optional overrides."""
        if name not in cls._presets:
            raise ValueError(f"Unknown preset '{name}'. Options: {list(cls._presets.keys())}")
        config = cls(**cls._presets[name])
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)
        config.__post_init__()
        return config
