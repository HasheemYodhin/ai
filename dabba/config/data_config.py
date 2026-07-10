"""
Data pipeline configuration. Controls data sources, preprocessing,
streaming, chunking, packing, and shuffling behavior.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DataConfig:
    """
    Configuration for the data preprocessing and streaming pipeline.

    Supports multiple data sources (local files, web datasets), text
    cleaning and deduplication, document chunking, and packed sequence
    generation for efficient transformer training.
    """

    # Data sources
    train_data_path: Optional[str] = None
    eval_data_path: Optional[str] = None
    web_dataset: Optional[str] = None  # Hugging Face dataset name or URL

    # File formats supported
    file_extensions: List[str] = field(
        default_factory=lambda: [".txt", ".jsonl", ".json", ".csv", ".parquet"]
    )

    # Text cleaning
    clean_text: bool = True
    min_text_length: int = 50
    max_text_length: Optional[int] = None
    remove_html: bool = True
    remove_urls: bool = True
    remove_extra_whitespace: bool = True
    normalize_unicode: bool = True
    language_filter: Optional[str] = None  # ISO language code

    # Deduplication
    deduplicate: bool = True
    dedup_method: str = "exact"  # "exact", "minhash"
    minhash_num_perm: int = 128
    minhash_threshold: float = 0.8
    minhash_seed: int = 42

    # Chunking
    chunk_size: int = 2048
    chunk_overlap: int = 64
    chunk_strategy: str = "paragraph"  # "paragraph", "sentence", "token", "fixed"

    # Tokenization
    tokenizer_path: Optional[str] = None
    vocab_size: int = 32000
    train_tokenizer: bool = True
    tokenizer_sample_size: int = 100000  # Number of docs for tokenizer training

    # Streaming dataset
    streaming: bool = True
    shuffle_buffer_size: int = 10000
    prefetch_batches: int = 2
    cache_in_memory: bool = False

    # Packed sequences
    pack_sequences: bool = True
    max_packed_length: Optional[int] = None  # Defaults to model max_seq_length

    # Masking
    mask_padding: bool = True
    loss_on_padding: bool = False
