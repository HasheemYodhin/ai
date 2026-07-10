"""
Vocabulary trainer for the BPE tokenizer. Handles loading text data
from various sources, sampling, and training the tokenizer vocabulary.
"""

import random
from pathlib import Path
from typing import Iterator, List, Optional, Union
from dabba.tokenizer.bpe_tokenizer import BPETokenizer
from dabba.utils.logging import get_logger


class VocabTrainer:
    """
    Trains a BPE tokenizer vocabulary on text data from files or iterators.

    Supports training from:
        - Plain text files (.txt)
        - JSONL files (.jsonl)
        - Lists of strings
        - Iterators over strings
        - Directory traversal for .txt files

    Usage:
        trainer = VocabTrainer(vocab_size=32000)
        trainer.load_texts_from_directory("/path/to/data")
        tokenizer = trainer.train()
        tokenizer.save("tokenizer.json")
    """

    def __init__(
        self,
        vocab_size: int = 32000,
        min_frequency: int = 2,
        byte_level: bool = True,
        sample_size: Optional[int] = None,
    ):
        """
        Initialize the vocabulary trainer.

        Args:
            vocab_size: Target vocabulary size.
            min_frequency: Minimum frequency for BPE merges.
            byte_level: Use byte-level BPE if True.
            sample_size: Maximum number of documents to use for training.
        """
        self.vocab_size = vocab_size
        self.min_frequency = min_frequency
        self.byte_level = byte_level
        self.sample_size = sample_size
        self.texts: List[str] = []
        self.logger = get_logger("dabba.tokenizer")

    def add_text(self, text: str) -> None:
        """
        Add a single text to the training corpus.

        Args:
            text: Text string to add.
        """
        if isinstance(text, str) and len(text.strip()) > 0:
            self.texts.append(text)

    def add_texts(self, texts: List[str]) -> None:
        """
        Add multiple texts to the training corpus.

        Args:
            texts: List of text strings.
        """
        for text in texts:
            self.add_text(text)

    def load_text_file(self, path: str) -> int:
        """
        Load texts from a plain text file (one paragraph per entry).

        Args:
            path: Path to the text file.

        Returns:
            Number of texts loaded.
        """
        count = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if len(line) >= 10:
                    self.texts.append(line)
                    count += 1
        return count

    def load_jsonl_file(self, path: str, text_field: str = "text") -> int:
        """
        Load texts from a JSONL file where each line is a JSON object
        with a text field.

        Args:
            path: Path to the JSONL file.
            text_field: JSON field name containing the text.

        Returns:
            Number of texts loaded.
        """
        import json
        count = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    text = obj.get(text_field, "")
                    if isinstance(text, str) and len(text.strip()) > 0:
                        self.texts.append(text)
                        count += 1
                except json.JSONDecodeError:
                    continue
        return count

    def load_directory(self, path: str, pattern: str = "*.txt") -> int:
        """
        Load all text files from a directory.

        Args:
            path: Directory path to scan.
            pattern: Glob pattern for file matching.

        Returns:
            Number of texts loaded across all files.
        """
        total = 0
        for file_path in Path(path).rglob(pattern):
            if file_path.is_file():
                total += self.load_text_file(str(file_path))
        return total

    def load_from_iterator(self, texts: Iterator[str]) -> int:
        """
        Load texts from an iterator.

        Args:
            texts: Iterator yielding text strings.

        Returns:
            Number of texts loaded.
        """
        count = 0
        for text in texts:
            if isinstance(text, str) and len(text.strip()) > 0:
                self.texts.append(text)
                count += 1
        return count

    def train(self) -> BPETokenizer:
        """
        Train the BPE tokenizer on the collected texts.

        If sample_size is set, randomly samples that many texts from
        the corpus before training.

        Returns:
            Trained BPETokenizer instance.
        """
        if not self.texts:
            raise ValueError("No texts loaded. Load texts before training.")

        if self.sample_size and len(self.texts) > self.sample_size:
            self.texts = random.sample(self.texts, self.sample_size)

        self.logger.info(
            f"Training BPE tokenizer on {len(self.texts)} texts "
            f"(vocab_size={self.vocab_size})"
        )

        tokenizer = BPETokenizer(
            vocab_size=self.vocab_size,
            min_frequency=self.min_frequency,
            byte_level=self.byte_level,
        )

        tokenizer.train(self.texts, verbose=True)

        self.logger.info(
            f"Tokenizer trained. Vocabulary size: {len(tokenizer.vocab)}"
        )
        return tokenizer

    def clear(self) -> None:
        """Clear all loaded texts."""
        self.texts.clear()
