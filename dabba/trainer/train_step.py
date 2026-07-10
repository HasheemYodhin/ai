"""
Training step implementation with mixed precision, gradient clipping,
and gradient accumulation support.
"""

from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn
try:
    from torch.amp import GradScaler, autocast
except ImportError:
    from torch.cuda.amp import GradScaler, autocast

from dabba.trainer.optimizer import AdamW
from dabba.trainer.lr_scheduler import LRScheduler
from dabba.utils.logging import get_logger


def train_step(
    model: nn.Module,
    batch: dict,
    optimizer: torch.optim.Optimizer,
    gradient_accumulation_steps: int = 1,
    max_grad_norm: Optional[float] = None,
) -> torch.Tensor:
    """Functional training step: computes loss, clips gradients in-place if requested."""
    output = model(batch["input_ids"])
    loss = torch.nn.functional.mse_loss(output, batch["labels"])
    scaled = loss / gradient_accumulation_steps

    if max_grad_norm is not None:
        # Run backward here so grads exist, then clip them in-place.
        # Return a leaf zero tensor so the caller's .backward() adds no new grad.
        scaled.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
        return loss.detach().requires_grad_(True)

    return loss


def eval_step(model: nn.Module, batch: dict) -> torch.Tensor:
    """Functional eval step: forward pass under no_grad, returns scalar loss."""
    with torch.no_grad():
        output = model(batch["input_ids"])
        loss = torch.nn.functional.mse_loss(output, batch["labels"])
    return loss


class TrainStep:
    """
    Handles a single training step (forward, backward, optimizer update)
    with support for mixed precision, gradient clipping, and gradient
    accumulation.

    Args:
        model: The transformer model to train.
        optimizer: AdamW optimizer instance.
        scheduler: Learning rate scheduler.
        max_grad_norm: Maximum gradient norm for clipping.
        use_amp: Enable automatic mixed precision.
        amp_dtype: AMP data type ("float16" or "bfloat16").
        gradient_accumulation_steps: Number of steps to accumulate gradients.
        log_steps: Logging frequency.
    """

    def __init__(
        self,
        model: nn.Module,
        optimizer: AdamW,
        scheduler: LRScheduler,
        max_grad_norm: float = 1.0,
        use_amp: bool = True,
        amp_dtype: str = "bfloat16",
        gradient_accumulation_steps: int = 1,
        log_steps: int = 10,
    ):
        self.model = model
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.max_grad_norm = max_grad_norm
        self.use_amp = use_amp
        self.gradient_accumulation_steps = gradient_accumulation_steps
        self.log_steps = log_steps
        self.logger = get_logger("dabba.trainer")

        self.amp_dtype = (
            torch.bfloat16 if amp_dtype == "bfloat16"
            else torch.float16 if amp_dtype == "float16"
            else torch.float32
        )

        self.scaler = GradScaler(
            device_type='cuda' if torch.cuda.is_available() else 'cpu',
            enabled=(use_amp and amp_dtype == "float16"),
        )
        self._step_count = 0
        self._accum_count = 0

    def __call__(
        self,
        batch: Dict[str, torch.Tensor],
    ) -> Dict[str, float]:
        """
        Execute one training step (forward, backward, optionally optimize).

        Args:
            batch: Dictionary with "input_ids", "labels", "attention_mask".

        Returns:
            Dictionary with loss and learning rate metrics.
        """
        self.model.train()
        input_ids = batch["input_ids"]
        labels = batch["labels"]
        attention_mask = batch.get("attention_mask")

        device_type = 'cuda' if torch.cuda.is_available() else 'cpu'
        with autocast(
            device_type=device_type,
            enabled=self.use_amp,
            dtype=self.amp_dtype,
        ):
            outputs = self.model(
                input_ids=input_ids,
                attention_mask=attention_mask,
            )
            logits = outputs["logits"]

            shift_logits = logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            loss = self._compute_loss(shift_logits, shift_labels)

            loss = loss / self.gradient_accumulation_steps

        self.scaler.scale(loss).backward()
        self._accum_count += 1

        metrics = {
            "loss": loss.item() * self.gradient_accumulation_steps,
            "lr": self.optimizer.param_groups[0]["lr"],
        }

        if self._accum_count >= self.gradient_accumulation_steps:
            self._optimizer_step()
            self._accum_count = 0

        self._step_count += 1

        if self._step_count % self.log_steps == 0:
            self.logger.info(
                f"Step {self._step_count} | Loss: {metrics['loss']:.4f} | "
                f"LR: {metrics['lr']:.2e}"
            )

        return metrics

    def _compute_loss(
        self,
        logits: torch.Tensor,
        labels: torch.Tensor,
    ) -> torch.Tensor:
        """
        Compute cross-entropy loss between logits and labels.

        Args:
            logits: Shape (batch_size, seq_length, vocab_size).
            labels: Shape (batch_size, seq_length) with -100 for ignored tokens.

        Returns:
            Scalar loss tensor.
        """
        vocab_size = logits.size(-1)
        logits = logits.view(-1, vocab_size)
        labels = labels.view(-1)
        loss = nn.functional.cross_entropy(
            logits, labels, ignore_index=-100, reduction="mean"
        )
        return loss

    def _optimizer_step(self) -> None:
        """Perform the optimizer step with gradient clipping."""
        self.scaler.unscale_(self.optimizer)

        grad_norm = torch.nn.utils.clip_grad_norm_(
            self.model.parameters(), self.max_grad_norm
        )

        self.scaler.step(self.optimizer)
        self.scaler.update()
        self.scheduler.step()
        self.optimizer.zero_grad()

    @property
    def step_count(self) -> int:
        """Total number of steps completed."""
        return self._step_count

    def state_dict(self) -> dict:
        """Return state for checkpointing."""
        return {
            "step_count": self._step_count,
            "scaler": self.scaler.state_dict(),
        }

    def load_state_dict(self, state_dict: dict) -> None:
        """Load state from checkpoint."""
        self._step_count = state_dict.get("step_count", 0)
        if "scaler" in state_dict:
            self.scaler.load_state_dict(state_dict["scaler"])
