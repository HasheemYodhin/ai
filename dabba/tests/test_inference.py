import torch
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from dabba.inference import Generator, GenerationConfig
from dabba.inference.samplers import (
    SamplerBase,
    GreedySampler,
    TopKSampler,
    TopPSampler,
    TemperatureSampler,
    BeamSampler,
)
from dabba.inference.beam_search import BeamSearch
from dabba.inference.streaming import StreamingHandler


class TestGenerationConfig:
    def test_defaults(self):
        cfg = GenerationConfig()
        assert cfg.max_length == 100
        assert cfg.temperature == 1.0
        assert cfg.top_k == 50
        assert cfg.top_p == 0.9

    def test_custom(self):
        cfg = GenerationConfig(max_length=200, temperature=0.8, do_sample=False)
        assert cfg.max_length == 200
        assert cfg.temperature == 0.8
        assert cfg.do_sample is False


class TestSamplers:
    def test_greedy_sampler(self):
        sampler = GreedySampler()
        logits = torch.randn(1, 10)
        token = sampler.sample(logits)
        assert isinstance(token, torch.Tensor)
        assert token.shape == (1,)

    def test_greedy_always_selects_max(self):
        sampler = GreedySampler()
        logits = torch.tensor([[1.0, 10.0, 2.0, 3.0]])
        token = sampler.sample(logits)
        assert token.item() == 1

    def test_temperature_sampler(self):
        sampler = TemperatureSampler(temperature=1.0)
        logits = torch.randn(1, 10)
        token = sampler.sample(logits)
        assert isinstance(token, torch.Tensor)
        assert token.shape == (1,)

    def test_temperature_zero(self):
        sampler = TemperatureSampler(temperature=0.0)
        logits = torch.tensor([[1.0, 10.0, 2.0]])
        token = sampler.sample(logits)
        assert token.item() == 1

    def test_temperature_low(self):
        sampler = TemperatureSampler(temperature=0.1)
        logits = torch.randn(2, 100)
        token = sampler.sample(logits)
        assert token.shape == (2,)

    def test_topk_sampler(self):
        sampler = TopKSampler(k=10)
        logits = torch.randn(1, 100)
        token = sampler.sample(logits)
        assert token.shape == (1,)

    def test_topk_filters(self):
        sampler = TopKSampler(k=1)
        logits = torch.tensor([[1.0, 10.0, 2.0, 3.0]])
        token = sampler.sample(logits)
        assert token.item() == 1

    def test_topk_with_temperature(self):
        sampler = TopKSampler(k=20, temperature=0.9)
        logits = torch.randn(2, 100)
        token = sampler.sample(logits)
        assert token.shape == (2,)

    def test_topp_sampler(self):
        sampler = TopPSampler(p=0.9)
        logits = torch.randn(1, 100)
        token = sampler.sample(logits)
        assert token.shape == (1,)

    def test_topp_p_one(self):
        sampler = TopPSampler(p=1.0)
        logits = torch.randn(1, 100)
        token = sampler.sample(logits)
        assert token.shape == (1,)

    def test_topp_with_temperature(self):
        sampler = TopPSampler(p=0.9, temperature=0.8)
        logits = torch.randn(2, 100)
        token = sampler.sample(logits)
        assert token.shape == (2,)

    def test_beam_sampler(self):
        sampler = BeamSampler(num_beams=3)
        logits = torch.randn(1, 100)
        tokens = sampler.sample(logits)
        assert tokens.shape == (1,)

    def test_sampler_base(self):
        class TestSampler(SamplerBase):
            def sample(self, logits):
                return torch.argmax(logits, dim=-1)

        sampler = TestSampler()
        logits = torch.randn(1, 10)
        result = sampler.sample(logits)
        assert result.shape == (1,)


class TestBeamSearch:
    def test_beam_search_basic(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        beam = BeamSearch(model, num_beams=3, max_length=5)
        input_ids = torch.randint(0, 100, (1, 5))
        output = beam.search(input_ids)
        assert output.shape[-1] >= 5
        assert output.shape[-1] <= 10

    def test_beam_search_early_stopping(self):
        model = MagicMock()
        eos_logits = torch.full((1, 1, 100), -float("inf"))
        eos_logits[0, 0, 2] = 0.0
        model.forward = MagicMock(return_value={"logits": eos_logits})
        beam = BeamSearch(model, num_beams=2, max_length=10, early_stopping=True)
        input_ids = torch.randint(0, 100, (1, 5))
        output = beam.search(input_ids)
        assert output.shape[-1] >= 5

    def test_beam_search_length_penalty(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        beam = BeamSearch(model, num_beams=3, max_length=10, length_penalty=1.0)
        input_ids = torch.randint(0, 100, (1, 5))
        output = beam.search(input_ids)
        assert output is not None

    def test_beam_search_no_repeat_ngram(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        beam = BeamSearch(model, num_beams=2, max_length=8, no_repeat_ngram_size=2)
        input_ids = torch.randint(0, 100, (1, 5))
        output = beam.search(input_ids)
        assert output is not None

    def test_beam_search_batch(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(2, 1, 100)})
        beam = BeamSearch(model, num_beams=2, max_length=5)
        input_ids = torch.randint(0, 100, (2, 5))
        output = beam.search(input_ids)
        assert output.shape[0] == 2


class TestGenerator:
    def test_generate_basic(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=10)
        assert output.shape[-1] >= 5
        assert output.shape[-1] <= 15

    def test_generate_with_temperature(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=8, temperature=0.8, do_sample=True)
        assert output.shape[-1] >= 5

    def test_generate_with_top_k(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=8, top_k=10, do_sample=True)
        assert output.shape[-1] >= 5

    def test_generate_with_top_p(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=8, top_p=0.9, do_sample=True)
        assert output.shape[-1] >= 5

    def test_generate_with_eos(self):
        model = MagicMock()
        eos_logits = torch.full((1, 1, 100), -float("inf"))
        eos_logits[0, 0, 2] = 0.0
        model.forward = MagicMock(return_value={"logits": eos_logits})
        gen = Generator(model, eos_token_id=2)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=50)
        assert output.shape[-1] >= 5

    def test_generate_with_pad_token_id(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model, pad_token_id=0, eos_token_id=2)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=10)
        assert output is not None

    def test_generate_batch(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(2, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (2, 5))
        output = gen.generate(input_ids, max_length=8)
        assert output.shape[0] == 2

    def test_generate_repetition_penalty(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=8, repetition_penalty=1.2)
        assert output is not None

    def test_generate_no_repeat_ngram(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=8, no_repeat_ngram_size=2)
        assert output is not None

    def test_generate_do_sample_false(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=10, do_sample=False)
        assert output.shape[-1] >= 5

    def test_generate_min_length(self):
        model = MagicMock()
        eos_logits = torch.full((1, 1, 100), -float("inf"))
        eos_logits[0, 0, 2] = 0.0
        model.forward = MagicMock(return_value={"logits": eos_logits})
        gen = Generator(model, eos_token_id=2)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=20, min_length=10)
        assert output.shape[-1] >= 10

    def test_generate_max_length(self):
        model = MagicMock()
        model.forward = MagicMock(return_value={"logits": torch.randn(1, 1, 100)})
        gen = Generator(model)
        input_ids = torch.randint(0, 100, (1, 5))
        output = gen.generate(input_ids, max_length=7)
        assert output.shape[-1] == 7


class TestStreamingHandler:
    def test_on_next_token(self):
        handler = StreamingHandler()
        results = []
        handler.on_next_token = lambda token: results.append(token)
        handler.on_next_token(1)
        handler.on_next_token(2)
        assert len(results) == 2

    def test_on_finished(self):
        handler = StreamingHandler()
        finished = []
        handler.on_finished = lambda: finished.append(True)
        handler.on_finished()
        assert finished == [True]

    def test_on_error(self):
        handler = StreamingHandler()
        errors = []
        handler.on_error = lambda e: errors.append(e)
        handler.on_error(Exception("test error"))
        assert len(errors) == 1

    def test_generate_streaming(self):
        model = MagicMock()
        model.forward.side_effect = [{"logits": torch.randn(1, 1, 100)} for _ in range(10)]
        gen = Generator(model)
        tokens = []
        input_ids = torch.randint(0, 100, (1, 5))
        for token in gen.generate_stream(input_ids, max_length=10):
            tokens.append(token)
        assert len(tokens) <= 5

    def test_streaming_handler_integration(self):
        handler = StreamingHandler()
        tokens = []
        handler.on_next_token = lambda t: tokens.append(t)
        handler.on_next_token(1)
        handler.on_next_token(2)
        handler.on_finished()
        assert len(tokens) == 2
