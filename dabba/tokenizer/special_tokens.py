"""
Special tokens used by the dabba tokenizer. Defines standard special
tokens for control, padding, unknown words, and conversation roles.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SpecialTokens:
    """
    Container for special token IDs used in tokenization and training.

    Attributes:
        pad_token_id: Padding token ID (fills sequences to equal length).
        bos_token_id: Beginning-of-sequence token ID.
        eos_token_id: End-of-sequence token ID.
        unk_token_id: Unknown token ID (for out-of-vocabulary words).
        mask_token_id: Mask token ID (for masked language modeling).
        sep_token_id: Separator token ID.
        cls_token_id: Classifier token ID.
        additional_special_tokens: Map of name->ID for custom tokens.
    """

    pad_token_id: int = 0
    bos_token_id: int = 1
    eos_token_id: int = 2
    unk_token_id: int = 3
    mask_token_id: int = 4
    sep_token_id: int = 5
    cls_token_id: int = 6

    additional_special_tokens: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        current_id = 7
        self._id_to_token = {}
        self._token_to_id = {}
        for name, tid in [
            ("<pad>", self.pad_token_id),
            ("<bos>", self.bos_token_id),
            ("<eos>", self.eos_token_id),
            ("<unk>", self.unk_token_id),
            ("<mask>", self.mask_token_id),
            ("<sep>", self.sep_token_id),
            ("<cls>", self.cls_token_id),
        ]:
            self._id_to_token[tid] = name
            self._token_to_id[name] = tid

        for name, tid in self.additional_special_tokens.items():
            self._id_to_token[tid] = name
            self._token_to_id[name] = tid

    def get_num_special_tokens(self) -> int:
        """Return the total count of special tokens."""
        return len(self._id_to_token)

    def token_to_id(self, token: str) -> int:
        """Convert a special token string to its ID."""
        return self._token_to_id.get(token, self.unk_token_id)

    def id_to_token(self, token_id: int) -> str:
        """Convert a special token ID to its string representation."""
        return self._id_to_token.get(token_id, "<unk>")

    def get_vocab_prefix(self, vocab_size: int) -> Dict[str, int]:
        """
        Create a vocabulary prefix mapping special tokens to their IDs.

        Args:
            vocab_size: Total vocabulary size.

        Returns:
            Dictionary mapping token strings to IDs for special tokens.
        """
        return {v: k for k, v in self._id_to_token.items() if k < vocab_size}


def get_special_tokens(
    pad_token_id: int = 0,
    bos_token_id: int = 1,
    eos_token_id: int = 2,
    unk_token_id: int = 3,
    mask_token_id: int = 4,
    sep_token_id: int = 5,
    cls_token_id: int = 6,
    additional_tokens: Dict[str, int] = None,
) -> SpecialTokens:
    """
    Convenience factory for creating a SpecialTokens instance.

    Args:
        pad_token_id: ID for the padding token.
        bos_token_id: ID for the beginning-of-sequence token.
        eos_token_id: ID for the end-of-sequence token.
        unk_token_id: ID for the unknown token.
        mask_token_id: ID for the mask token.
        sep_token_id: ID for the separator token.
        cls_token_id: ID for the classifier token.
        additional_tokens: Additional special tokens mapping names to IDs.

    Returns:
        Configured SpecialTokens instance.
    """
    return SpecialTokens(
        pad_token_id=pad_token_id,
        bos_token_id=bos_token_id,
        eos_token_id=eos_token_id,
        unk_token_id=unk_token_id,
        mask_token_id=mask_token_id,
        sep_token_id=sep_token_id,
        cls_token_id=cls_token_id,
        additional_special_tokens=additional_tokens or {},
    )
