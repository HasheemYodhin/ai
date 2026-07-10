"""
Streaming dataset implementation for memory-efficient training on
large text corpora.

Reads tokenized data from disk in chunks, supports shuffling with
a buffer, and provides an iterable-style PyTorch Dataset compatible
with torch DataLoader.
"""

import json
import os
import random
import struct
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union
import numpy as np

import torch
from torch.utils.data import IterableDataset, get_worker_info


class StreamingDataset(IterableDataset):
    """
    Memory-efficient iterable-style dataset for training on large
    text corpora that don't fit in RAM.

    Reads binary tokenized data files (`.bin`) or JSONL files from
    disk in a streaming fashion. Supports shuffling within a sliding
    window buffer and distributed training via worker-aware sharding.

    Data format (binary):
        [num_tokens: uint64] [token_ids: uint32 x num_tokens]

    Usage:
        dataset = StreamingDataset("data/train/", seq_length=2048)
        loader = DataLoader(dataset, batch_size=32)
        for batch in loader:
            # batch contains input_ids, attention_mask, labels
    """

    def __init__(
        self,
        data_path: str,
        seq_length: int = 2048,
        shuffle_buffer: int = 10000,
        seed: int = 42,
        cache_in_memory: bool = False,
        prefetch_batches: int = 2,
        file_pattern: str = "*.bin",
    ):
        """
        Initialize the streaming dataset.

        Args:
            data_path: Path to directory containing .bin or .jsonl files.
            seq_length: Maximum sequence length for each sample.
            shuffle_buffer: Size of the shuffle buffer (0 = no shuffling).
            seed: Random seed for shuffling.
            cache_in_memory: If True, load all data into memory.
            prefetch_batches: Number of batches to prefetch.
            file_pattern: Glob pattern for matching data files.
        """
        super().__init__()
        self.data_path = data_path
        self.seq_length = seq_length
        self.shuffle_buffer = shuffle_buffer
        self.seed = seed
        self.cache_in_memory = cache_in_memory
        self.prefetch_batches = prefetch_batches
        self.file_pattern = file_pattern

        self._rng = random.Random(seed)
        self._file_list = self._get_file_list()
        self._cached_data: Optional[List[int]] = None

        if self.cache_in_memory:
            self._cache_all_data()

    def _get_file_list(self) -> List[str]:
        """
        Get sorted list of data files matching the file pattern.

        Returns:
            Sorted list of file paths.
        """
        path = Path(self.data_path)
        files = sorted(str(f) for f in path.glob(self.file_pattern))
        if not files:
            files = sorted(str(f) for f in path.glob("*.jsonl"))
        if not files:
            raise FileNotFoundError(
                f"No data files found in {self.data_path} "
                f"matching {self.file_pattern} or *.jsonl"
            )
        return files

    def _cache_all_data(self) -> None:
        """
        Load all data files into memory. Can use significant RAM for
        large datasets.
        """
        all_tokens = []
        for file_path in self._file_list:
            tokens = self._read_file(file_path)
            all_tokens.extend(tokens)
        self._cached_data = all_tokens

    def _read_file(self, path: str) -> List[int]:
        """
        Read a single data file (binary .bin or .jsonl).

        Args:
            path: Path to the data file.

        Returns:
            List of token IDs.
        """
        if path.endswith(".bin"):
            return self._read_binary(path)
        elif path.endswith(".jsonl"):
            return self._read_jsonl(path)
        else:
            return self._read_binary(path)

    def _read_binary(self, path: str) -> List[int]:
        """
        Read a binary token file.

        Format: [num_tokens: uint64] [tokens: uint32 x num_tokens]

        Args:
            path: Path to .bin file.

        Returns:
            List of token IDs.
        """
        with open(path, "rb") as f:
            header = f.read(8)
            if len(header) < 8:
                return []
            num_tokens = struct.unpack("<Q", header)[0]
            token_bytes = f.read(num_tokens * 4)
            tokens = struct.unpack(f"<{num_tokens}I", token_bytes)
            return list(tokens)

    def _read_jsonl(self, path: str) -> List[int]:
        """
        Read a JSONL file where each line contains token IDs.

        Line format: {"tokens": [1, 2, 3, ...]}

        Args:
            path: Path to .jsonl file.

        Returns:
            List of token IDs.
        """
        tokens = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    line_tokens = data.get("tokens") or data.get("input_ids") or []
                    tokens.extend(line_tokens)
                except json.JSONDecodeError:
                    continue
        return tokens

    def _token_generator(self) -> Iterator[int]:
        """
        Generate tokens from data files, cycling through files
        indefinitely.

        Yields:
            Token IDs one at a time.
        """
        if self._cached_data is not None:
            while True:
                for token in self._cached_data:
                    yield token
            return

        while True:
            for file_path in self._file_list:
                tokens = self._read_file(file_path)
                for token in tokens:
                    yield token

    def _shuffle_generator(self) -> Iterator[int]:
        """
        Yield shuffled tokens using a buffer for randomization.

        Maintains a buffer of shuffle_buffer tokens, randomly selects
        one to yield, and refills from the source generator.

        Yields:
            Shuffled token IDs.
        """
        source = self._token_generator()
        buffer = []

        for token in source:
            buffer.append(token)
            if len(buffer) >= self.shuffle_buffer:
                idx = self._rng.randint(0, len(buffer) - 1)
                yield buffer.pop(idx)

        self._rng.shuffle(buffer)
        while buffer:
            yield buffer.pop()

    def _seq_generator(self) -> Iterator[Dict[str, torch.Tensor]]:
        """
        Generate sequences of seq_length tokens for training.

        Produces input_ids, labels (shifted by 1), and attention_mask.

        Yields:
            Dictionary with "input_ids", "labels", and "attention_mask".
        """
        source = self._shuffle_generator() if self.shuffle_buffer > 0 else self._token_generator()

        token_buffer = []
        for token in source:
            token_buffer.append(token)
            while len(token_buffer) >= self.seq_length + 1:
                tokens = token_buffer[:self.seq_length + 1]
                token_buffer = token_buffer[self.seq_length:]

                input_ids = torch.tensor(tokens[:-1], dtype=torch.long)
                labels = torch.tensor(tokens[1:], dtype=torch.long)
                attention_mask = torch.ones(self.seq_length, dtype=torch.long)

                yield {
                    "input_ids": input_ids,
                    "labels": labels,
                    "attention_mask": attention_mask,
                }

    def __iter__(self) -> Iterator[Dict[str, torch.Tensor]]:
        """
        Return an iterator over the dataset.

        Handles worker-based sharding for multi-worker DataLoader.

        Yields:
            Batches of input_ids, labels, and attention_mask.
        """
        worker_info = get_worker_info()
        if worker_info is not None:
            num_workers = worker_info.num_workers
            worker_id = worker_info.id
            gen = self._seq_generator()
            for i, batch in enumerate(gen):
                if i % num_workers == worker_id:
                    yield batch
        else:
            yield from self._seq_generator()

    def save_to_binary(self, tokens: List[int], path: str) -> None:
        """
        Save a list of tokens to binary format for efficient loading.

        Args:
            tokens: List of token IDs.
            path: Output file path.
        """
        with open(path, "wb") as f:
            f.write(struct.pack("<Q", len(tokens)))
            f.write(struct.pack(f"<{len(tokens)}I", *tokens))

    def __len__(self) -> int:
        """Return an approximate length for the dataset."""
        return 10_000_000  # Placeholder for IterableDataset
