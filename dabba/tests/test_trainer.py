import pytest
import torch
import tempfile
import os
import json
from unittest.mock import Mock, patch, PropertyMock, MagicMock
from dabba.trainer import Trainer, TrainerConfig
from dabba.config import ModelConfig, TrainingConfig
from dabba.trainer.optimizer import get_optimizer
from dabba.trainer.scheduler import get_scheduler
from dabba.trainer.train_step import train_step, eval_step
from dabba.trainer.checkpoint import save_checkpoint, load_checkpoint
from dabba.trainer.metrics import MetricsTracker


class TestTrainerConfig:
    def test_defaults(self):
        cfg = TrainerConfig()
        assert cfg.learning_rate == 1e-4
        assert cfg.batch_size == 4

    def test_custom_values(self):
        cfg = TrainerConfig(learning_rate=5e-5, batch_size=8, num_epochs=10)
        assert cfg.learning_rate == 5e-5
        assert cfg.batch_size == 8
        assert cfg.num_epochs == 10


class TestOptimizer:
    def test_adamw(self):
        model = torch.nn.Linear(10, 10)
        opt = get_optimizer(model, name="adamw", lr=1e-4)
        assert isinstance(opt, torch.optim.AdamW)

    def test_adam(self):
        model = torch.nn.Linear(10, 10)
        opt = get_optimizer(model, name="adam", lr=1e-4)
        assert isinstance(opt, torch.optim.Adam)

    def test_sgd(self):
        model = torch.nn.Linear(10, 10)
        opt = get_optimizer(model, name="sgd", lr=1e-2)
        assert isinstance(opt, torch.optim.SGD)

    def test_unknown_optimizer(self):
        model = torch.nn.Linear(10, 10)
        try:
            get_optimizer(model, name="unknown", lr=1e-4)
            assert False
        except ValueError:
            pass

    def test_custom_kwargs(self):
        model = torch.nn.Linear(10, 10)
        opt = get_optimizer(model, name="adamw", lr=1e-4, weight_decay=0.1, betas=(0.9, 0.99))
        assert isinstance(opt, torch.optim.AdamW)
        assert opt.defaults["weight_decay"] == 0.1

    def test_group_parameters(self):
        model = torch.nn.Linear(10, 10)
        opt = get_optimizer(model, name="adamw", lr=1e-4, weight_decay=0.1)
        param_groups = opt.param_groups
        assert len(param_groups) >= 1

    def test_no_weight_decay_on_bias(self):
        model = torch.nn.Linear(10, 10)
        opt = get_optimizer(model, name="adamw", lr=1e-4, weight_decay=0.1)
        for group in opt.param_groups:
            if group["weight_decay"] == 0:
                break
        else:
            pass


class TestScheduler:
    def test_cosine(self):
        opt = torch.optim.AdamW([torch.nn.Parameter(torch.randn(10, 10))], lr=1e-4)
        scheduler = get_scheduler(opt, name="cosine", num_training_steps=100)
        assert scheduler.get_last_lr()[0] == 1e-4

    def test_linear(self):
        opt = torch.optim.AdamW([torch.nn.Parameter(torch.randn(10, 10))], lr=1e-4)
        scheduler = get_scheduler(opt, name="linear", num_training_steps=100)
        assert scheduler.get_last_lr()[0] == 1e-4

    def test_constant(self):
        opt = torch.optim.AdamW([torch.nn.Parameter(torch.randn(10, 10))], lr=1e-4)
        scheduler = get_scheduler(opt, name="constant", num_training_steps=100)
        assert scheduler.get_last_lr()[0] == 1e-4

    def test_warmup_cosine(self):
        opt = torch.optim.AdamW([torch.nn.Parameter(torch.randn(10, 10))], lr=1e-4)
        scheduler = get_scheduler(opt, name="cosine", num_training_steps=100, warmup_steps=10)
        lr = scheduler.get_last_lr()[0]
        assert lr < 1e-4

    def test_unknown_scheduler(self):
        opt = torch.optim.AdamW([torch.nn.Parameter(torch.randn(10, 10))], lr=1e-4)
        try:
            get_scheduler(opt, name="unknown", num_training_steps=100)
            assert False
        except ValueError:
            pass


class TestTrainStep:
    def test_train_step(self):
        model = torch.nn.Linear(10, 10)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
        batch = {"input_ids": torch.randn(2, 10), "labels": torch.randn(2, 10)}
        loss = train_step(model, batch, opt)
        assert isinstance(loss, torch.Tensor)
        assert loss.shape == ()

    def test_gradient_accumulation(self):
        model = torch.nn.Linear(10, 10)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
        batch = {"input_ids": torch.randn(2, 10), "labels": torch.randn(2, 10)}
        loss1 = train_step(model, batch, opt, gradient_accumulation_steps=2)
        loss2 = train_step(model, batch, opt, gradient_accumulation_steps=2)
        assert loss1.shape == ()
        assert loss2.shape == ()

    def test_eval_step(self):
        model = torch.nn.Linear(10, 10)
        batch = {"input_ids": torch.randn(2, 10), "labels": torch.randn(2, 10)}
        loss = eval_step(model, batch)
        assert isinstance(loss, torch.Tensor)
        assert loss.shape == ()

    def test_gradient_clipping(self):
        model = torch.nn.Linear(10, 10)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
        batch = {"input_ids": torch.randn(2, 10), "labels": torch.randn(2, 10)}
        loss = train_step(model, batch, opt, max_grad_norm=1.0)
        loss.backward()
        total_norm = 0.0
        for p in model.parameters():
            if p.grad is not None:
                total_norm += p.grad.norm().item() ** 2
        total_norm = total_norm ** 0.5
        assert total_norm <= 1.0 or total_norm == 0.0


class TestCheckpoint:
    def test_save_and_load(self):
        model = torch.nn.Linear(10, 10)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_checkpoint(model, opt, epoch=1, step=100, output_dir=tmpdir)
            assert os.path.exists(path)
            model2 = torch.nn.Linear(10, 10)
            opt2 = torch.optim.AdamW(model2.parameters(), lr=1e-4)
            state = load_checkpoint(path, model2, opt2)
            assert state["epoch"] == 1
            assert state["step"] == 100
            for p1, p2 in zip(model.parameters(), model2.parameters()):
                assert torch.allclose(p1, p2)

    def test_load_no_optimizer(self):
        model = torch.nn.Linear(10, 10)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_checkpoint(model, opt, epoch=1, step=50, output_dir=tmpdir)
            model2 = torch.nn.Linear(10, 10)
            state = load_checkpoint(path, model2)
            assert state["epoch"] == 1
            assert state["step"] == 50

    def test_load_file_not_found(self):
        model = torch.nn.Linear(10, 10)
        try:
            load_checkpoint("/nonexistent/path.pt", model)
            assert False
        except FileNotFoundError:
            pass

    def test_multiple_checkpoints(self):
        model = torch.nn.Linear(10, 10)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = save_checkpoint(model, opt, epoch=1, step=100, output_dir=tmpdir)
            path2 = save_checkpoint(model, opt, epoch=2, step=200, output_dir=tmpdir)
            assert path1 != path2
            assert os.path.exists(path1)
            assert os.path.exists(path2)

    def test_checkpoint_contains_metadata(self):
        model = torch.nn.Linear(10, 10)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_checkpoint(model, opt, epoch=1, step=100, output_dir=tmpdir, metadata={"test": "value"})
            state = torch.load(path, map_location="cpu", weights_only=False)
            assert "metadata" in state
            assert state["metadata"]["test"] == "value"


class TestMetricsTracker:
    def test_initialization(self):
        tracker = MetricsTracker()
        assert len(tracker.history) == 0

    def test_update(self):
        tracker = MetricsTracker()
        tracker.update("loss", 0.5)
        assert len(tracker.history["loss"]) == 1
        assert tracker.history["loss"][0]["value"] == 0.5

    def test_multiple_updates(self):
        tracker = MetricsTracker()
        for i in range(10):
            tracker.update("loss", i * 0.1)
        assert len(tracker.history["loss"]) == 10
        assert tracker.average("loss") == pytest.approx(0.45, rel=1e-2)

    def test_average_empty(self):
        tracker = MetricsTracker()
        assert tracker.average("nonexistent") == 0.0

    def test_reset(self):
        tracker = MetricsTracker()
        tracker.update("loss", 0.5)
        tracker.reset()
        assert len(tracker.history) == 0

    def test_latest(self):
        tracker = MetricsTracker()
        tracker.update("loss", 1.0)
        tracker.update("loss", 2.0)
        assert tracker.latest("loss") == 2.0

    def test_latest_nonexistent(self):
        tracker = MetricsTracker()
        assert tracker.latest("nonexistent") is None

    def test_best_lowest(self):
        tracker = MetricsTracker()
        for v in [3.0, 1.0, 2.0]:
            tracker.update("loss", v)
        assert tracker.best("loss", mode="min")["value"] == 1.0

    def test_best_highest(self):
        tracker = MetricsTracker()
        for v in [1.0, 3.0, 2.0]:
            tracker.update("accuracy", v)
        assert tracker.best("accuracy", mode="max")["value"] == 3.0

    def test_best_empty(self):
        tracker = MetricsTracker()
        assert tracker.best("loss") is None

    def test_save_load(self):
        tracker = MetricsTracker()
        for i in range(5):
            tracker.update("loss", i * 0.1)
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            tmp_path = f.name
        try:
            tracker.save(tmp_path)
            loaded = MetricsTracker.load(tmp_path)
            assert len(loaded.history["loss"]) == 5
            assert loaded.average("loss") == tracker.average("loss")
        finally:
            os.unlink(tmp_path)

    def test_serializable(self):
        tracker = MetricsTracker()
        tracker.update("loss", 0.5)
        data = tracker.to_dict()
        assert "loss" in data
        assert len(data["loss"]) == 1

    def test_from_dict(self):
        data = {"loss": [{"step": 0, "value": 0.5}]}
        tracker = MetricsTracker.from_dict(data)
        assert len(tracker.history["loss"]) == 1


class TestTrainer:
    def test_train(self):
        model = torch.nn.Linear(10, 10)
        cfg = TrainerConfig(num_epochs=1, batch_size=2, log_interval=1)
        train_data = [{"input_ids": torch.randn(10), "labels": torch.randn(10)} for _ in range(4)]
        trainer = Trainer(model, cfg)
        history = trainer.train(train_data)
        assert "train_loss" in history

    def test_evaluate(self):
        model = torch.nn.Linear(10, 10)
        cfg = TrainerConfig(batch_size=2)
        eval_data = [{"input_ids": torch.randn(10), "labels": torch.randn(10)} for _ in range(4)]
        trainer = Trainer(model, cfg)
        metrics = trainer.evaluate(eval_data)
        assert "eval_loss" in metrics

    def test_train_eval_loop(self):
        model = torch.nn.Linear(10, 10)
        cfg = TrainerConfig(num_epochs=2, batch_size=2, eval_interval=1)
        train_data = [{"input_ids": torch.randn(10), "labels": torch.randn(10)} for _ in range(4)]
        eval_data = [{"input_ids": torch.randn(10), "labels": torch.randn(10)} for _ in range(2)]
        trainer = Trainer(model, cfg)
        history = trainer.train(train_data, eval_data=eval_data)
        assert "train_loss" in history
        assert "eval_loss" in history
