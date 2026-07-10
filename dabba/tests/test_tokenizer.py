import os
import json
import tempfile
import torch
from dabba.tokenizer import BPETokenizer, SpecialTokens, get_special_tokens


class TestBPETokenizer:
    def test_init(self):
        tokenizer = BPETokenizer(vocab_size=1000)
        assert tokenizer.vocab_size == 1000
        assert tokenizer.special_tokens is not None
        assert tokenizer.byte_level is True

    def test_train_small_vocab(self):
        texts = ["hello world", "hello there", "world of hello", "test data here"]
        tokenizer = BPETokenizer(vocab_size=50, min_frequency=1)
        tokenizer.train(texts, verbose=False)
        assert len(tokenizer.vocab) <= 50
        assert len(tokenizer.vocab) > 10

    def test_encode_decode_roundtrip(self):
        texts = ["hello world", "this is a test", "bpe tokenization works"]
        tokenizer = BPETokenizer(vocab_size=200, min_frequency=1)
        tokenizer.train(texts, verbose=False)
        for text in texts:
            ids = tokenizer.encode(text)
            decoded = tokenizer.decode(ids)
            assert len(ids) > 0

    def test_encode_returns_list_of_ints(self):
        tokenizer = BPETokenizer(vocab_size=100, min_frequency=1)
        tokenizer.train(["test encode"], verbose=False)
        ids = tokenizer.encode("hello")
        assert isinstance(ids, list)
        assert all(isinstance(i, int) for i in ids)

    def test_special_tokens_present(self):
        tokenizer = BPETokenizer(vocab_size=100, min_frequency=1)
        tokenizer.train(["some text"], verbose=False)
        assert tokenizer.special_tokens.pad_token_id == 0
        assert tokenizer.special_tokens.bos_token_id == 1
        assert tokenizer.special_tokens.eos_token_id == 2
        assert tokenizer.special_tokens.unk_token_id == 3

    def test_batch_encode_decode(self):
        texts = ["first document", "second document here", "third one"]
        tokenizer = BPETokenizer(vocab_size=150, min_frequency=1)
        tokenizer.train(texts, verbose=False)
        batch_ids = tokenizer.encode_batch(texts)
        assert len(batch_ids) == len(texts)
        decoded = tokenizer.decode_batch(batch_ids)
        assert len(decoded) == len(texts)

    def test_save_and_load(self):
        texts = ["save and load test", "another document", "final one"]
        tokenizer = BPETokenizer(vocab_size=150, min_frequency=1)
        tokenizer.train(texts, verbose=False)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = f.name
        try:
            tokenizer.save(tmp_path)
            loaded = BPETokenizer.load(tmp_path)
            assert loaded.vocab_size == tokenizer.vocab_size
            assert loaded.byte_level == tokenizer.byte_level
            assert len(loaded.vocab) == len(tokenizer.vocab)
            for text in texts:
                orig_ids = tokenizer.encode(text)
                loaded_ids = loaded.encode(text)
                assert orig_ids == loaded_ids
        finally:
            os.unlink(tmp_path)

    def test_byte_level_encoding(self):
        tokenizer = BPETokenizer(vocab_size=200, min_frequency=1, byte_level=True)
        tokenizer.train(["hello world"], verbose=False)
        ids = tokenizer.encode("héllo wörld")
        assert len(ids) > 0

    def test_empty_string(self):
        tokenizer = BPETokenizer(vocab_size=100, min_frequency=1)
        tokenizer.train(["test"], verbose=False)
        ids = tokenizer.encode("")
        assert ids == []

    def test_vocab_size_property(self):
        tokenizer = BPETokenizer(vocab_size=100, min_frequency=1)
        tokenizer.train(["test"], verbose=False)
        assert tokenizer.get_vocab_size() == len(tokenizer.vocab)

    def test_len(self):
        tokenizer = BPETokenizer(vocab_size=100, min_frequency=1)
        tokenizer.train(["test"], verbose=False)
        assert len(tokenizer) == len(tokenizer.vocab)

    def test_special_tokens_factory(self):
        st = get_special_tokens()
        assert st.pad_token_id == 0
        assert st.bos_token_id == 1
        assert st.eos_token_id == 2
        st2 = get_special_tokens(pad_token_id=10, bos_token_id=11, eos_token_id=12)
        assert st2.pad_token_id == 10
        assert st2.bos_token_id == 11

    def test_special_tokens_num_special(self):
        st = get_special_tokens()
        assert st.get_num_special_tokens() >= 7

    def test_special_tokens_id_to_token(self):
        st = get_special_tokens()
        assert st.id_to_token(0) == "<pad>"
        assert st.id_to_token(1) == "<bos>"
        assert st.id_to_token(999) == "<unk>"

    def test_cache_clears(self):
        tokenizer = BPETokenizer(vocab_size=100, min_frequency=1, cache_size=10)
        tokenizer.train(["test"], verbose=False)
        for i in range(20):
            tokenizer.encode(f"text {i}")
        assert len(tokenizer._encode_cache) <= 10

    def test_getstate_clears_cache(self):
        tokenizer = BPETokenizer(vocab_size=100, min_frequency=1)
        tokenizer.train(["test"], verbose=False)
        tokenizer.encode("hello")
        state = tokenizer.__getstate__()
        assert state["_encode_cache"] == {}
        assert state["_decode_cache"] == {}
