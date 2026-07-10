import torch
import pytest
from dabba.model import (
    MultiHeadAttention,
    GroupedQueryAttention,
    MultiQueryAttention,
    KVCache,
    apply_rotary_pos_emb,
    RotaryEmbedding,
    FlashAttention,
    SparseAttention,
    SlidingWindowAttention,
    AlibiAttention,
)


class TestMultiHeadAttention:
    def test_forward(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, weights, cache = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)
        assert weights.shape == (2, 4, 10, 10)

    def test_with_attention_mask(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        mask = torch.ones(2, 1, 10, 10)
        mask[:, :, :, 5:] = 0
        out, weights, _ = attn(x, attention_mask=mask, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_dropout_training(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, attention_dropout=0.5, max_position_embeddings=64)
        attn.train()
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out1, _, _ = attn(x, position_ids=pos)
        out2, _, _ = attn(x, position_ids=pos)
        assert not torch.allclose(out1, out2)

    def test_dropout_eval(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, attention_dropout=0.5, max_position_embeddings=64)
        attn.eval()
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out1, _, _ = attn(x, position_ids=pos)
        out2, _, _ = attn(x, position_ids=pos)
        assert torch.allclose(out1, out2)

    def test_scale(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(1, 1, 64)
        pos = torch.zeros(1, 1, dtype=torch.long)
        out, _, _ = attn(x, position_ids=pos)
        assert not torch.isnan(out).any()

    def test_multiple_layers_independent(self):
        attn1 = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        attn2 = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(1, 5, 64)
        pos = torch.zeros(1, 5, dtype=torch.long)
        o1, _, _ = attn1(x, position_ids=pos)
        o2, _, _ = attn2(x, position_ids=pos)
        assert not torch.allclose(o1, o2)

    def test_batch_independence(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x1 = torch.ones(1, 5, 64)
        x2 = torch.zeros(1, 5, 64)
        pos = torch.zeros(1, 5, dtype=torch.long)
        batch = torch.cat([x1, x2], dim=0)
        pos_batch = torch.cat([pos, pos], dim=0)
        out, _, _ = attn(batch, position_ids=pos_batch)
        assert not torch.allclose(out[0], out[1])

    def test_causal_attention(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64, causal=True)
        x = torch.randn(1, 10, 64)
        pos = torch.arange(10).unsqueeze(0)
        _, weights, _ = attn(x, position_ids=pos)
        for i in range(10):
            for j in range(i + 1, 10):
                assert weights[0, :, i, j].sum() < 1e-6

    def test_use_cache(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(1, 5, 64)
        pos = torch.arange(5).unsqueeze(0)
        _, _, cache = attn(x, position_ids=pos, use_cache=True)
        x2 = torch.randn(1, 1, 64)
        pos2 = torch.tensor([[5]])
        _, _, cache2 = attn(x2, position_ids=pos2, past_key_value=cache, use_cache=True)
        assert cache2.size == 6

    def test_no_cache(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(1, 5, 64)
        pos = torch.arange(5).unsqueeze(0)
        _, _, cache = attn(x, position_ids=pos, use_cache=False)
        assert cache is None


class TestGroupedQueryAttention:
    def test_kv_heads_less_than_q_heads(self):
        attn = GroupedQueryAttention(hidden_size=64, num_heads=8, num_key_value_heads=2, head_dim=8, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, _, _ = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_single_kv_head(self):
        attn = GroupedQueryAttention(hidden_size=64, num_heads=8, num_key_value_heads=1, head_dim=8, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, _, _ = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_equal_heads(self):
        attn = GroupedQueryAttention(hidden_size=64, num_heads=8, num_key_value_heads=8, head_dim=8, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, _, _ = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_error_kv_exceeds_q(self):
        try:
            attn = GroupedQueryAttention(hidden_size=64, num_heads=4, num_key_value_heads=8, head_dim=16, max_position_embeddings=64)
            assert False
        except ValueError:
            pass


class TestMultiQueryAttention:
    def test_forward(self):
        attn = MultiQueryAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, _, _ = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_shared_kv(self):
        attn = MultiQueryAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(1, 5, 64)
        pos = torch.arange(5).unsqueeze(0)
        out, weights, _ = attn(x, position_ids=pos)
        assert weights.shape[1] == 4


class TestKVCache:
    def test_empty_cache(self):
        cache = KVCache()
        assert cache.size == 0
        assert cache.cache is None

    def test_single_update(self):
        cache = KVCache()
        k = torch.randn(1, 4, 5, 16)
        v = torch.randn(1, 4, 5, 16)
        k_out, v_out = cache.update(k, v)
        assert k_out.shape == (1, 4, 5, 16)
        assert v_out.shape == (1, 4, 5, 16)

    def test_sequential_updates(self):
        cache = KVCache()
        for i in range(10):
            k = torch.randn(1, 4, 1, 16)
            v = torch.randn(1, 4, 1, 16)
            k_out, v_out = cache.update(k, v)
            assert k_out.shape[2] == i + 1

    def test_batch_preserved(self):
        cache = KVCache()
        k = torch.randn(2, 4, 5, 16)
        v = torch.randn(2, 4, 5, 16)
        cache.update(k, v)
        assert cache.size == 5

    def test_reset(self):
        cache = KVCache()
        cache.update(torch.randn(1, 4, 5, 16), torch.randn(1, 4, 5, 16))
        cache.reset()
        assert cache.size == 0
        assert cache.cache is None

    def test_multiple_resets(self):
        cache = KVCache()
        for _ in range(5):
            cache.update(torch.randn(1, 4, 3, 16), torch.randn(1, 4, 3, 16))
            cache.reset()
            assert cache.size == 0

    def test_get_max_cache(self):
        cache = KVCache(max_cache_size=10)
        k = torch.randn(1, 4, 5, 16)
        v = torch.randn(1, 4, 5, 16)
        cache.update(k, v)
        assert cache.size == 5
        assert cache.get_max_cache() == 10

    def test_repr(self):
        cache = KVCache()
        r = repr(cache)
        assert "KVCache" in r
        cache.update(torch.randn(1, 4, 5, 16), torch.randn(1, 4, 5, 16))
        r2 = repr(cache)
        assert "5" in r2


class TestRotaryEmbedding:
    def test_forward(self):
        rope = RotaryEmbedding(dim=32, max_position_embeddings=128)
        x = torch.randn(2, 4, 10, 32)
        pos = torch.arange(10).unsqueeze(0).expand(2, 10)
        cos, sin = rope(x, pos)
        assert cos.shape == (2, 1, 10, 64)
        assert sin.shape == (2, 1, 10, 64)

    def test_zero_position(self):
        rope = RotaryEmbedding(dim=32)
        x = torch.randn(1, 1, 1, 32)
        pos = torch.zeros(1, 1, dtype=torch.long)
        cos, sin = rope(x, pos)
        assert torch.allclose(cos, torch.ones_like(cos), atol=1e-6)
        assert torch.allclose(sin, torch.zeros_like(sin), atol=1e-6)

    def test_apply_rope_rotates(self):
        q = torch.randn(1, 1, 3, 4)
        k = torch.randn(1, 1, 3, 4)
        cos = torch.randn(1, 1, 3, 8)
        sin = torch.randn(1, 1, 3, 8)
        q_out, k_out = apply_rotary_pos_emb(q, k, cos, sin)
        assert q_out.shape == q.shape
        assert k_out.shape == k.shape
        assert not torch.allclose(q_out, q)


class TestFlashAttention:
    def test_forward(self):
        attn = FlashAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, weights, _ = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_causal(self):
        attn = FlashAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64, causal=True)
        x = torch.randn(1, 10, 64)
        pos = torch.arange(10).unsqueeze(0)
        out, _, _ = attn(x, position_ids=pos)
        assert out.shape == (1, 10, 64)

    def test_with_mask(self):
        attn = FlashAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        mask = torch.ones(2, 1, 10, 10)
        out, _, _ = attn(x, attention_mask=mask, position_ids=pos)
        assert out.shape == (2, 10, 64)


class TestSparseAttention:
    def test_forward(self):
        attn = SparseAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64, sparsity_factor=2)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, _, _ = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_strided_sparsity(self):
        attn = SparseAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=128, sparsity_pattern="strided", sparsity_factor=2)
        x = torch.randn(1, 20, 64)
        pos = torch.arange(20).unsqueeze(0)
        out, weights, _ = attn(x, position_ids=pos)
        n_zero = (weights == 0).sum().item()
        assert n_zero > 0


class TestSlidingWindowAttention:
    def test_forward(self):
        attn = SlidingWindowAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64, window_size=8)
        x = torch.randn(2, 20, 64)
        pos = torch.arange(20).unsqueeze(0).expand(2, -1)
        out, weights, _ = attn(x, position_ids=pos)
        assert out.shape == (2, 20, 64)

    def test_window_limits_attention(self):
        attn = SlidingWindowAttention(hidden_size=64, num_heads=2, head_dim=16, max_position_embeddings=64, window_size=4)
        x = torch.randn(1, 20, 64)
        pos = torch.arange(20).unsqueeze(0)
        _, weights, _ = attn(x, position_ids=pos)
        n_possible = (weights[0, 0] > 0).sum(dim=-1)
        assert (n_possible <= 5).all()


class TestAlibiAttention:
    def test_forward(self):
        attn = AlibiAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, weights, _ = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)
        assert weights.shape == (2, 4, 10, 10)

    def test_alibi_bias_applied(self):
        attn = AlibiAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(1, 10, 64)
        pos = torch.arange(10).unsqueeze(0)
        _, weights, _ = attn(x, position_ids=pos)
        for h in range(1, 4):
            assert not torch.allclose(weights[0, 0], weights[0, h])
