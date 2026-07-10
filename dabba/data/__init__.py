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
from dabba.data.streaming_dataset import StreamingDataset
from dabba.data.packer import SequencePacker
from dabba.data.dataloader import create_dataloader

__all__ = [
    "TextCleaner",
    "Deduplicator",
    "DocumentParser",
    "TextChunker",
    "StreamingDataset",
    "SequencePacker",
    "create_dataloader",
]
