"""
Data pipeline for processing and streaming training data.

Provides text cleaning, deduplication, document parsing, chunking,
packed sequence generation, and an efficient streaming dataloader
for transformer training.
"""

from dabba.data.text_cleaner import TextCleaner
from dabba.data.deduplication import Deduplicator
from dabba.data.document_parser import DocumentParser
from dabba.data.chunker import TextChunker
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dabba.data.dataloader import create_dataloader
    from dabba.data.packer import SequencePacker
    from dabba.data.streaming_dataset import StreamingDataset

__all__ = [
    "TextCleaner",
    "Deduplicator",
    "DocumentParser",
    "TextChunker",
    "StreamingDataset",
    "SequencePacker",
    "create_dataloader",
]


_TRAINING_EXPORTS = {
    "StreamingDataset": "streaming_dataset",
    "SequencePacker": "packer",
    "create_dataloader": "dataloader",
}


def __getattr__(name: str):
    module = _TRAINING_EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
