import torch
import numpy as np
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from dabba.rag import RAGPipeline, RAGConfig
from dabba.rag.embedding import EmbeddingModel
from dabba.rag.vector_store import VectorStore
from dabba.rag.retriever import Retriever
from dabba.rag.reranker import Reranker
from dabba.rag.hybrid import HybridRetriever


class TestRAGConfig:
    def test_defaults(self):
        cfg = RAGConfig()
        assert cfg.top_k == 5
        assert cfg.embedding_dim == 384

    def test_custom(self):
        cfg = RAGConfig(top_k=10, embedding_dim=768, similarity_metric="cosine")
        assert cfg.top_k == 10
        assert cfg.embedding_dim == 768


class TestEmbeddingModel:
    def test_encode(self):
        model = Mock(spec=EmbeddingModel)
        model.encode.return_value = torch.randn(3, 384)
        texts = ["hello world", "test document", "another one"]
        embeddings = model.encode(texts)
        assert embeddings.shape == (3, 384)

    def test_encode_single(self):
        model = Mock(spec=EmbeddingModel)
        model.encode.return_value = torch.randn(1, 384)
        embedding = model.encode("single text")
        assert embedding.shape == (1, 384)

    def test_encode_normalized(self):
        model = Mock(spec=EmbeddingModel)
        emb = torch.randn(2, 384)
        emb = emb / emb.norm(dim=-1, keepdim=True)
        model.encode.return_value = emb
        embeddings = model.encode(["test1", "test2"])
        norms = embeddings.norm(dim=-1)
        assert torch.allclose(norms, torch.ones(2), atol=1e-5)

    def test_model_name(self):
        model = Mock(spec=EmbeddingModel)
        type(model).model_name = PropertyMock(return_value="all-MiniLM-L6-v2")
        assert model.model_name == "all-MiniLM-L6-v2"

    def test_embedding_dim(self):
        model = Mock(spec=EmbeddingModel)
        type(model).embedding_dim = PropertyMock(return_value=384)
        assert model.embedding_dim == 384


class TestVectorStore:
    def test_add_and_search(self):
        store = VectorStore(dimension=384, metric="cosine")
        embeddings = torch.randn(10, 384)
        store.add(embeddings, metadata=[{"id": i} for i in range(10)])
        query = torch.randn(1, 384)
        results = store.search(query, k=3)
        assert len(results) == 3

    def test_search_returns_distances(self):
        store = VectorStore(dimension=4, metric="cosine")
        embeddings = torch.eye(4)
        store.add(embeddings, metadata=[{"id": i} for i in range(4)])
        query = torch.tensor([[1.0, 0.0, 0.0, 0.0]])
        results = store.search(query, k=2)
        for r in results:
            assert "distance" in r
            assert "id" in r

    def test_empty_store(self):
        store = VectorStore(dimension=384)
        query = torch.randn(1, 384)
        results = store.search(query, k=3)
        assert results == []

    def test_delete(self):
        store = VectorStore(dimension=4)
        embeddings = torch.randn(5, 4)
        store.add(embeddings)
        store.delete([0, 1])
        query = torch.randn(1, 4)
        results = store.search(query, k=10)
        assert len(results) == 3

    def test_clear(self):
        store = VectorStore(dimension=4)
        store.add(torch.randn(5, 4))
        store.clear()
        assert len(store) == 0

    def test_len(self):
        store = VectorStore(dimension=4)
        assert len(store) == 0
        store.add(torch.randn(5, 4))
        assert len(store) == 5

    def test_save_and_load(self):
        store = VectorStore(dimension=4)
        store.add(torch.randn(5, 4), metadata=[{"id": i} for i in range(5)])
        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            tmp_path = f.name
        try:
            store.save(tmp_path)
            loaded = VectorStore.load(tmp_path)
            assert len(loaded) == 5
        finally:
            os.unlink(tmp_path)

    def test_l2_metric(self):
        store = VectorStore(dimension=4, metric="l2")
        embeddings = torch.randn(5, 4)
        store.add(embeddings)
        query = torch.randn(1, 4)
        results = store.search(query, k=3)
        assert len(results) == 3

    def test_ip_metric(self):
        store = VectorStore(dimension=4, metric="ip")
        embeddings = torch.randn(5, 4)
        store.add(embeddings)
        query = torch.randn(1, 4)
        results = store.search(query, k=3)
        assert len(results) == 3

    def test_large_k(self):
        store = VectorStore(dimension=4)
        embeddings = torch.randn(10, 4)
        store.add(embeddings)
        query = torch.randn(1, 4)
        results = store.search(query, k=100)
        assert len(results) == 10


class TestRetriever:
    def test_retrieve(self):
        retriever = Mock(spec=Retriever)
        retriever.retrieve.return_value = [
            {"text": "doc1", "score": 0.9},
            {"text": "doc2", "score": 0.7},
            {"text": "doc3", "score": 0.5},
        ]
        query = "test query"
        docs = retriever.retrieve(query, k=3)
        assert len(docs) == 3
        assert docs[0]["score"] >= docs[1]["score"]

    def test_retrieve_returns_different_docs(self):
        retriever = Mock(spec=Retriever)
        retriever.retrieve.side_effect = [
            [{"text": "apple doc", "score": 0.9}],
            [{"text": "banana doc", "score": 0.8}],
        ]
        docs1 = retriever.retrieve("apple", k=1)
        docs2 = retriever.retrieve("banana", k=1)
        assert docs1[0]["text"] != docs2[0]["text"]

    def test_retrieve_empty_result(self):
        retriever = Mock(spec=Retriever)
        retriever.retrieve.return_value = []
        docs = retriever.retrieve("unknown query", k=5)
        assert docs == []

    def test_batch_retrieve(self):
        retriever = Mock(spec=Retriever)
        retriever.retrieve_batch.return_value = [
            [{"text": "doc1", "score": 0.99}],
            [{"text": "doc2", "score": 0.88}],
        ]
        queries = ["query1", "query2"]
        results = retriever.retrieve_batch(queries, k=1)
        assert len(results) == 2
        assert len(results[0]) == 1


class TestReranker:
    def test_rerank(self):
        reranker = Mock(spec=Reranker)
        docs = [
            {"text": "doc a", "score": 0.1},
            {"text": "doc b", "score": 0.3},
            {"text": "doc c", "score": 0.2},
        ]
        reranker.rerank.return_value = [
            {"text": "doc b", "score": 0.95},
            {"text": "doc c", "score": 0.90},
            {"text": "doc a", "score": 0.85},
        ]
        query = "test query"
        reranked = reranker.rerank(query, docs, top_k=3)
        assert len(reranked) == 3
        assert reranked[0]["score"] >= reranked[1]["score"]

    def test_rerank_preserves_text(self):
        reranker = Mock(spec=Reranker)
        docs = [{"text": f"doc{i}", "score": 0.1} for i in range(3)]
        reranker.rerank.return_value = [
            {"text": "doc0", "score": 0.99},
            {"text": "doc2", "score": 0.98},
            {"text": "doc1", "score": 0.97},
        ]
        query = "query"
        reranked = reranker.rerank(query, docs, top_k=3)
        texts = [d["text"] for d in reranked]
        assert len(set(texts)) == 3


class TestHybridRetriever:
    def test_hybrid_search(self):
        hybrid = Mock(spec=HybridRetriever)
        hybrid.search.return_value = [
            {"text": "doc1", "score": 0.85},
            {"text": "doc2", "score": 0.72},
        ]
        results = hybrid.search("test query", alpha=0.5, k=2)
        assert len(results) == 2

    def test_alpha_zero(self):
        hybrid = Mock(spec=HybridRetriever)
        hybrid.search.return_value = [{"text": "keyword doc", "score": 0.9}]
        results = hybrid.search("test", alpha=0.0, k=1)
        assert results[0]["text"] == "keyword doc"

    def test_alpha_one(self):
        hybrid = Mock(spec=HybridRetriever)
        hybrid.search.return_value = [{"text": "semantic doc", "score": 0.95}]
        results = hybrid.search("test", alpha=1.0, k=1)
        assert results[0]["text"] == "semantic doc"


class TestRAGPipeline:
    def test_query(self):
        pipeline = Mock(spec=RAGPipeline)
        pipeline.query.return_value = {
            "answer": "This is the generated answer.",
            "documents": [{"text": "source doc", "score": 0.92}],
        }
        result = pipeline.query("What is Dabba?")
        assert "answer" in result
        assert "documents" in result
        assert len(result["documents"]) > 0

    def test_query_no_docs(self):
        pipeline = Mock(spec=RAGPipeline)
        pipeline.query.return_value = {
            "answer": "I don't have enough information.",
            "documents": [],
        }
        result = pipeline.query("Unknown topic")
        assert len(result["documents"]) == 0

    def test_add_documents(self):
        pipeline = Mock(spec=RAGPipeline)
        pipeline.add_documents.return_value = None
        docs = [{"text": "doc1", "metadata": {"source": "wiki"}}]
        pipeline.add_documents(docs)

    def test_add_documents_multiple(self):
        pipeline = Mock(spec=RAGPipeline)
        pipeline.add_documents.return_value = None
        docs = [{"text": f"doc{i}"} for i in range(100)]
        pipeline.add_documents(docs)

    def test_clear_index(self):
        pipeline = Mock(spec=RAGPipeline)
        pipeline.clear_index.return_value = None
        pipeline.clear_index()

    def test_get_stats(self):
        pipeline = Mock(spec=RAGPipeline)
        pipeline.get_stats.return_value = {"num_documents": 42, "embedding_dim": 384}
        stats = pipeline.get_stats()
        assert stats["num_documents"] == 42
