"""
Logging utilities for dabba. Provides a centralized logger with
file and console output, structured formatting, and distributed
training awareness.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_LOGGERS: dict = {}


def setup_logger(
    name: str = "dabba",
    level: str = "info",
    log_file: Optional[str] = None,
    rank: int = 0,
    simple_format: bool = False,
) -> logging.Logger:
    """
    Create and configure a logger with the given name.

    Args:
        name: Logger name (usually module name).
        level: Log level string ("debug", "info", "warning", "error", "critical").
        log_file: Optional file path for log output.
        rank: Process rank (used in distributed training to avoid duplicate logs).
        simple_format: Use simpler format (for non-interactive environments).

    Returns:
        Configured logging.Logger instance.
    """
    if rank != 0:
        level = "error"

    logger = logging.getLogger(name)
    logger.setLevel(_LOG_LEVELS.get(level, logging.INFO))

    if logger.handlers:
        return logger

    if not simple_format:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        formatter = logging.Formatter(fmt="%(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _LOGGERS[name] = logger
    return logger


def get_logger(name: str = "dabba") -> logging.Logger:
    """
    Get an existing logger by name, or create a new one with default settings.

    Args:
        name: Logger name.

    Returns:
        logging.Logger instance.
    """
    if name in _LOGGERS:
        return _LOGGERS[name]
    return setup_logger(name=name)
