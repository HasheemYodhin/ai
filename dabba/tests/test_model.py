import torch
from dabba.model import (
    TokenEmbedding,
    RotaryEmbedding,
    apply_rotary_pos_emb,
    RMSNorm,
    LayerNorm,
    MultiHeadAttention,
    GroupedQueryAttention,
    MultiQueryAttention,
    FeedForward,
    SwiGLU,
    GELU,
    DecoderBlock,
    Transformer,
    OutputHead,
    KVCache,
)
from dabba.config import ModelConfig


def _tiny_config():
    return ModelConfig(
        vocab_size=1000,
        hidden_size=64,
        num_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        intermediate_size=128,
        max_position_embeddings=128,
    )


class TestTokenEmbedding:
    def test_forward_shape(self):
        emb = TokenEmbedding(vocab_size=100, hidden_size=32)
        x = torch.randint(0, 100, (2, 10))
        out = emb(x)
        assert out.shape == (2, 10, 32)

    def test_padding_idx_zero(self):
        emb = TokenEmbedding(vocab_size=100, hidden_size=32, padding_idx=0)
        x = torch.tensor([[0, 1, 2]])
        out = emb(x)
        assert torch.allclose(out[:, 0], torch.zeros(32))


class TestRotaryEmbedding:
    def test_shape(self):
        rope = RotaryEmbedding(dim=32, max_position_embeddings=128)
        x = torch.randn(2, 4, 10, 32)
        pos = torch.arange(10).unsqueeze(0)
        cos, sin = rope(x, pos)
        assert cos.shape == (1, 1, 10, 64)
        assert sin.shape == (1, 1, 10, 64)

    def test_apply_rope_shape(self):
        q = torch.randn(2, 4, 10, 32)
        k = torch.randn(2, 2, 10, 32)
        cos = torch.randn(1, 1, 10, 64)
        sin = torch.randn(1, 1, 10, 64)
        q_out, k_out = apply_rotary_pos_emb(q, k, cos, sin)
        assert q_out.shape == q.shape
        assert k_out.shape == k.shape


class TestNormalization:
    def test_rmsnorm_shape(self):
        norm = RMSNorm(hidden_size=64)
        x = torch.randn(2, 10, 64)
        out = norm(x)
        assert out.shape == x.shape

    def test_rmsnorm_values(self):
        norm = RMSNorm(hidden_size=4, elementwise_affine=False)
        x = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
        out = norm(x)
        assert not torch.isnan(out).any()
        assert not torch.isinf(out).any()

    def test_layernorm_shape(self):
        norm = LayerNorm(hidden_size=64)
        x = torch.randn(2, 10, 64)
        out = norm(x)
        assert out.shape == x.shape


class TestAttention:
    def test_mha_forward_shape(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, weights, cache = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_mha_with_mask(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        mask = torch.zeros(2, 1, 10, 10)
        out, weights, cache = attn(x, attention_mask=mask, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_gqa_forward(self):
        attn = GroupedQueryAttention(hidden_size=64, num_heads=4, num_key_value_heads=2, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, weights, cache = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_mqa_forward(self):
        attn = MultiQueryAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, weights, cache = attn(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_kv_cache_update(self):
        cache = KVCache()
        k = torch.randn(2, 4, 5, 16)
        v = torch.randn(2, 4, 5, 16)
        k_out, v_out = cache.update(k, v)
        assert k_out.shape == (2, 4, 5, 16)
        k2 = torch.randn(2, 4, 1, 16)
        v2 = torch.randn(2, 4, 1, 16)
        k_out2, v_out2 = cache.update(k2, v2)
        assert k_out2.shape == (2, 4, 6, 16)

    def test_kv_cache_size(self):
        cache = KVCache()
        assert cache.size == 0
        cache.update(torch.randn(2, 4, 5, 16), torch.randn(2, 4, 5, 16))
        assert cache.size == 5

    def test_kv_cache_reset(self):
        cache = KVCache()
        cache.update(torch.randn(2, 4, 5, 16), torch.randn(2, 4, 5, 16))
        cache.reset()
        assert cache.size == 0

    def test_attention_use_cache(self):
        attn = MultiHeadAttention(hidden_size=64, num_heads=4, head_dim=16, max_position_embeddings=64)
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, _, cache = attn(x, position_ids=pos, use_cache=True)
        assert cache is not None


class TestFeedForward:
    def test_swiglu_shape(self):
        ffn = SwiGLU(hidden_size=64, intermediate_size=128)
        x = torch.randn(2, 10, 64)
        out = ffn(x)
        assert out.shape == (2, 10, 64)

    def test_gelu_shape(self):
        gelu = GELU()
        x = torch.randn(2, 10, 64)
        out = gelu(x)
        assert out.shape == (2, 10, 64)

    def test_feedforward_swiglu(self):
        ffn = FeedForward(hidden_size=64, intermediate_size=128, activation="silu")
        x = torch.randn(2, 10, 64)
        out = ffn(x)
        assert out.shape == (2, 10, 64)

    def test_feedforward_gelu(self):
        ffn = FeedForward(hidden_size=64, intermediate_size=128, activation="gelu")
        x = torch.randn(2, 10, 64)
        out = ffn(x)
        assert out.shape == (2, 10, 64)


class TestDecoderBlock:
    def test_forward_shape(self):
        block = DecoderBlock(
            hidden_size=64,
            num_attention_heads=4,
            num_key_value_heads=2,
            head_dim=16,
            intermediate_size=128,
            max_position_embeddings=64,
        )
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, cache = block(x, position_ids=pos)
        assert out.shape == (2, 10, 64)

    def test_forward_with_cache(self):
        block = DecoderBlock(
            hidden_size=64,
            num_attention_heads=4,
            num_key_value_heads=2,
            head_dim=16,
            intermediate_size=128,
            max_position_embeddings=64,
        )
        x = torch.randn(2, 10, 64)
        pos = torch.arange(10).unsqueeze(0).expand(2, -1)
        out, cache = block(x, position_ids=pos, use_cache=True)
        assert out.shape == (2, 10, 64)
        assert cache is not None


class TestTransformer:
    def test_forward_shape(self):
        config = _tiny_config()
        model = Transformer(config)
        x = torch.randint(0, config.vocab_size, (2, 16))
        output = model(x)
        assert output["logits"].shape == (2, 16, config.vocab_size)

    def test_forward_with_cache(self):
        config = _tiny_config()
        model = Transformer(config)
        x = torch.randint(0, config.vocab_size, (2, 16))
        output = model(x, use_cache=True)
        assert "past_key_values" in output
        assert len(output["past_key_values"]) == config.num_layers

    def test_weight_tying(self):
        config = _tiny_config()
        config.tie_word_embeddings = True
        model = Transformer(config)
        assert model.lm_head.is_tied

    def test_output_head_weight_tying(self):
        emb = TokenEmbedding(vocab_size=100, hidden_size=32)
        head = OutputHead(hidden_size=32, vocab_size=100, weight=emb.weight)
        assert head.is_tied
        x = torch.randn(2, 10, 32)
        logits = head(x)
        assert logits.shape == (2, 10, 100)

    def test_output_head_no_tying(self):
        head = OutputHead(hidden_size=32, vocab_size=100)
        assert not head.is_tied
        x = torch.randn(2, 10, 32)
        logits = head(x)
        assert logits.shape == (2, 10, 100)

    def test_backward(self):
        config = _tiny_config()
        model = Transformer(config)
        x = torch.randint(0, config.vocab_size, (2, 16))
        output = model(x)
        loss = output["logits"].mean()
        loss.backward()
        for p in model.parameters():
            if p.grad is not None:
                assert not torch.isnan(p.grad).any()
                break

    def test_get_num_params(self):
        config = _tiny_config()
        model = Transformer(config)
        n = model.get_num_params()
        assert n > 0

    def test_get_memory_footprint(self):
        config = _tiny_config()
        model = Transformer(config)
        mem = model.get_memory_footprint()
        assert mem > 0
