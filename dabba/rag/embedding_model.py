"""
Text embedding model wrapper using sentence-transformers.

Provides a unified interface for encoding queries and documents into
dense vector representations used throughout the RAG pipeline.
"""

from typing import List, Optional, Union

import numpy as np
import numpy.typing as npt

from dabba.utils.logging import get_logger

logger = get_logger("dabba.rag.embedding")


class EmbeddingModel:
    """
    Wrapper around sentence-transformers for producing dense text embeddings.

    Supports configurable model names, device placement, batch encoding,
    and optional L2 normalization of output vectors.

    Usage:
        model = EmbeddingModel(model_name="BAAI/bge-small-en-v1.5")
        vector = model.encode("What is the capital of France?")
        vectors = model.encode_batch(["doc1", "doc2", "doc3"])
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        device: str = "cpu",
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        max_seq_length: Optional[int] = None,
        show_progress_bar: bool = False,
    ) -> None:
        """
        Initialize the embedding model.

        Args:
            model_name: HuggingFace model name or path for sentence-transformers.
            device: Target device ("cpu", "cuda", "cuda:0", etc.).
            batch_size: Number of texts to encode per batch.
            normalize_embeddings: If True, L2-normalize output embeddings.
            max_seq_length: Maximum sequence length (tokens). Uses model default
                when None.
            show_progress_bar: Show a progress bar during encoding.
        """
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self.show_progress_bar = show_progress_bar

        self._model = None
        self._max_seq_length = max_seq_length
        self._load_model()

    def _load_model(self) -> None:
        """Lazy-load the sentence-transformers model."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
            )
            if self._max_seq_length is not None:
                self._model.max_seq_length = self._max_seq_length
            logger.info(
                "Loaded embedding model %s on %s (dim=%d, max_len=%d)",
                self.model_name,
                self.device,
                self.dim,
                self._model.max_seq_length,
            )
        except ImportError:
            raise ImportError(
                "sentence-transformers is required. Install with: pip install sentence-transformers"
            )

    @property
    def dim(self) -> int:
        """Embedding dimension of the loaded model."""
        if self._model is None:
            self._load_model()
        return self._model.get_sentence_embedding_dimension()

    def encode(self, text: str) -> npt.NDArray[np.float32]:
        """
        Encode a single text string into an embedding vector.

        Args:
            text: Input text to encode.

        Returns:
            Embedding vector as a 1-D float32 numpy array.
        """
        if not text or not text.strip():
            raise ValueError("Cannot encode empty text.")
        return self.encode_batch([text])[0]

    def encode_batch(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        show_progress_bar: Optional[bool] = None,
    ) -> npt.NDArray[np.float32]:
        """
        Encode a list of texts into a matrix of embeddings.

        Args:
            texts: List of text strings to encode.
            batch_size: Override the default batch size for this call.
            show_progress_bar: Override the default progress bar setting.

        Returns:
            2-D float32 numpy array of shape (len(texts), dim).
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        self._load_model()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size or self.batch_size,
            show_progress_bar=(
                show_progress_bar
                if show_progress_bar is not None
                else self.show_progress_bar
            ),
            normalize_embeddings=self.normalize_embeddings,
        )
        return np.array(embeddings, dtype=np.float32)

    def encode_queries(self, queries: List[str]) -> npt.NDArray[np.float32]:
        """
        Encode query strings, optionally applying query-side prefixes
        used by some models (e.g., BGE, E5).

        Args:
            queries: List of query strings.

        Returns:
            2-D float32 numpy array of shape (len(queries), dim).
        """
        prefixed: List[str] = []
        for q in queries:
            if "bge" in self.model_name.lower():
                prefixed.append(f"Represent this sentence for searching: {q}")
            elif "e5" in self.model_name.lower():
                prefixed.append(f"query: {q}")
            else:
                prefixed.append(q)
        return self.encode_batch(prefixed)

    def encode_documents(self, documents: List[str]) -> npt.NDArray[np.float32]:
        """
        Encode document strings, optionally applying document-side prefixes
        used by some models.

        Args:
            documents: List of document strings.

        Returns:
            2-D float32 numpy array of shape (len(documents), dim).
        """
        prefixed: List[str] = []
        for d in documents:
            if "bge" in self.model_name.lower():
                prefixed.append(f"Represent this document for searching: {d}")
            elif "e5" in self.model_name.lower():
                prefixed.append(f"passage: {d}")
            else:
                prefixed.append(d)
        return self.encode_batch(prefixed)

    def similarity(
        self,
        query_embedding: npt.NDArray[np.float32],
        document_embeddings: npt.NDArray[np.float32],
    ) -> npt.NDArray[np.float32]:
        """
        Compute cosine similarity between a query embedding and document embeddings.

        Args:
            query_embedding: 1-D query embedding vector.
            document_embeddings: 2-D matrix of document embeddings.

        Returns:
            1-D array of cosine similarity scores.
        """
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-12)
        doc_norms = document_embeddings / (
            np.linalg.norm(document_embeddings, axis=1, keepdims=True) + 1e-12
        )
        return np.dot(doc_norms, query_norm)

    def __getstate__(self) -> dict:
        """Serialization support — exclude the model itself."""
        state = self.__dict__.copy()
        state["_model"] = None
        return state

    def __setstate__(self, state: dict) -> None:
        """Deserialization support."""
        self.__dict__.update(state)
        self._model = None
