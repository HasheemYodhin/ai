"""
Document indexing pipeline.

Handles loading documents from files or directories, chunking them,
generating embeddings, and storing the results in a vector database.
"""

import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

import numpy as np
import numpy.typing as npt

from dabba.config.rag_config import RagConfig
from dabba.data.chunker import TextChunker
from dabba.data.document_parser import DocumentParser
from dabba.rag.embedding_model import EmbeddingModel
from dabba.rag.vector_store import Document, VectorStore
from dabba.utils.logging import get_logger

logger = get_logger("dabba.rag.indexer")


class DocumentIndexer:
    """
    End-to-end document indexing pipeline.

    Loads documents from files or directories, splits them into chunks,
    generates embeddings using an EmbeddingModel, and stores everything
    in a VectorStore with associated metadata.

    Usage:
        indexer = DocumentIndexer(embedding_model, vector_store)
        indexer.index_file("document.pdf")
        indexer.index_directory("/path/to/docs")
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        chunker: Optional[TextChunker] = None,
        document_parser: Optional[DocumentParser] = None,
        config: Optional[RagConfig] = None,
    ) -> None:
        """
        Initialize the document indexer.

        Args:
            embedding_model: Model used to generate embeddings.
            vector_store: Vector database to store indexed documents.
            chunker: Text splitter for chunking long documents. Uses config
                defaults if not provided.
            document_parser: Parser for reading various file formats. Uses
                config defaults if not provided.
            config: RAG configuration. Falls back to defaults otherwise.
        """
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.config = config or RagConfig()

        self.chunker = chunker or TextChunker(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            strategy="paragraph",
        )
        self.document_parser = document_parser or DocumentParser(
            max_file_size_mb=self.config.max_file_size_mb,
        )

    def _generate_doc_id(
        self, source: str, chunk_index: int, text: str
    ) -> str:
        """Generate a deterministic document ID from source, index, and text."""
        raw = f"{source}:{chunk_index}:{text[:100]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _build_metadata(
        self,
        source: str,
        chunk_index: int,
        total_chunks: int,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a metadata dictionary for a document chunk."""
        metadata: Dict[str, Any] = {
            "source": source,
            "source_filename": os.path.basename(source),
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "indexed_at": datetime.utcnow().isoformat(),
        }
        if extra:
            metadata.update(extra)
        return metadata

    def index_text(
        self,
        text: str,
        source: str = "memory",
        metadata: Optional[Dict[str, Any]] = None,
        batch_size: Optional[int] = None,
    ) -> List[str]:
        """
        Index plain text by chunking, embedding, and storing.

        Args:
            text: Text content to index.
            source: Source identifier for provenance tracking.
            metadata: Additional metadata to attach to every chunk.
            batch_size: Embedding batch size override.

        Returns:
            List of document IDs created.
        """
        chunks = self.chunker.chunk(text)
        if not chunks:
            logger.warning("No chunks produced from text (source=%s)", source)
            return []

        documents: List[Document] = []
        total = len(chunks)
        for i, chunk_text in enumerate(chunks):
            doc_id = self._generate_doc_id(source, i, chunk_text)
            doc_meta = self._build_metadata(source, i, total, extra=metadata)
            documents.append(
                Document(id=doc_id, text=chunk_text, metadata=doc_meta)
            )

        return self._embed_and_store(documents, batch_size=batch_size)

    def index_file(
        self,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
        batch_size: Optional[int] = None,
    ) -> List[str]:
        """
        Load a file, parse it, chunk the content, and index it.

        Args:
            file_path: Path to the file to index.
            metadata: Additional metadata to attach to all chunks.
            batch_size: Embedding batch size override.

        Returns:
            List of document IDs created.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        texts = self.document_parser.parse_file(file_path)
        if not texts:
            logger.warning("No text extracted from %s", file_path)
            return []

        full_text = "\n\n".join(texts)
        source = str(path.resolve())
        merged_meta: Dict[str, Any] = {
            "file_type": path.suffix.lower(),
            "file_size_bytes": path.stat().st_size,
        }
        if metadata:
            merged_meta.update(metadata)

        return self.index_text(
            text=full_text,
            source=source,
            metadata=merged_meta,
            batch_size=batch_size,
        )

    def index_directory(
        self,
        directory: str,
        recursive: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, List[str]]:
        """
        Index all supported files in a directory.

        Args:
            directory: Path to the directory to scan.
            recursive: If True, recurse into subdirectories.
            metadata: Additional metadata to attach to all chunks.
            batch_size: Embedding batch size override.

        Returns:
            Dictionary mapping file paths to lists of document IDs.
        """
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            raise NotADirectoryError(f"Not a valid directory: {directory}")

        results: Dict[str, List[str]] = {}
        extensions = self.config.supported_extensions
        pattern = "**/*" if recursive else "*"

        for file_path in sorted(dir_path.glob(pattern)):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in extensions:
                continue

            try:
                doc_ids = self.index_file(
                    str(file_path),
                    metadata=metadata,
                    batch_size=batch_size,
                )
                results[str(file_path)] = doc_ids
                logger.info(
                    "Indexed %s → %d chunks", file_path.name, len(doc_ids)
                )
            except Exception as exc:
                logger.error("Failed to index %s: %s", file_path, exc)
                results[str(file_path)] = []

        return results

    def index_texts(
        self,
        texts: List[str],
        source_prefix: str = "batch",
        metadatas: Optional[List[Dict[str, Any]]] = None,
        batch_size: Optional[int] = None,
    ) -> List[str]:
        """
        Index a list of pre-chunked texts directly.

        Each text is treated as a single chunk. Useful when chunking is
        performed externally.

        Args:
            texts: List of pre-chunked text strings.
            source_prefix: Prefix for source tracking.
            metadatas: Per-text metadata list (must match length of texts).
            batch_size: Embedding batch size override.

        Returns:
            List of document IDs.
        """
        documents: List[Document] = []
        total = len(texts)
        for i, chunk_text in enumerate(texts):
            doc_id = self._generate_doc_id(source_prefix, i, chunk_text)
            extra = metadatas[i] if metadatas and i < len(metadatas) else None
            doc_meta = self._build_metadata(
                source_prefix, i, total, extra=extra
            )
            documents.append(
                Document(id=doc_id, text=chunk_text, metadata=doc_meta)
            )

        return self._embed_and_store(documents, batch_size=batch_size)

    def _embed_and_store(
        self,
        documents: List[Document],
        batch_size: Optional[int] = None,
    ) -> List[str]:
        """
        Generate embeddings for documents and store in the vector store.

        Args:
            documents: List of Document objects to embed and store.
            batch_size: Embedding batch size override.

        Returns:
            List of stored document IDs.
        """
        if not documents:
            return []

        texts = [doc.text for doc in documents]
        embeddings = self.embedding_model.encode_batch(
            texts,
            batch_size=batch_size or self.embedding_model.batch_size,
        )
        doc_ids = self.vector_store.add_documents(documents, embeddings)

        logger.info(
            "Indexed %d chunks (%d dimensions)",
            len(doc_ids),
            embeddings.shape[1],
        )
        return doc_ids

    def clear_index(self) -> None:
        """Delete all documents from the vector store."""
        current_count = self.vector_store.count()
        if current_count > 0:
            # Note: ChromaVectorStore does not support delete_all directly,
            # but the collection can be dropped and recreated.
            logger.info("Clearing %d indexed documents", current_count)
            if hasattr(self.vector_store, "_collection"):
                try:
                    self.vector_store._client.delete_collection(
                        self.vector_store.collection_name
                    )
                    self.vector_store._collection = (
                        self.vector_store._client.create_collection(
                            name=self.vector_store.collection_name,
                        )
                    )
                except Exception:
                    logger.warning("Could not clear vector store via delete_collection")
