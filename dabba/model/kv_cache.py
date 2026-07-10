"""
Key-Value (KV) cache for autoregressive inference.

Stores and manages key and value tensors across decoding steps,
avoiding recomputation of previous tokens' keys and values.
"""

from typing import Optional, Tuple

import torch


class KVCache:
    """
    Key-Value cache for efficient autoregressive decoding.

    Maintains a growing buffer of key and value tensors that are
    concatenated with new tokens' keys/values at each generation step.

    The cache shape is (batch_size, num_heads, cached_seq_len, head_dim)
    and grows by 1 in the sequence dimension each step.

    Args:
        key: Initial key tensor, or None.
        value: Initial value tensor, or None.
        max_cache_size: Maximum number of tokens to cache (-1 for no limit).
    """

    def __init__(
        self,
        key: Optional[torch.Tensor] = None,
        value: Optional[torch.Tensor] = None,
        max_cache_size: int = -1,
    ):
        self._key = key
        self._value = value
        self.max_cache_size = max_cache_size

    def update(
        self,
        key: torch.Tensor,
        value: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Update the cache with new key/value tensors.

        Concatenates along the sequence dimension.

        Args:
            key: New key tensor of shape (batch, num_heads, seq_len, head_dim).
            value: New value tensor of shape (batch, num_heads, seq_len, head_dim).

        Returns:
            Tuple of (full_key, full_value) including cached history.
        """
        if self._key is None:
            self._key = key
            self._value = value
        else:
            self._key = torch.cat([self._key, key], dim=2)
            self._value = torch.cat([self._value, value], dim=2)

            if self.max_cache_size > 0 and self._key.size(2) > self.max_cache_size:
                self._key = self._key[:, :, -self.max_cache_size:]
                self._value = self._value[:, :, -self.max_cache_size:]

        return self._key, self._value

    def get(self) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Get the current cached key and value tensors.

        Returns:
            Tuple of (key, value) tensors.

        Raises:
            ValueError: If cache is empty.
        """
        if self._key is None:
            raise ValueError("KV cache is empty. No prior keys/values stored.")
        return self._key, self._value

    @property
    def size(self) -> int:
        """
        Return the current cache size (number of cached tokens).

        Returns:
            Sequence length of cached tokens.
        """
        return self._key.size(2) if self._key is not None else 0

    def reset(self) -> None:
        """Clear the cache."""
        self._key = None
        self._value = None

    def clone(self) -> "KVCache":
        """
        Create a deep copy of the cache.

        Returns:
            New KVCache with copied tensors.
        """
        return KVCache(
            key=self._key.clone() if self._key is not None else None,
            value=self._value.clone() if self._value is not None else None,
            max_cache_size=self.max_cache_size,
        )

    def to(self, device: torch.device) -> "KVCache":
        """
        Move the cache to the specified device.

        Args:
            device: Target device.

        Returns:
            Self for chaining.
        """
        if self._key is not None:
            self._key = self._key.to(device)
        if self._value is not None:
            self._value = self._value.to(device)
        return self

    def __len__(self) -> int:
        """Return the number of cached tokens."""
        return self.size

    def __repr__(self) -> str:
        if self._key is None:
            return "KVCache(empty)"
        return f"KVCache(size={self.size}, shape={list(self._key.shape)})"

    @property
    def cache(self):
        """Dict-like view of cached k/v tensors, None if nothing cached."""
        if self._key is None:
            return None
        return {"key": self._key, "value": self._value}

    def get_max_cache(self) -> int:
        """Return the configured maximum cache size (-1 = unlimited)."""
        return self.max_cache_size
