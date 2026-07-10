"""
Document chunking module. Splits long documents into smaller chunks
using paragraph, sentence, token-based, or fixed-size strategies.
"""

import re
from typing import Iterator, List, Optional


class TextChunker:
    """
    Splits documents into chunks for processing and training.

    Supports multiple chunking strategies:
        - paragraph: Split on paragraph boundaries
        - sentence: Split on sentence boundaries (using regex)
        - token: Split on whitespace token counts
        - fixed: Split by character count with optional overlap

    Usage:
        chunker = TextChunker(chunk_size=512, chunk_overlap=64, strategy="paragraph")
        chunks = chunker.chunk(long_text)
    """

    def __init__(
        self,
        chunk_size: int = 2048,
        chunk_overlap: int = 64,
        strategy: str = "paragraph",
        respect_boundaries: bool = True,
    ):
        """
        Initialize the text chunker.

        Args:
            chunk_size: Target size of each chunk (in characters or tokens).
            chunk_overlap: Overlap between consecutive chunks.
            strategy: Chunking strategy ("paragraph", "sentence", "token", "fixed").
            respect_boundaries: If True, try to break at natural boundaries.
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy
        self.respect_boundaries = respect_boundaries

        self._sentence_re = re.compile(
            r'(?<=[.!?])\s+(?=[A-Z"\'({])|(?<=[.!?])[\n\r]+|(?<=[\u3002\uff01\uff1f])\s*'
        )
        self._paragraph_re = re.compile(r"\n\s*\n")

    def chunk(self, text: str) -> List[str]:
        """
        Split text into chunks using the configured strategy.

        Args:
            text: Input text to chunk.

        Returns:
            List of text chunks.
        """
        if not text or not text.strip():
            return []

        strategies = {
            "paragraph": self._chunk_by_paragraphs,
            "sentence": self._chunk_by_sentences,
            "token": self._chunk_by_tokens,
            "fixed": self._chunk_fixed_size,
        }

        chunker = strategies.get(self.strategy)
        if chunker is None:
            raise ValueError(f"Unknown chunking strategy: {self.strategy}")

        return chunker(text)

    def _chunk_by_paragraphs(self, text: str) -> List[str]:
        """
        Split text on paragraph boundaries and merge small paragraphs
        into chunks of approximately chunk_size.

        Args:
            text: Input text.

        Returns:
            List of chunks.
        """
        paragraphs = self._paragraph_re.split(text.strip())
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks = []
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            para_len = len(para)
            if current_length + para_len <= self.chunk_size:
                current_chunk.append(para)
                current_length += para_len
            else:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                if para_len > self.chunk_size:
                    sub_chunks = self._chunk_fixed_size(para)
                    chunks.extend(sub_chunks)
                    current_chunk = []
                    current_length = 0
                else:
                    current_chunk = [para]
                    current_length = para_len

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks

    def _chunk_by_sentences(self, text: str) -> List[str]:
        """
        Split text on sentence boundaries and merge into chunks.

        Args:
            text: Input text.

        Returns:
            List of chunks.
        """
        sentences = self._sentence_re.split(text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sent_len = len(sentence)
            if current_length + sent_len <= self.chunk_size:
                current_chunk.append(sentence)
                current_length += sent_len
            else:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                if sent_len > self.chunk_size:
                    sub_chunks = self._chunk_by_tokens(sentence)
                    chunks.extend(sub_chunks)
                    current_chunk = []
                    current_length = 0
                else:
                    current_chunk = [sentence]
                    current_length = sent_len

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    def _chunk_by_tokens(self, text: str) -> List[str]:
        """
        Split text by whitespace token count.

        Args:
            text: Input text.

        Returns:
            List of chunks with approximately chunk_size tokens.
        """
        tokens = text.split()
        chunks = []
        step = max(1, self.chunk_size - self.chunk_overlap)
        for i in range(0, len(tokens), step):
            chunk_tokens = tokens[i:i + self.chunk_size]
            if chunk_tokens:
                chunks.append(" ".join(chunk_tokens))
        return chunks

    def _chunk_fixed_size(self, text: str) -> List[str]:
        """
        Split text by fixed character count with overlap.

        Args:
            text: Input text.

        Returns:
            List of fixed-size chunks.
        """
        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + self.chunk_size, text_len)

            if (
                self.respect_boundaries
                and end < text_len
                and end - start == self.chunk_size
            ):
                search_start = max(start, end - 100)
                search_text = text[search_start:end]
                last_period = max(
                    search_text.rfind("."),
                    search_text.rfind("!"),
                    search_text.rfind("?"),
                    search_text.rfind("\n"),
                )
                if last_period >= 0:
                    end = search_start + last_period + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - self.chunk_overlap if end < text_len else text_len

        return chunks

    def chunk_iterator(self, text: str) -> Iterator[str]:
        """
        Generator version of chunk() for memory efficiency with large texts.

        Args:
            text: Input text.

        Yields:
            Text chunks one at a time.
        """
        for chunk in self.chunk(text):
            yield chunk
