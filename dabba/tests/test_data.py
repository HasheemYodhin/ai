import os
import json
import tempfile
import torch
from dabba.data.text_cleaner import TextCleaner
from dabba.data.deduplication import Deduplicator
from dabba.data.document_parser import DocumentParser
from dabba.data.chunker import TextChunker
from dabba.data.packer import SequencePacker


class TestTextCleaner:
    def test_clean_basic(self):
        cleaner = TextCleaner(min_text_length=5)
        result = cleaner.clean("  Hello   world!  ")
        assert result is not None
        assert "Hello" in result

    def test_remove_html(self):
        cleaner = TextCleaner(remove_html=True, min_text_length=1)
        result = cleaner.clean("<p>Hello <b>world</b></p>")
        assert result is not None
        assert "<p>" not in result
        assert "Hello" in result

    def test_remove_urls(self):
        cleaner = TextCleaner(remove_urls=True, min_text_length=1)
        result = cleaner.clean("Check https://example.com/page for details")
        assert result is not None
        assert "https://" not in result

    def test_min_text_length_filter(self):
        cleaner = TextCleaner(min_text_length=100)
        result = cleaner.clean("short")
        assert result is None

    def test_max_text_length_filter(self):
        cleaner = TextCleaner(min_text_length=1, max_text_length=10)
        result = cleaner.clean("this is a long text that should be filtered out")
        assert result is None

    def test_extra_whitespace_removal(self):
        cleaner = TextCleaner(remove_extra_whitespace=True, min_text_length=1)
        result = cleaner.clean("hello    world\n\n\nnext line")
        assert result is not None
        assert "    " not in result

    def test_unicode_normalization(self):
        cleaner = TextCleaner(normalize_unicode=True, min_text_length=1)
        result = cleaner.clean("café")
        assert result is not None

    def test_clean_batch(self):
        cleaner = TextCleaner(min_text_length=5)
        texts = ["valid text here", "no", "another valid one"]
        results = cleaner.clean_batch(texts)
        assert len(results) == 2

    def test_none_input(self):
        cleaner = TextCleaner()
        result = cleaner.clean(None)
        assert result is None

    def test_empty_string(self):
        cleaner = TextCleaner(min_text_length=1)
        result = cleaner.clean("")
        assert result is None


class TestDeduplication:
    def test_exact_dedup(self):
        dedup = Deduplicator(method="exact")
        docs = ["hello world", "hello world", "unique doc", "another"]
        result = dedup.deduplicate(docs)
        assert len(result) == 3
        assert result[0] == "hello world"

    def test_minhash_dedup(self):
        dedup = Deduplicator(method="minhash", threshold=0.8, num_perm=64)
        docs = [
            "the quick brown fox jumps over the lazy dog",
            "the quick brown fox jumps over the lazy dog indeed",
            "completely different document here",
        ]
        result = dedup.deduplicate(docs)
        assert len(result) <= 2

    def test_is_duplicate(self):
        dedup = Deduplicator(method="exact")
        assert not dedup.is_duplicate("first text")
        assert dedup.is_duplicate("first text")
        assert not dedup.is_duplicate("second text")

    def test_empty_list(self):
        dedup = Deduplicator()
        result = dedup.deduplicate([])
        assert result == []

    def test_all_unique(self):
        dedup = Deduplicator(method="exact")
        docs = ["doc a", "doc b", "doc c"]
        result = dedup.deduplicate(docs)
        assert len(result) == 3


class TestDocumentParser:
    def test_parse_txt(self):
        parser = DocumentParser()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Hello world.\n\nThis is a test.\n\nFinal paragraph.")
            tmp_path = f.name
        try:
            texts = parser.parse_file(tmp_path)
            assert len(texts) >= 1
        finally:
            os.unlink(tmp_path)

    def test_parse_json(self):
        parser = DocumentParser()
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"text": "Hello from JSON"}, f)
            tmp_path = f.name
        try:
            texts = parser.parse_file(tmp_path)
            assert any("Hello from JSON" in t for t in texts)
        finally:
            os.unlink(tmp_path)

    def test_parse_jsonl(self):
        parser = DocumentParser()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps({"text": "line1"}) + "\n")
            f.write(json.dumps({"text": "line2"}) + "\n")
            tmp_path = f.name
        try:
            texts = parser.parse_file(tmp_path)
            assert len(texts) == 2
        finally:
            os.unlink(tmp_path)

    def test_file_not_found(self):
        parser = DocumentParser()
        try:
            parser.parse_file("/nonexistent/file.txt")
            assert False
        except FileNotFoundError:
            pass

    def test_unsupported_format(self):
        parser = DocumentParser()
        with tempfile.NamedTemporaryFile(suffix=".xyz", mode="w", delete=False) as f:
            f.write("content")
            tmp_path = f.name
        try:
            texts = parser.parse_file(tmp_path)
            assert texts == []
        finally:
            os.unlink(tmp_path)

    def test_parse_directory(self):
        parser = DocumentParser()
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                p = os.path.join(tmpdir, f"doc{i}.txt")
                with open(p, "w") as f:
                    f.write(f"Document {i} content here.\n\nMore text.")
            texts = list(parser.parse_directory(tmpdir))
            assert len(texts) >= 3


class TestTextChunker:
    def test_chunk_paragraph(self):
        chunker = TextChunker(chunk_size=100, strategy="paragraph")
        text = "Para one.\n\nPara two.\n\nPara three.\n\nPara four."
        chunks = chunker.chunk(text)
        assert len(chunks) >= 1

    def test_chunk_fixed(self):
        chunker = TextChunker(chunk_size=20, chunk_overlap=5, strategy="fixed")
        text = "This is a longer text to be split into fixed size chunks for testing."
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2

    def test_chunk_by_token(self):
        chunker = TextChunker(chunk_size=5, strategy="token")
        text = "one two three four five six seven eight nine ten"
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2

    def test_chunk_iterator(self):
        chunker = TextChunker(chunk_size=50, strategy="paragraph")
        text = "Para one.\n\nPara two.\n\nPara three."
        chunks = list(chunker.chunk_iterator(text))
        assert len(chunks) >= 1

    def test_empty_text(self):
        chunker = TextChunker()
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_invalid_strategy(self):
        chunker = TextChunker(strategy="invalid")
        try:
            chunker.chunk("some text")
            assert False
        except ValueError:
            pass


class TestSequencePacker:
    def test_pack_single_sequence(self):
        packer = SequencePacker(max_length=128)
        seqs = [{"input_ids": torch.arange(10), "labels": torch.arange(10)}]
        result = packer.pack(seqs)
        assert "input_ids" in result
        assert "labels" in result
        assert "attention_mask" in result
        assert result["input_ids"].shape[0] == 128

    def test_pack_multiple_sequences(self):
        packer = SequencePacker(max_length=256)
        seqs = [
            {"input_ids": torch.arange(50), "labels": torch.arange(50)},
            {"input_ids": torch.arange(80), "labels": torch.arange(80)},
        ]
        result = packer.pack(seqs)
        assert result["input_ids"].shape[0] == 256
        assert result["document_ids"] is not None

    def test_pack_batch(self):
        packer = SequencePacker(max_length=64)
        batch = [
            [{"input_ids": torch.arange(10), "labels": torch.arange(10)}],
            [{"input_ids": torch.arange(20), "labels": torch.arange(20)}],
        ]
        result = packer.pack_batch(batch)
        assert result["input_ids"].shape[0] == 2
        assert result["input_ids"].shape[1] == 64

    def test_causal_mask(self):
        packer = SequencePacker(max_length=16)
        attn_mask = torch.ones(2, 16)
        doc_ids = torch.zeros(2, 16, dtype=torch.long)
        doc_ids[:, 0] = 1
        mask = packer.get_causal_mask(attn_mask, doc_ids)
        assert mask.shape == (2, 1, 16, 16)

    def test_empty_sequences(self):
        packer = SequencePacker(max_length=64)
        result = packer.pack([])
        assert result["input_ids"].shape[0] == 64
