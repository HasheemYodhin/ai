"""Utility modules for logging, configuration, and distributed training."""

from dabba.utils.config_loader import load_config, save_config
from dabba.utils.logging import get_logger, setup_logger

_DISTRIBUTED_EXPORTS = {
    "all_reduce_mean",
    "get_rank",
    "get_world_size",
    "is_distributed",
}


def __getattr__(name: str):
    """Load Torch-dependent distributed helpers only when requested."""
    if name in _DISTRIBUTED_EXPORTS:
        from dabba.utils import distributed

        return getattr(distributed, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Include lazily exported helpers in interactive module discovery."""
    return sorted(set(globals()) | _DISTRIBUTED_EXPORTS)


__all__ = [
    "all_reduce_mean",
    "get_logger",
    "get_rank",
    "get_world_size",
    "is_distributed",
    "load_config",
    "save_config",
    "setup_logger",
]
