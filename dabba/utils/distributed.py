"""
Distributed training utilities. Provides helper functions for DDP
(Data Distributed Parallel) initialization, synchronization, and
communication across processes.

Supports both single-node multi-GPU and multi-node distributed training.
"""

import os
import torch
import torch.distributed as dist
from typing import Optional


def is_distributed() -> bool:
    """
    Check if distributed training is initialized.

    Returns:
        True if torch.distributed is available and initialized.
    """
    return dist.is_available() and dist.is_initialized()


def get_world_size() -> int:
    """
    Get the total number of processes in the distributed group.

    Returns:
        World size (number of processes). Returns 1 if not distributed.
    """
    if is_distributed():
        return dist.get_world_size()
    return 1


def get_rank() -> int:
    """
    Get the rank of the current process.

    Returns:
        Rank of the current process. Returns 0 if not distributed.
    """
    if is_distributed():
        return dist.get_rank()
    return 0


def get_local_rank() -> int:
    """
    Get the local rank of the current process (within a single node).

    Returns:
        Local rank, or 0 if environment variable is not set.
    """
    return int(os.environ.get("LOCAL_RANK", 0))


def setup_distributed(
    backend: str = "nccl",
    init_method: Optional[str] = None,
    world_size: Optional[int] = None,
    rank: Optional[int] = None,
) -> None:
    """
    Initialize the distributed training environment.

    Reads environment variables set by torchrun or similar launchers.
    Falls back to a single-process setup if not in a distributed context.

    Args:
        backend: Communication backend ("nccl" for GPU, "gloo" for CPU).
        init_method: URL for distributed initialization.
        world_size: Total number of processes.
        rank: Rank of this process.
    """
    if not dist.is_available():
        return

    env_rank = int(os.environ.get("RANK", -1))
    env_world_size = int(os.environ.get("WORLD_SIZE", -1))
    env_master_addr = os.environ.get("MASTER_ADDR", "localhost")
    env_master_port = os.environ.get("MASTER_PORT", "29500")

    if env_rank < 0:
        return

    if not dist.is_initialized():
        dist.init_process_group(
            backend=backend,
            init_method=init_method or f"tcp://{env_master_addr}:{env_master_port}",
            world_size=world_size or env_world_size,
            rank=rank or env_rank,
        )

    torch.cuda.set_device(get_local_rank())


def cleanup_distributed() -> None:
    """Destroy the distributed process group."""
    if is_distributed():
        dist.destroy_process_group()


def all_reduce_mean(tensor: torch.Tensor) -> torch.Tensor:
    """
    Compute the mean of a tensor across all processes.

    Args:
        tensor: Input tensor.

    Returns:
        Tensor with the mean value synchronized across all processes.
    """
    if not is_distributed() or get_world_size() == 1:
        return tensor

    dist.all_reduce(tensor, op=dist.ReduceOp.SUM)
    tensor = tensor / get_world_size()
    return tensor


def all_reduce_sum(tensor: torch.Tensor) -> torch.Tensor:
    """
    Compute the sum of a tensor across all processes.

    Args:
        tensor: Input tensor.

    Returns:
        Tensor with the sum value synchronized across all processes.
    """
    if not is_distributed() or get_world_size() == 1:
        return tensor

    dist.all_reduce(tensor, op=dist.ReduceOp.SUM)
    return tensor


def broadcast_model(model: torch.nn.Module, src_rank: int = 0) -> None:
    """
    Broadcast model parameters from source rank to all other processes.

    Args:
        model: PyTorch model whose parameters should be synchronized.
        src_rank: Source rank to broadcast from.
    """
    if not is_distributed():
        return
    for param in model.parameters():
        dist.broadcast(param.data, src=src_rank)


def average_gradients(model: torch.nn.Module) -> None:
    """
    Average gradients across all processes in the distributed group.
    Should be called after loss.backward() and before optimizer.step().

    Args:
        model: Model whose gradients should be averaged.
    """
    if not is_distributed() or get_world_size() == 1:
        return
    world_size = get_world_size()
    for param in model.parameters():
        if param.grad is not None:
            dist.all_reduce(param.grad.data, op=dist.ReduceOp.SUM)
            param.grad.data /= world_size
