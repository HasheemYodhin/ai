"""
Validation loop for evaluating model performance during training.
Computes loss and perplexity on a validation dataset.
"""

import math
from typing import Dict, Optional

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.cuda.amp import autocast

from dabba.utils.logging import get_logger


class Validator:
    """
    Runs validation during training to evaluate model performance.

    Computes validation loss, perplexity, and accuracy on a held-out
    dataset. Used for early stopping and model selection.

    Args:
        model: The model to validate.
        loss_fn: Optional custom loss function (default: cross-entropy).
        use_amp: Use mixed precision for validation.
        amp_dtype: AMP data type.
        eval_iters: Number of batches to evaluate (-1 for entire dataset).
    """

    def __init__(
        self,
        model: nn.Module,
        loss_fn: Optional[callable] = None,
        use_amp: bool = True,
        amp_dtype: str = "bfloat16",
        eval_iters: int = 100,
    ):
        self.model = model
        self.loss_fn = loss_fn or self._default_loss
        self.use_amp = use_amp
        self.eval_iters = eval_iters
        self.logger = get_logger("dabba.trainer")

        self.amp_dtype = (
            torch.bfloat16 if amp_dtype == "bfloat16"
            else torch.float16 if amp_dtype == "float16"
            else torch.float32
        )

    def validate(
        self,
        dataloader: DataLoader,
        max_batches: Optional[int] = None,
    ) -> Dict[str, float]:
        """
        Run validation on the given dataloader.

        Args:
            dataloader: DataLoader for validation data.
            max_batches: Maximum batches to evaluate (overrides eval_iters).

        Returns:
            Dictionary with "loss", "perplexity", and "accuracy".
        """
        self.model.eval()
        total_loss = 0.0
        total_tokens = 0
        total_correct = 0
        num_batches = 0

        max_batches = max_batches or self.eval_iters

        with torch.no_grad():
            for batch_idx, batch in enumerate(dataloader):
                if max_batches > 0 and batch_idx >= max_batches:
                    break

                input_ids = batch["input_ids"]
                labels = batch["labels"]
                attention_mask = batch.get("attention_mask")

                input_ids = input_ids.to(self.model.device if hasattr(self.model, 'device') else next(self.model.parameters()).device)
                labels = labels.to(input_ids.device)

                with autocast(
                    enabled=self.use_amp,
                    dtype=self.amp_dtype,
                ):
                    outputs = self.model(
                        input_ids=input_ids,
                        attention_mask=attention_mask.to(input_ids.device) if attention_mask is not None else None,
                    )
                    logits = outputs["logits"]

                    loss = self.loss_fn(logits, labels)

                total_loss += loss.item()
                num_batches += 1

                predictions = logits.argmax(dim=-1)
                mask = labels != -100
                total_correct += (predictions[mask] == labels[mask]).sum().item()
                total_tokens += mask.sum().item()

        avg_loss = total_loss / max(num_batches, 1)
        perplexity = math.exp(avg_loss) if avg_loss < 100 else float("inf")
        accuracy = total_correct / max(total_tokens, 1)

        self.logger.info(
            f"Validation | Loss: {avg_loss:.4f} | "
            f"Perplexity: {perplexity:.2f} | "
            f"Accuracy: {accuracy:.4f}"
        )

        self.model.train()
        return {
            "loss": avg_loss,
            "perplexity": perplexity,
            "accuracy": accuracy,
        }

    def _default_loss(
        self,
        logits: torch.Tensor,
        labels: torch.Tensor,
    ) -> torch.Tensor:
        """
        Default cross-entropy loss computation.

        Args:
            logits: Shape (batch_size, seq_length, vocab_size).
            labels: Shape (batch_size, seq_length) with -100 for ignored tokens.

        Returns:
            Scalar loss.
        """
        shift_logits = logits[..., :-1, :].contiguous()
        shift_labels = labels[..., 1:].contiguous()
        return nn.functional.cross_entropy(
            shift_logits.view(-1, shift_logits.size(-1)),
            shift_labels.view(-1),
            ignore_index=-100,
        )
