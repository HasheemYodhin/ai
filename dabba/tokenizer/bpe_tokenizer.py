"""
Core BPE (Byte Pair Encoding) tokenizer implementation.

The tokenizer learns merge rules from training data and can encode
text into token IDs and decode IDs back into text. Implements the
standard BPE algorithm with byte-level encoding for full Unicode
coverage.

Reference: "Neural Machine Translation of Rare Words with Subword
Units" (Sennrich et al., 2016) and the GPT-2 byte-level BPE approach.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict

from dabba.tokenizer.special_tokens import SpecialTokens, get_special_tokens


class BPETokenizer:
    """
    Byte Pair Encoding tokenizer with byte-level fallback.

    Features:
        - BPE merge rules learned from training data
        - Byte-level encoding for unknown characters
        - Special token support (pad, bos, eos, unk)
        - Caching for fast encoding/decoding
        - Save/load from JSON files

    Usage:
        tokenizer = BPETokenizer(vocab_size=32000)
        tokenizer.train(texts)
        ids = tokenizer.encode("Hello, world!")
        text = tokenizer.decode(ids)
    """

    def __init__(
        self,
        vocab_size: int = 32000,
        special_tokens: Optional[SpecialTokens] = None,
        min_frequency: int = 2,
        byte_level: bool = True,
        cache_size: int = 10000,
    ):
        """
        Initialize the BPE tokenizer.

        Args:
            vocab_size: Target vocabulary size (including special tokens).
            special_tokens: SpecialTokens configuration. Creates defaults if None.
            min_frequency: Minimum frequency for a merge to be considered.
            byte_level: If True, use byte-level encoding for unknown characters.
            cache_size: Maximum number of cached encode/decode results.
        """
        self.vocab_size = vocab_size
        self.special_tokens = special_tokens or get_special_tokens()
        self.min_frequency = min_frequency
        self.byte_level = byte_level

        self.num_special = self.special_tokens.get_num_special_tokens()
        self.vocab: Dict[str, int] = {}
        self.merges: Dict[Tuple[str, str], str] = {}
        self.merge_priority: Dict[Tuple[str, str], int] = {}

        self._encode_cache: Dict[str, List[int]] = {}
        self._decode_cache: Dict[str, str] = {}
        self._cache_size = cache_size

        self._byte_encoder = self._build_byte_encoder()
        self._byte_decoder = {v: k for k, v in self._byte_encoder.items()}

    def _build_byte_encoder(self) -> Dict[int, str]:
        """
        Build a mapping from byte values to Unicode characters for
        byte-level encoding. Uses a printable Unicode range to represent
        all 256 byte values.
        """
        encoder = {}
        for i in range(256):
            if 33 <= i <= 126:
                encoder[i] = chr(i)
            elif 0 <= i <= 31 or i == 127:
                encoder[i] = chr(i + 256)
            else:
                encoder[i] = chr(i + 512)
        return encoder

    def _get_pairs(self, word: Tuple[str, ...]) -> Set[Tuple[str, str]]:
        """
        Get all adjacent pairs of symbols in a word.

        Args:
            word: Tuple of symbols (characters or subwords).

        Returns:
            Set of adjacent symbol pairs.
        """
        pairs = set()
        prev_char = word[0]
        for char in word[1:]:
            pairs.add((prev_char, char))
            prev_char = char
        return pairs

    def _byte_encode(self, text: str) -> str:
        """
        Encode text into a byte-level representation.
        Each character is converted to its UTF-8 bytes, then each byte
        is mapped to a printable Unicode character.

        Args:
            text: Input text string.

        Returns:
            Byte-encoded string.
        """
        if not text:
            return ""
        return "".join(self._byte_encoder[b] for b in text.encode("utf-8"))

    def _split_into_words(self, text: str) -> List[str]:
        """
        Split text into words using regex. Words are separated by
        whitespace boundaries.

        Args:
            text: Input text.

        Returns:
            List of word strings (including whitespace tokens).
        """
        return re.findall(r"\S+\s*", text)

    def train(self, texts: List[str], verbose: bool = True) -> None:
        """
        Train the BPE tokenizer on a corpus of texts.

        Learns merge rules by iteratively finding the most frequent
        pair of adjacent symbols and merging them until the desired
        vocabulary size is reached.

        Args:
            texts: List of training text strings.
            verbose: If True, print progress information.
        """
        word_freqs: Dict[str, int] = {}
        for text in texts:
            if self.byte_level:
                text = self._byte_encode(text)
            else:
                text = text.lower()
            for word in self._split_into_words(text):
                word_freqs[word] = word_freqs.get(word, 0) + 1

        splits: Dict[str, List[str]] = {}
        for word in word_freqs:
            splits[word] = list(word) + ["</w>"]

        self.vocab = {}
        for sid, stoken in self.special_tokens._id_to_token.items():
            self.vocab[stoken] = sid

        current_id = self.num_special

        for word, symbols in splits.items():
            for symbol in symbols:
                if symbol not in self.vocab:
                    self.vocab[symbol] = current_id
                    current_id += 1

        total_merges = self.vocab_size - len(self.vocab)
        merges_done = 0

        while len(self.vocab) < self.vocab_size:
            pair_freqs = defaultdict(int)
            for word, freq in word_freqs.items():
                symbols = splits[word]
                for i in range(len(symbols) - 1):
                    pair = (symbols[i], symbols[i + 1])
                    pair_freqs[pair] += freq

            if not pair_freqs:
                break

            best_pair = max(pair_freqs, key=pair_freqs.get)
            best_freq = pair_freqs[best_pair]

            if best_freq < self.min_frequency:
                break

            merged = best_pair[0] + best_pair[1]
            self.merges[best_pair] = merged
            self.merge_priority[best_pair] = merges_done

            for word in splits:
                symbols = splits[word]
                new_symbols = []
                i = 0
                while i < len(symbols):
                    if (
                        i < len(symbols) - 1
                        and symbols[i] == best_pair[0]
                        and symbols[i + 1] == best_pair[1]
                    ):
                        new_symbols.append(merged)
                        i += 2
                    else:
                        new_symbols.append(symbols[i])
                        i += 1
                splits[word] = new_symbols

            if merged not in self.vocab:
                self.vocab[merged] = current_id
                current_id += 1

            merges_done += 1
            if verbose and merges_done % 1000 == 0:
                print(f"  Merge {merges_done}: '{best_pair[0]}' + '{best_pair[1]}' "
                      f"-> '{merged}' (freq={best_freq})")

        if verbose:
            print(f"Training complete. Vocabulary: {len(self.vocab)} tokens "
                  f"({merges_done} merges performed)")

    def encode(self, text: str) -> List[int]:
        """
        Encode a text string into token IDs using learned BPE merges.

        Applies byte-level encoding first (if configured), then applies
        merge rules greedily from highest to lowest priority.

        Args:
            text: Input text to encode.

        Returns:
            List of token IDs.
        """
        cache_key = text
        if cache_key in self._encode_cache:
            return self._encode_cache[cache_key][:]

        tokens = []
        text_encoded = self._byte_encode(text) if self.byte_level else text

        words = self._split_into_words(text_encoded)
        for word in words:
            word_symbols = list(word) + ["</w>"] if word else []
            word_symbols = self._apply_merges(word_symbols)
            for symbol in word_symbols:
                token_id = self.vocab.get(symbol, self.special_tokens.unk_token_id)
                tokens.append(token_id)

        self._encode_cache[cache_key] = tokens
        if len(self._encode_cache) > self._cache_size:
            self._encode_cache.clear()

        return tokens

    def _apply_merges(self, symbols: List[str]) -> List[str]:
        """
        Apply learned BPE merges greedily to a list of symbols.

        Repeatedly merges the pair with the highest priority (learned
        earliest) until no more merges can be applied.

        Args:
            symbols: List of symbol strings.

        Returns:
            List of merged subword strings.
        """
        while True:
            pairs = self._get_pairs(tuple(symbols))
            if not pairs:
                break

            best_pair = None
            best_priority = float("inf")
            for pair in pairs:
                priority = self.merge_priority.get(pair, float("inf"))
                if priority < best_priority:
                    best_priority = priority
                    best_pair = pair

            if best_pair not in self.merges:
                break

            merged = self.merges[best_pair]
            new_symbols = []
            i = 0
            while i < len(symbols):
                if (
                    i < len(symbols) - 1
                    and symbols[i] == best_pair[0]
                    and symbols[i + 1] == best_pair[1]
                ):
                    new_symbols.append(merged)
                    i += 2
                else:
                    new_symbols.append(symbols[i])
                    i += 1
            symbols = new_symbols

        return symbols

    def decode(self, token_ids: List[int]) -> str:
        """
        Decode a list of token IDs back into a text string.

        Joins subword tokens, removes word boundary markers, and
        converts byte-level encodings back to UTF-8.

        Args:
            token_ids: List of token IDs to decode.

        Returns:
            Decoded text string.
        """
        cache_key = str(token_ids)
        if cache_key in self._decode_cache:
            return self._decode_cache[cache_key]

        id_to_token = {v: k for k, v in self.vocab.items()}
        symbols = []
        for tid in token_ids:
            token = id_to_token.get(tid, self.special_tokens.id_to_token(tid))
            if self.byte_level:
                if token in self.special_tokens._id_to_token.values():
                    symbols.append(token)
                elif token == "</w>":
                    symbols.append(" ")
                else:
                    symbols.append(token)
            else:
                if token in self.special_tokens._id_to_token.values():
                    symbols.append(token)
                elif token == "</w>":
                    symbols.append(" ")
                else:
                    symbols.append(token)

        if self.byte_level:
            decoded = self._byte_decode("".join(symbols))
        else:
            decoded = "".join(symbols)
            decoded = decoded.replace("</w>", " ")
            decoded = re.sub(r"\s+", " ", decoded).strip()

        self._decode_cache[cache_key] = decoded
        if len(self._decode_cache) > self._cache_size:
            self._decode_cache.clear()

        return decoded

    def _byte_decode(self, text: str) -> str:
        """
        Decode a byte-encoded string back to UTF-8 text.

        Maps each character through the byte decoder lookup and
        converts the resulting byte sequence back to a string.

        Args:
            text: Byte-encoded string.

        Returns:
            Decoded UTF-8 string.
        """
        bytes_list = []
        for char in text:
            byte_val = self._byte_decoder.get(char)
            if byte_val is not None:
                bytes_list.append(byte_val)
        return bytes(bytes_list).decode("utf-8", errors="replace")

    def encode_batch(self, texts: List[str]) -> List[List[int]]:
        """
        Encode a batch of texts into token IDs.

        Args:
            texts: List of text strings.

        Returns:
            List of token ID lists.
        """
        return [self.encode(text) for text in texts]

    def decode_batch(self, batch_ids: List[List[int]]) -> List[str]:
        """
        Decode a batch of token ID lists back to text.

        Args:
            batch_ids: List of token ID lists.

        Returns:
            List of decoded text strings.
        """
        return [self.decode(ids) for ids in batch_ids]

    def get_vocab_size(self) -> int:
        """Return the current vocabulary size."""
        return len(self.vocab)

    def save(self, path: str) -> None:
        """
        Save the tokenizer to a JSON file.

        Args:
            path: File path to save the tokenizer.
        """
        save_data = {
            "vocab_size": self.vocab_size,
            "min_frequency": self.min_frequency,
            "byte_level": self.byte_level,
            "special_tokens": {
                "pad_token_id": self.special_tokens.pad_token_id,
                "bos_token_id": self.special_tokens.bos_token_id,
                "eos_token_id": self.special_tokens.eos_token_id,
                "unk_token_id": self.special_tokens.unk_token_id,
                "mask_token_id": self.special_tokens.mask_token_id,
                "sep_token_id": self.special_tokens.sep_token_id,
                "cls_token_id": self.special_tokens.cls_token_id,
            },
            "vocab": self.vocab,
            "merges": {f"{k[0]} {k[1]}": v for k, v in self.merges.items()},
            "merge_priority": {f"{k[0]} {k[1]}": v for k, v in self.merge_priority.items()},
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "BPETokenizer":
        """
        Load a tokenizer from a JSON file saved with save().

        Args:
            path: Path to the saved tokenizer JSON file.

        Returns:
            Loaded BPETokenizer instance.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        special_tokens = get_special_tokens(**data["special_tokens"])
        tokenizer = cls(
            vocab_size=data["vocab_size"],
            special_tokens=special_tokens,
            min_frequency=data["min_frequency"],
            byte_level=data["byte_level"],
        )

        tokenizer.vocab = data["vocab"]
        tokenizer.merges = {
            tuple(k.split(" ")): v for k, v in data["merges"].items()
        }
        tokenizer.merge_priority = {
            tuple(k.split(" ")): v for k, v in data["merge_priority"].items()
        }

        return tokenizer

    def __len__(self) -> int:
        """Return vocabulary size."""
        return len(self.vocab)

    def __getstate__(self):
        state = self.__dict__.copy()
        state["_encode_cache"] = {}
        state["_decode_cache"] = {}
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
