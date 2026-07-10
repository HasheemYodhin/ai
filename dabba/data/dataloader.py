"""
Dataloader factory for creating configured data loaders for training
and evaluation.

Combines StreamingDataset, SequencePacker, and standard PyTorch
DataLoader into a simple interface.
"""

from typing import Dict, Iterator, Optional, Union

import torch
from torch.utils.data import DataLoader, DistributedSampler, IterableDataset

from dabba.data.streaming_dataset import StreamingDataset
from dabba.data.packer import SequencePacker
from dabba.utils.distributed import is_distributed, get_world_size


def create_dataloader(
    data_path: str,
    seq_length: int = 2048,
    batch_size: int = 32,
    shuffle: bool = True,
    shuffle_buffer: int = 10000,
    seed: int = 42,
    num_workers: int = 4,
    prefetch_factor: int = 2,
    pack_sequences: bool = False,
    cache_in_memory: bool = False,
    is_eval: bool = False,
    infinite: bool = True,
) -> DataLoader:
    """
    Create a configured DataLoader for training or evaluation.

    Args:
        data_path: Path to directory containing tokenized data files.
        seq_length: Maximum sequence length.
        batch_size: Batch size per GPU.
        shuffle: If True, shuffle the data (for training).
        shuffle_buffer: Size of the shuffle buffer for streaming.
        seed: Random seed.
        num_workers: Number of DataLoader worker processes.
        prefetch_factor: Number of batches to prefetch per worker.
        pack_sequences: If True, pack short sequences together.
        cache_in_memory: If True, load all data into RAM.
        is_eval: If True, use deterministic settings (no shuffle, 1 worker).
        infinite: If True, the dataset yields sequences indefinitely.

    Returns:
        Configured DataLoader instance.
    """
    dataset = StreamingDataset(
        data_path=data_path,
        seq_length=seq_length,
        shuffle_buffer=shuffle_buffer if shuffle else 0,
        seed=seed,
        cache_in_memory=cache_in_memory,
        file_pattern="*.bin",
    )

    if is_eval:
        num_workers = 1
        shuffle = False

    loader = DataLoader(
        dataset=dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        prefetch_factor=prefetch_factor if num_workers > 0 else None,
        pin_memory=torch.cuda.is_available(),
        drop_last=True,
        persistent_workers=num_workers > 0,
    )

    return loader
