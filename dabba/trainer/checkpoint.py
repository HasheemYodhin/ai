"""
Checkpoint management for saving and resuming model training.

Provides checkpoint saving at regular intervals, best-model tracking,
automatic cleanup of old checkpoints, and full training state
serialization for resume capability.
"""

import datetime
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

import torch
import torch.nn as nn

from dabba.utils.logging import get_logger


class CheckpointManager:
    """
    Manages model checkpointing during training.

    Saves model state, optimizer state, scheduler state, and training
    metrics to disk at specified intervals. Supports resuming training
    from any checkpoint and maintains only the most recent N checkpoints.

    Args:
        output_dir: Directory to save checkpoints.
        save_steps: Save a checkpoint every N training steps.
        save_total_limit: Maximum number of checkpoints to keep (-1 for all).
        model: The model to checkpoint.
        optimizer: The optimizer to checkpoint.
        scheduler: The scheduler to checkpoint.
        train_step: Optional TrainStep to checkpoint.
    """

    def __init__(
        self,
        output_dir: str,
        save_steps: int = 1000,
        save_total_limit: int = 5,
        model: Optional[nn.Module] = None,
        optimizer: Optional[torch.optim.Optimizer] = None,
        scheduler: Optional[object] = None,
        train_step: Optional[object] = None,
    ):
        self.output_dir = Path(output_dir)
        self.save_steps = save_steps
        self.save_total_limit = save_total_limit
        self.model = model
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.train_step = train_step
        self.logger = get_logger("dabba.trainer")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._best_metric = float("inf")
        self._best_checkpoint = None

    def save(self, step: int, metrics: Dict[str, float], is_best: bool = False) -> str:
        """
        Save a training checkpoint.

        Args:
            step: Current training step.
            metrics: Dictionary of training metrics.
            is_best: Whether this is the best checkpoint so far.

        Returns:
            Path to the saved checkpoint directory.
        """
        checkpoint_dir = self.output_dir / f"checkpoint-{step}"
        checkpoint_dir.mkdir(exist_ok=True)

        if self.model is not None:
            model_state = self._get_model_state()
            torch.save(model_state, checkpoint_dir / "model.pt")

            config_path = self.output_dir / "config.json"
            if not config_path.exists():
                self._save_config(config_path)

        if self.optimizer is not None:
            torch.save(
                self.optimizer.state_dict(),
                checkpoint_dir / "optimizer.pt",
            )

        if self.scheduler is not None:
            torch.save(
                self.scheduler.state_dict(),
                checkpoint_dir / "scheduler.pt",
            )

        training_state = {
            "step": step,
            "metrics": metrics,
            "timestamp": datetime.datetime.now().isoformat(),
            "is_best": is_best,
        }

        if self.train_step is not None:
            training_state["train_step"] = self.train_step.state_dict()

        with open(checkpoint_dir / "training_state.json", "w") as f:
            json.dump(training_state, f, indent=2)

        self.logger.info(f"Saved checkpoint at step {step} to {checkpoint_dir}")

        if is_best:
            best_path = self.output_dir / "best"
            if best_path.exists():
                best_path.unlink()
            best_path.symlink_to(checkpoint_dir.name)
            self._best_checkpoint = str(checkpoint_dir)
            self._best_metric = metrics.get("eval_loss", metrics.get("loss", 0))

        self._cleanup_old_checkpoints()

        return str(checkpoint_dir)

    def _get_model_state(self) -> Dict:
        """
        Get model state dictionary including any non-parameter state.

        Returns:
            Model state dictionary.
        """
        state = {
            "model_state_dict": self.model.state_dict(),
            "model_config": getattr(self.model, "config", None),
        }
        if hasattr(self.model, "gradient_checkpointing"):
            state["gradient_checkpointing"] = self.model.gradient_checkpointing

        wrapped = getattr(self.model, "module", None)
        if wrapped is not None:
            state["model_state_dict"] = wrapped.state_dict()

        return state

    def _save_config(self, config_path: Path) -> None:
        """
        Save the model configuration to a JSON file.

        Args:
            config_path: Path to save the configuration.
        """
        if hasattr(self.model, "config") and self.model.config is not None:
            config = self.model.config
            if hasattr(config, "__dataclass_fields__"):
                config_dict = {
                    k: getattr(config, k)
                    for k in config.__dataclass_fields__
                }
            else:
                config_dict = config
            with open(config_path, "w") as f:
                json.dump(config_dict, f, indent=2, default=str)

    def _cleanup_old_checkpoints(self) -> None:
        """Remove oldest checkpoints if save_total_limit is exceeded."""
        if self.save_total_limit <= 0:
            return

        checkpoints = sorted([
            d for d in self.output_dir.iterdir()
            if d.is_dir() and d.name.startswith("checkpoint-")
        ], key=lambda d: int(d.name.split("-")[1]))

        while len(checkpoints) > self.save_total_limit:
            oldest = checkpoints.pop(0)
            import shutil
            shutil.rmtree(oldest)
            self.logger.info(f"Removed old checkpoint: {oldest}")

    def load_latest(self) -> Optional[int]:
        """
        Load the most recent checkpoint.

        Returns:
            Step number of the loaded checkpoint, or None if no checkpoint found.
        """
        checkpoints = sorted([
            d for d in self.output_dir.iterdir()
            if d.is_dir() and d.name.startswith("checkpoint-")
        ], key=lambda d: int(d.name.split("-")[1]))

        if not checkpoints:
            return None

        return self.load(str(checkpoints[-1]))

    def load(self, checkpoint_path: str) -> Optional[int]:
        """
        Load a specific checkpoint.

        Args:
            checkpoint_path: Path to the checkpoint directory.

        Returns:
            Step number of the loaded checkpoint.
        """
        checkpoint_dir = Path(checkpoint_path)
        if not checkpoint_dir.exists():
            self.logger.error(f"Checkpoint not found: {checkpoint_path}")
            return None

        model_path = checkpoint_dir / "model.pt"
        if model_path.exists() and self.model is not None:
            state = torch.load(model_path, map_location="cpu")
            model_state = (
                state["model_state_dict"]
                if "model_state_dict" in state
                else state
            )
            if hasattr(self.model, "module"):
                self.model.module.load_state_dict(model_state)
            else:
                self.model.load_state_dict(model_state)
            self.logger.info(f"Loaded model from {model_path}")

        optimizer_path = checkpoint_dir / "optimizer.pt"
        if optimizer_path.exists() and self.optimizer is not None:
            self.optimizer.load_state_dict(torch.load(
                optimizer_path, map_location="cpu"
            ))

        scheduler_path = checkpoint_dir / "scheduler.pt"
        if scheduler_path.exists() and self.scheduler is not None:
            self.scheduler.load_state_dict(torch.load(
                scheduler_path, map_location="cpu"
            ))

        training_state_path = checkpoint_dir / "training_state.json"
        if training_state_path.exists():
            with open(training_state_path, "r") as f:
                training_state = json.load(f)

            if self.train_step is not None and "train_step" in training_state:
                self.train_step.load_state_dict(training_state["train_step"])

            step = training_state.get("step", 0)
            self.logger.info(
                f"Loaded training state at step {step} "
                f"with metrics: {training_state.get('metrics', {})}"
            )
            return step

        return None

    def should_save(self, step: int) -> bool:
        """Check if a checkpoint should be saved at this step."""
        return step % self.save_steps == 0


def save_checkpoint(
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    epoch: int,
    step: int,
    output_dir: str,
    metadata: Optional[Dict] = None,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"checkpoint_epoch{epoch}_step{step}.pt")
    state = {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "epoch": epoch,
        "step": step,
    }
    if metadata is not None:
        state["metadata"] = metadata
    torch.save(state, path)
    return path


def load_checkpoint(
    path: str,
    model: nn.Module,
    optimizer: Optional[torch.optim.Optimizer] = None,
) -> Dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Checkpoint not found: {path}")
    state = torch.load(path, map_location="cpu", weights_only=False)
    model.load_state_dict(state["model_state_dict"])
    if optimizer is not None and "optimizer_state_dict" in state:
        optimizer.load_state_dict(state["optimizer_state_dict"])
    return state
