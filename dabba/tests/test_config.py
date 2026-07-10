import os
import json
import tempfile
import yaml
from dabba.config import ModelConfig, TrainingConfig, DataConfig


class TestModelConfig:
    def test_default_config(self):
        cfg = ModelConfig()
        assert cfg.vocab_size == 32000
        assert cfg.hidden_size == 768
        assert cfg.num_layers == 12
        assert cfg.num_attention_heads == 12
        assert cfg.num_key_value_heads == 12
        assert cfg.head_dim == 64
        assert cfg.intermediate_size is not None
        assert cfg.tie_word_embeddings is True

    def test_from_preset_tiny(self):
        cfg = ModelConfig.from_preset("tiny")
        assert cfg.hidden_size == 256
        assert cfg.num_layers == 6
        assert cfg.num_attention_heads == 8
        assert cfg.num_key_value_heads == 4

    def test_from_preset_small(self):
        cfg = ModelConfig.from_preset("small")
        assert cfg.hidden_size == 512
        assert cfg.num_layers == 12

    def test_from_preset_base(self):
        cfg = ModelConfig.from_preset("base")
        assert cfg.hidden_size == 768
        assert cfg.num_layers == 12
        assert cfg.num_attention_heads == 12

    def test_from_preset_medium(self):
        cfg = ModelConfig.from_preset("medium")
        assert cfg.hidden_size == 1024
        assert cfg.num_layers == 24

    def test_from_preset_large(self):
        cfg = ModelConfig.from_preset("large")
        assert cfg.hidden_size == 2048
        assert cfg.num_layers == 24

    def test_from_preset_xl(self):
        cfg = ModelConfig.from_preset("xl")
        assert cfg.hidden_size == 3200
        assert cfg.num_layers == 32

    def test_from_preset_xxl(self):
        cfg = ModelConfig.from_preset("xxl")
        assert cfg.hidden_size == 4096
        assert cfg.num_layers == 32

    def test_from_preset_with_overrides(self):
        cfg = ModelConfig.from_preset("tiny", num_layers=12, hidden_size=512)
        assert cfg.num_layers == 12
        assert cfg.hidden_size == 512
        assert cfg.vocab_size == 32000

    def test_invalid_preset(self):
        try:
            ModelConfig.from_preset("nonexistent")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_custom_config(self):
        cfg = ModelConfig(
            vocab_size=50000,
            hidden_size=1024,
            num_layers=16,
            num_attention_heads=16,
            num_key_value_heads=4,
        )
        assert cfg.vocab_size == 50000
        assert cfg.hidden_size == 1024
        assert cfg.num_layers == 16
        assert cfg.head_dim == 64

    def test_gqa_head_dim(self):
        cfg = ModelConfig(hidden_size=1024, num_attention_heads=16, num_key_value_heads=4)
        assert cfg.head_dim == 64
        assert cfg.num_key_value_groups == 4

    def test_intermediate_size_auto(self):
        cfg = ModelConfig(hidden_size=768)
        assert cfg.intermediate_size is not None
        assert cfg.intermediate_size % 64 == 0

    def test_num_params_tiny(self):
        cfg = ModelConfig.from_preset("tiny")
        assert cfg.num_params > 0

    def test_num_params_scales_with_size(self):
        tiny = ModelConfig.from_preset("tiny")
        base = ModelConfig.from_preset("base")
        assert base.num_params > tiny.num_params


class TestTrainingConfig:
    def test_defaults(self):
        cfg = TrainingConfig()
        assert cfg.learning_rate == 3e-4
        assert cfg.weight_decay == 0.1
        assert cfg.batch_size == 32
        assert cfg.max_grad_norm == 1.0
        assert cfg.use_amp is True
        assert cfg.amp_dtype == "bfloat16"

    def test_eval_batch_size_defaults_to_batch_size(self):
        cfg = TrainingConfig()
        assert cfg.eval_batch_size == cfg.batch_size

    def test_custom_values(self):
        cfg = TrainingConfig(
            learning_rate=1e-4,
            batch_size=64,
            max_steps=10000,
            warmup_steps=500,
        )
        assert cfg.learning_rate == 1e-4
        assert cfg.batch_size == 64
        assert cfg.max_steps == 10000
        assert cfg.warmup_steps == 500

    def test_max_steps_override(self):
        cfg = TrainingConfig(num_epochs=3, max_steps=5000)
        assert cfg.max_steps == 5000


class TestDataConfig:
    def test_defaults(self):
        cfg = DataConfig()
        assert cfg.min_text_length == 50
        assert cfg.deduplicate is True
        assert cfg.dedup_method == "exact"
        assert cfg.chunk_strategy == "paragraph"
        assert cfg.streaming is True

    def test_custom_values(self):
        cfg = DataConfig(
            train_data_path="/data/train",
            chunk_size=1024,
            dedup_method="minhash",
            streaming=False,
        )
        assert cfg.train_data_path == "/data/train"
        assert cfg.chunk_size == 1024
        assert cfg.dedup_method == "minhash"
        assert cfg.streaming is False

    def test_file_extensions_default(self):
        cfg = DataConfig()
        assert ".txt" in cfg.file_extensions
        assert ".jsonl" in cfg.file_extensions
        assert ".json" in cfg.file_extensions


class TestConfigYAML:
    def test_save_and_load_yaml(self):
        from dabba.utils.config_loader import save_config, load_yaml
        import tempfile
        cfg = ModelConfig.from_preset("tiny")
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            tmp_path = f.name
        try:
            save_config(cfg, tmp_path)
            loaded = load_yaml(tmp_path)
            assert loaded["hidden_size"] == 256
            assert loaded["num_layers"] == 6
        finally:
            os.unlink(tmp_path)

    def test_load_full_config(self):
        from dabba.utils.config_loader import load_config
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(yaml.dump({
                "model": {"hidden_size": 512, "num_layers": 8, "num_attention_heads": 8},
                "training": {"batch_size": 16},
                "data": {"chunk_size": 1024},
            }))
            tmp_path = f.name
        try:
            model_cfg, train_cfg, data_cfg, optional = load_config(tmp_path)
            assert model_cfg.hidden_size == 512
            assert model_cfg.num_layers == 8
            assert train_cfg.batch_size == 16
            assert data_cfg.chunk_size == 1024
        finally:
            os.unlink(tmp_path)

    def test_load_config_with_preset(self):
        from dabba.utils.config_loader import load_config
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(yaml.dump({
                "training": {"batch_size": 64},
                "data": {},
            }))
            tmp_path = f.name
        try:
            model_cfg, train_cfg, data_cfg, _ = load_config(tmp_path, model_preset="tiny")
            assert model_cfg.hidden_size == 256
            assert train_cfg.batch_size == 64
        finally:
            os.unlink(tmp_path)

    def test_preset_parameter_counts(self):
        counts = {
            "tiny": ModelConfig.from_preset("tiny").num_params,
            "small": ModelConfig.from_preset("small").num_params,
            "base": ModelConfig.from_preset("base").num_params,
            "medium": ModelConfig.from_preset("medium").num_params,
            "large": ModelConfig.from_preset("large").num_params,
        }
        assert counts["tiny"] < counts["small"]
        assert counts["small"] < counts["base"]
        assert counts["base"] < counts["medium"]
        assert counts["medium"] < counts["large"]
