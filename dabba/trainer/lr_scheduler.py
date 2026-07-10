"""
Learning rate scheduler implementations.

Supports cosine decay with linear warmup, linear decay, and constant
learning rates — all configurable and compatible with the training loop.
"""

import math
from typing import Optional

import torch


class LRScheduler:
    """
    Learning rate scheduler with warmup and decay.

    Supports three decay styles:
        - cosine: Cosine annealing from peak LR to min LR
        - linear: Linear decay from peak LR to min LR
        - constant: Constant LR after warmup

    All schedules begin with a linear warmup from 0 to the peak LR.

    Args:
        optimizer: PyTorch optimizer to schedule.
        warmup_steps: Number of warmup steps.
        max_steps: Total number of training steps.
        lr_min_ratio: Minimum LR as a fraction of peak LR.
        decay_style: Type of decay ("cosine", "linear", "constant").
    """

    def __init__(
        self,
        optimizer: torch.optim.Optimizer,
        warmup_steps: int = 2000,
        max_steps: int = 100000,
        lr_min_ratio: float = 0.1,
        decay_style: str = "cosine",
    ):
        self.optimizer = optimizer
        self.warmup_steps = warmup_steps
        self.max_steps = max_steps
        self.lr_min_ratio = lr_min_ratio
        self.decay_style = decay_style
        self.base_lrs = [group["lr"] for group in optimizer.param_groups]
        self.current_step = 0

    def get_lr(self, step: Optional[int] = None) -> float:
        """
        Compute the learning rate for the given step.

        Args:
            step: Current training step. Uses internal counter if None.

        Returns:
            Learning rate value.
        """
        if step is None:
            step = self.current_step

        if step < self.warmup_steps:
            return self.base_lrs[0] * (step + 1) / self.warmup_steps

        if self.max_steps is not None and step > self.max_steps:
            step = self.max_steps

        progress = (step - self.warmup_steps) / max(
            1, (self.max_steps - self.warmup_steps)
        )
        progress = min(1.0, max(0.0, progress))

        lr_min = self.base_lrs[0] * self.lr_min_ratio

        if self.decay_style == "cosine":
            lr = lr_min + 0.5 * (self.base_lrs[0] - lr_min) * (
                1 + math.cos(math.pi * progress)
            )
        elif self.decay_style == "linear":
            lr = self.base_lrs[0] * (1 - progress) + lr_min * progress
        elif self.decay_style == "constant":
            lr = self.base_lrs[0]
        else:
            raise ValueError(f"Unknown decay style: {self.decay_style}")

        return lr

    def step(self) -> None:
        """Advance one step and update optimizer LR."""
        lr = self.get_lr()
        for param_group in self.optimizer.param_groups:
            param_group["lr"] = lr
        self.current_step += 1

    def state_dict(self) -> dict:
        """Return scheduler state for checkpointing."""
        return {
            "current_step": self.current_step,
            "warmup_steps": self.warmup_steps,
            "max_steps": self.max_steps,
            "lr_min_ratio": self.lr_min_ratio,
            "decay_style": self.decay_style,
            "base_lrs": self.base_lrs,
        }

    def load_state_dict(self, state_dict: dict) -> None:
        """Load scheduler state from checkpoint."""
        self.current_step = state_dict["current_step"]
        self.warmup_steps = state_dict["warmup_steps"]
        self.max_steps = state_dict["max_steps"]
        self.lr_min_ratio = state_dict["lr_min_ratio"]
        self.decay_style = state_dict["decay_style"]
        self.base_lrs = state_dict["base_lrs"]
