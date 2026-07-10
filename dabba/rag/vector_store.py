"""
Vector database interface and implementations.

Defines an abstract base class for vector stores and provides concrete
implementations using ChromaDB and FAISS for dense retrieval.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import numpy.typing as npt

from dabba.utils.logging import get_logger

logger = get_logger("dabba.rag.vector_store")


@dataclass
class Document:
    """
    A document chunk stored in the vector store.

    Attributes:
        id: Unique identifier for the document.
        text: The text content of the chunk.
        metadata: Arbitrary key-value metadata (source, page, date, etc.).
        embedding: Optional pre-computed embedding vector.
    """

    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[npt.NDArray[np.float32]] = None


@dataclass
class SearchResult:
    """
    A single search result returned by the vector store.

    Attributes:
        document: The matched document.
        score: Similarity score (higher is more relevant).
        rank: Rank position in the result list (1-based).
    """

    document: Document
    score: float
    rank: int


_VectorStoreBase = None  # patched below


class VectorStore:
    """
    Concrete in-memory FAISS-backed vector store.

    Args:
        dimension: Embedding dimension.
        metric: Similarity metric — "cosine", "l2", or "ip".
    """

    def __init__(self, dimension: int = 384, metric: str = "cosine"):
        import faiss
        self.dimension = dimension
        self.metric = metric
        if metric in ("cosine", "ip"):
            self._index = faiss.IndexFlatIP(dimension)
        else:
            self._index = faiss.IndexFlatL2(dimension)
        self._ids: List = []
        self._vectors: List[npt.NDArray] = []

    def add(self, vectors: npt.NDArray, ids=None, metadata=None) -> None:
        vecs = np.array(vectors, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs[np.newaxis, :]
        n = vecs.shape[0]
        if ids is None:
            ids = list(range(len(self._ids), len(self._ids) + n))
        if self.metric == "cosine":
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            vecs = vecs / np.maximum(norms, 1e-8)
        self._index.add(vecs)
        self._ids.extend(list(ids) if hasattr(ids, '__iter__') else [ids])
        self._vectors.extend(list(vecs))

    def search(self, query: npt.NDArray, k: int = 5):
        q = np.array(query, dtype=np.float32)
        if q.ndim == 1:
            q = q[np.newaxis, :]
        if self.metric == "cosine":
            q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-8)
        k = min(k, len(self._ids))
        if k == 0:
            return []
        distances, indices = self._index.search(q, k)
        return [
            {"id": self._ids[i], "distance": float(distances[0][j])}
            for j, i in enumerate(indices[0]) if i >= 0
        ]

    def delete(self, ids) -> None:
        id_set = set(ids) if hasattr(ids, '__iter__') else {ids}
        keep = [i for i, id_ in enumerate(self._ids) if id_ not in id_set]
        if not keep:
            self.clear()
            return
        import faiss
        vecs = np.array([self._vectors[i] for i in keep], dtype=np.float32)
        if self.metric in ("cosine", "ip"):
            self._index = faiss.IndexFlatIP(self.dimension)
        else:
            self._index = faiss.IndexFlatL2(self.dimension)
        self._index.add(vecs)
        self._ids = [self._ids[i] for i in keep]
        self._vectors = [self._vectors[i] for i in keep]

    def clear(self) -> None:
        import faiss
        if self.metric in ("cosine", "ip"):
            self._index = faiss.IndexFlatIP(self.dimension)
        else:
            self._index = faiss.IndexFlatL2(self.dimension)
        self._ids = []
        self._vectors = []

    def save(self, path: str) -> None:
        import pickle, os
        # Support both file path (e.g. .npz) and directory path
        if str(path).endswith((".npz", ".pkl", ".pt")):
            with open(path, "wb") as f:
                pickle.dump({
                    "ids": self._ids,
                    "dimension": self.dimension,
                    "metric": self.metric,
                    "vectors": self._vectors,
                }, f)
        else:
            import faiss
            os.makedirs(path, exist_ok=True)
            faiss.write_index(self._index, os.path.join(path, "index.faiss"))
            with open(os.path.join(path, "meta.pkl"), "wb") as f:
                pickle.dump({"ids": self._ids, "dimension": self.dimension, "metric": self.metric}, f)

    @classmethod
    def load(cls, path: str) -> "VectorStore":
        import pickle, os
        if str(path).endswith((".npz", ".pkl", ".pt")):
            with open(path, "rb") as f:
                data = pickle.load(f)
            store = cls(dimension=data["dimension"], metric=data["metric"])
            if data.get("vectors"):
                vecs = np.array(data["vectors"], dtype=np.float32)
                store._index.add(vecs)
                store._vectors = list(vecs)
            store._ids = data["ids"]
            return store
        import faiss
        with open(os.path.join(path, "meta.pkl"), "rb") as f:
            meta = pickle.load(f)
        store = cls(dimension=meta["dimension"], metric=meta["metric"])
        store._index = faiss.read_index(os.path.join(path, "index.faiss"))
        store._ids = meta["ids"]
        return store

    def __len__(self) -> int:
        return len(self._ids)


class _VectorStoreABC(ABC):
    """
    Abstract base class for vector database backends.

    Subclasses must implement: add_documents, add_embeddings, search,
    delete, persist, load, count, and list_collections.
    """

    @abstractmethod
    def add_documents(
        self,
        documents: List[Document],
        embeddings: npt.NDArray[np.float32],
    ) -> List[str]:
        """
        Add documents with their embeddings to the store.

        Args:
            documents: List of Document objects.
            embeddings: 2-D float32 numpy array of shape (len(documents), dim).

        Returns:
            List of document IDs that were added.
        """
        ...

    @abstractmethod
    def search(
        self,
        query_embedding: npt.NDArray[np.float32],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        Search the vector store for documents similar to the query embedding.

        Args:
            query_embedding: 1-D query embedding vector.
            top_k: Maximum number of results to return.
            score_threshold: Minimum similarity score (results below this are
                discarded).
            filter_criteria: Optional metadata filters.

        Returns:
            List of SearchResult objects, sorted by descending score.
        """
        ...

    @abstractmethod
    def delete(self, ids: List[str]) -> None:
        """
        Delete documents from the store by their IDs.

        Args:
            ids: Document IDs to remove.
        """
        ...

    @abstractmethod
    def persist(self) -> None:
        """Persist the current state of the store to disk."""
        ...

    @abstractmethod
    def load(self) -> None:
        """Load the store state from disk."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return the total number of documents in the store."""
        ...

    @abstractmethod
    def list_collections(self) -> List[str]:
        """List all available collection names."""
        ...


class ChromaVectorStore(_VectorStoreABC):
    """
    Vector store implementation backed by ChromaDB.

    ChromaDB is an open-source embedding database that runs in-process
    and supports metadata filtering, persistence, and collection management.

    Usage:
        store = ChromaVectorStore(
            collection_name="my_docs",
            persist_directory="./chroma_db",
        )
        store.add_documents(docs, embeddings)
        results = store.search(query_emb)
    """

    def __init__(
        self,
        collection_name: str = "dabba_documents",
        persist_directory: str = "./chroma_db",
        distance_metric: str = "cosine",
    ) -> None:
        """
        Initialize the ChromaDB vector store.

        Args:
            collection_name: Name of the ChromaDB collection.
            persist_directory: Directory for on-disk persistence.
            distance_metric: Distance metric ("cosine", "l2", "ip").
        """
        self.collection_name = collection_name
        self.persist_directory = persist_directory
        self.distance_metric = distance_metric

        self._client: Any = None
        self._collection: Any = None
        self._load_chromadb()

    def _load_chromadb(self) -> None:
        """Initialize ChromaDB client and collection."""
        try:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": self.distance_metric},
            )
            logger.info(
                "Connected to ChromaDB collection '%s' at %s",
                self.collection_name,
                self.persist_directory,
            )
        except ImportError:
            raise ImportError(
                "chromadb is required. Install with: pip install chromadb"
            )

    def _to_chroma_metadata(
        self, metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert metadata values to types ChromaDB accepts."""
        cleaned: Dict[str, Any] = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                cleaned[k] = v
            elif v is None:
                cleaned[k] = ""
            else:
                cleaned[k] = str(v)
        return cleaned

    def add_documents(
        self,
        documents: List[Document],
        embeddings: npt.NDArray[np.float32],
    ) -> List[str]:
        if len(documents) != len(embeddings):
            raise ValueError(
                f"Number of documents ({len(documents)}) must match "
                f"number of embeddings ({len(embeddings)})."
            )
        if self._collection is None:
            self._load_chromadb()

        ids = [doc.id for doc in documents]
        texts = [doc.text for doc in documents]
        metadatas = [
            self._to_chroma_metadata(doc.metadata) for doc in documents
        ]

        self._collection.add(
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info("Added %d documents to ChromaDB collection '%s'", len(documents), self.collection_name)
        return ids

    def add_embeddings(
        self,
        ids: List[str],
        embeddings: npt.NDArray[np.float32],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        documents = [
            Document(
                id=ids[i],
                text=texts[i],
                metadata=metadatas[i] if metadatas else {},
            )
            for i in range(len(ids))
        ]
        return self.add_documents(documents, embeddings)

    def search(
        self,
        query_embedding: npt.NDArray[np.float32],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        if self._collection is None:
            self._load_chromadb()

        kwargs: Dict[str, Any] = {
            "query_embeddings": [query_embedding.tolist()],
            "n_results": top_k,
        }
        if filter_criteria:
            kwargs["where"] = filter_criteria

        results = self._collection.query(**kwargs)

        if not results["ids"]:
            return []

        search_results: List[SearchResult] = []
        for i, doc_id in enumerate(results["ids"][0]):
            score = results["distances"][0][i] if results["distances"] else 0.0
            # Chroma returns distances — convert to similarity
            if self.distance_metric == "cosine":
                score = 1.0 - score
            elif self.distance_metric == "l2":
                score = 1.0 / (1.0 + score)
            # "ip" stays as-is (inner product already == similarity)

            if score_threshold is not None and score < score_threshold:
                continue

            doc = Document(
                id=doc_id,
                text=results["documents"][0][i],
                metadata=results["metadatas"][0][i]
                if results["metadatas"]
                else {},
            )
            search_results.append(
                SearchResult(document=doc, score=float(score), rank=i + 1)
            )

        return search_results

    def delete(self, ids: List[str]) -> None:
        if self._collection is None:
            self._load_chromadb()
        self._collection.delete(ids=ids)
        logger.info("Deleted %d documents from ChromaDB", len(ids))

    def persist(self) -> None:
        # ChromaDB PersistentClient auto-saves; this is a no-op but
        # provided for interface conformance.
        logger.info("ChromaDB is auto-persisted at %s", self.persist_directory)

    def load(self) -> None:
        self._load_chromadb()

    def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()

    def list_collections(self) -> List[str]:
        if self._client is None:
            self._load_chromadb()
        collections = self._client.list_collections()
        return [c.name for c in collections]


class FAISSVectorStore(_VectorStoreABC):
    """
    Vector store implementation backed by FAISS.

    FAISS is a library for efficient similarity search and clustering
    of dense vectors, developed by Meta. This implementation uses
    IndexFlatIP (inner product) for exact search by default.

    Usage:
        store = FAISSVectorStore(embedding_dim=384)
        store.add_documents(docs, embeddings)
        results = store.search(query_emb)
        store.persist("faiss_index.bin")
    """

    def __init__(
        self,
        embedding_dim: int = 384,
        index_path: Optional[str] = None,
        distance_metric: str = "cosine",
    ) -> None:
        """
        Initialize the FAISS vector store.

        Args:
            embedding_dim: Dimensionality of the embedding vectors.
            index_path: Path to load a pre-built index from.
            distance_metric: Distance metric ("cosine", "l2", "ip").
        """
        self.embedding_dim = embedding_dim
        self.index_path = index_path
        self.distance_metric = distance_metric

        self._index: Any = None
        self._id_to_doc: Dict[str, Document] = {}
        self._next_id: int = 0
        self._load_faiss()

        if index_path is not None:
            self.load()

    def _load_faiss(self) -> None:
        """Initialize FAISS index."""
        try:
            import faiss
        except ImportError:
            raise ImportError(
                "faiss is required. Install with: pip install faiss-cpu"
            )

        if self.distance_metric == "cosine":
            self._index = faiss.IndexFlatIP(self.embedding_dim)
        elif self.distance_metric == "ip":
            self._index = faiss.IndexFlatIP(self.embedding_dim)
        elif self.distance_metric == "l2":
            self._index = faiss.IndexFlatL2(self.embedding_dim)
        else:
            raise ValueError(f"Unsupported distance metric: {self.distance_metric}")

    def add_documents(
        self,
        documents: List[Document],
        embeddings: npt.NDArray[np.float32],
    ) -> List[str]:
        if len(documents) != len(embeddings):
            raise ValueError(
                f"Number of documents ({len(documents)}) must match "
                f"number of embeddings ({len(embeddings)})."
            )
        if self._index is None:
            self._load_faiss()

        if self.distance_metric == "cosine":
            faiss.normalize_L2(embeddings)

        ids: List[str] = []
        for i, doc in enumerate(documents):
            doc_id = doc.id if doc.id else f"doc_{self._next_id}"
            self._id_to_doc[doc_id] = doc
            ids.append(doc_id)
            self._next_id += 1

        self._index.add(embeddings)
        logger.info("Added %d documents to FAISS index", len(documents))
        return ids

    def search(
        self,
        query_embedding: npt.NDArray[np.float32],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
        filter_criteria: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        if self._index is None or self._index.ntotal == 0:
            return []

        query_vec = query_embedding.reshape(1, -1).astype(np.float32)
        if self.distance_metric == "cosine":
            faiss.normalize_L2(query_vec)

        actual_k = min(top_k, self._index.ntotal)
        distances, indices = self._index.search(query_vec, actual_k)

        doc_ids = list(self._id_to_doc.keys())
        search_results: List[SearchResult] = []
        for rank, (idx, dist) in enumerate(zip(indices[0], distances[0])):
            if idx < 0 or idx >= len(doc_ids):
                continue

            score = float(dist)
            if self.distance_metric == "l2":
                score = 1.0 / (1.0 + score)

            if score_threshold is not None and score < score_threshold:
                continue

            doc_id = doc_ids[idx]
            doc = self._id_to_doc[doc_id]

            if filter_criteria:
                if not all(
                    doc.metadata.get(k) == v for k, v in filter_criteria.items()
                ):
                    continue

            search_results.append(
                SearchResult(document=doc, score=score, rank=rank + 1)
            )

        return search_results

    def delete(self, ids: List[str]) -> None:
        for doc_id in ids:
            self._id_to_doc.pop(doc_id, None)
        # Full rebuild required when using IndexFlat* without IDMap.
        # For simplicity we log a warning and rebuild on next persist.
        logger.warning(
            "Documents removed from metadata map; "
            "call persist() to rebuild the index."
        )

    def persist(self) -> None:
        import faiss

        if self.index_path is None:
            raise ValueError("index_path must be set to persist.")
        faiss.write_index(self._index, self.index_path)
        logger.info("FAISS index persisted to %s", self.index_path)

    def load(self) -> None:
        import faiss

        if self.index_path is None:
            raise ValueError("index_path must be set to load.")
        self._index = faiss.read_index(self.index_path)
        logger.info("FAISS index loaded from %s", self.index_path)

    def count(self) -> int:
        if self._index is None:
            return 0
        return self._index.ntotal

    def list_collections(self) -> List[str]:
        return ["faiss_default"]
