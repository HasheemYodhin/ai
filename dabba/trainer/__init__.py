"""
Training engine for decoder-only transformer models.

Provides the full training loop with AdamW optimizer, learning rate
scheduling, mixed precision, gradient clipping, checkpointing,
validation, early stopping, and TensorBoard logging.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import torch
import torch.nn.functional as F

from dabba.trainer.optimizer import AdamW
from dabba.trainer.lr_scheduler import LRScheduler
from dabba.trainer.train_step import TrainStep
from dabba.trainer.checkpoint import CheckpointManager
from dabba.trainer.validator import Validator
from dabba.trainer.metrics import MetricsTracker


@dataclass
class TrainerConfig:
    learning_rate: float = 1e-4
    batch_size: int = 4
    num_epochs: int = 1
    log_interval: int = 10
    eval_interval: int = 1
    max_grad_norm: float = 1.0
    weight_decay: float = 0.01
    output_dir: str = "./checkpoints"


class Trainer:
    """High-level training loop for any nn.Module."""

    def __init__(self, model: torch.nn.Module, config: TrainerConfig):
        self.model = model
        self.config = config
        self.optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )

    def train(self, train_data: List[Dict], eval_data: Optional[List[Dict]] = None) -> Dict:
        history: Dict[str, List] = {"train_loss": []}
        for epoch in range(self.config.num_epochs):
            self.model.train()
            epoch_losses = []
            for i in range(0, len(train_data), self.config.batch_size):
                batch = train_data[i : i + self.config.batch_size]
                self.optimizer.zero_grad()
                for item in batch:
                    inp = item["input_ids"]
                    lbl = item["labels"]
                    if inp.dim() == 1:
                        inp = inp.unsqueeze(0)
                        lbl = lbl.unsqueeze(0)
                    out = self.model(inp)
                    loss = F.mse_loss(out, lbl)
                    loss.backward()
                    epoch_losses.append(loss.item())
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.max_grad_norm)
                self.optimizer.step()
            history["train_loss"].extend(epoch_losses)

            if eval_data is not None and (epoch + 1) % self.config.eval_interval == 0:
                metrics = self.evaluate(eval_data)
                history.setdefault("eval_loss", []).append(metrics["eval_loss"])

        return history

    def evaluate(self, eval_data: List[Dict]) -> Dict:
        self.model.eval()
        losses = []
        with torch.no_grad():
            for item in eval_data:
                inp = item["input_ids"]
                lbl = item["labels"]
                if inp.dim() == 1:
                    inp = inp.unsqueeze(0)
                    lbl = lbl.unsqueeze(0)
                out = self.model(inp)
                losses.append(F.mse_loss(out, lbl).item())
        return {"eval_loss": sum(losses) / len(losses) if losses else 0.0}


__all__ = [
    "AdamW",
    "LRScheduler",
    "TrainStep",
    "CheckpointManager",
    "Validator",
    "MetricsTracker",
    "TrainerConfig",
    "Trainer",
]
