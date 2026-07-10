"""
Perplexity evaluation for autoregressive language models.

Computes the perplexity (exponential of the average negative log-likelihood)
of a model on a validation dataset. Supports sliding windows for long
sequences and per-document reporting.

Perplexity is defined as:
    PPL = exp(-1/N * sum(log P(token_i | token_{<i})))

where N is the number of tokens in the sequence and
P(token_i | token_{<i}) is the model's predicted probability of the
correct next token given the preceding tokens.
"""

import math
import time
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Tuple, Union

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, IterableDataset

from dabba.model.transformer import Transformer
from dabba.data.streaming_dataset import StreamingDataset


class PerplexityEvaluator:
    """
    Compute perplexity of a transformer model on a given dataset.

    Supports:
        - Standard perplexity on sequences up to model max_length.
        - Sliding window perplexity for sequences longer than model
          max_length (following the approach from Press et al., 2021).
        - Per-document reporting with aggregated statistics.
        - Token-level log-probability extraction.
        - Compatibility with StreamingDataset and standard DataLoader.

    Args:
        model: The transformer model to evaluate.
        stride: Stride for sliding window evaluation.
                Defaults to model's max_position_embeddings // 2.
        batch_size: Batch size for evaluation.
        device: Device to run evaluation on. Auto-detected if None.
        dtype: Torch dtype for evaluation.
    """

    def __init__(
        self,
        model: Transformer,
        stride: Optional[int] = None,
        batch_size: int = 4,
        device: Optional[torch.device] = None,
        dtype: torch.dtype = torch.float32,
    ):
        self.model = model
        self.max_length = model.config.max_position_embeddings
        self.stride = stride or (self.max_length // 2)
        self.batch_size = batch_size
        self.device = device or (
            torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
        )
        self.dtype = dtype

        self.model.to(self.device)
        self.model.eval()

    @torch.no_grad()
    def evaluate(
        self,
        dataset: Union[StreamingDataset, torch.utils.data.Dataset, DataLoader],
        max_batches: Optional[int] = None,
        verbose: bool = True,
    ) -> Dict[str, float]:
        """
        Compute perplexity on the entire dataset.

        Args:
            dataset: Dataset or DataLoader yielding dicts with
                     "input_ids" and optionally "labels".
            max_batches: Limit evaluation to this many batches.
            verbose: Print progress information.

        Returns:
            Dictionary with:
                - "perplexity": Overall perplexity score.
                - "loss": Average negative log-likelihood.
                - "num_tokens": Total number of evaluated tokens.
                - "num_sequences": Total number of sequences.
                - "wall_time_seconds": Evaluation wall time.
        """
        if isinstance(dataset, DataLoader):
            loader = dataset
        else:
            loader = DataLoader(
                dataset,
                batch_size=self.batch_size,
                num_workers=0,
            )

        total_loss = 0.0
        total_tokens = 0
        total_sequences = 0
        start_time = time.time()

        for batch_idx, batch in enumerate(loader):
            if max_batches is not None and batch_idx >= max_batches:
                break

            input_ids = batch["input_ids"].to(self.device)
            labels = batch.get("labels", input_ids.clone()).to(self.device)

            seq_len = input_ids.size(1)
            if seq_len > self.max_length:
                loss, tokens = self._sliding_window_loss(input_ids, labels)
            else:
                loss, tokens = self._sequence_loss(input_ids, labels)

            total_loss += loss
            total_tokens += tokens
            total_sequences += input_ids.size(0)

            if verbose and (batch_idx + 1) % 10 == 0:
                current_ppl = math.exp(total_loss / total_tokens) if total_tokens > 0 else float("inf")
                print(
                    f"  Batch {batch_idx + 1}: avg loss = {total_loss / total_tokens:.4f}, "
                    f"perplexity = {current_ppl:.2f}"
                )

        avg_loss = total_loss / total_tokens if total_tokens > 0 else float("inf")
        perplexity = math.exp(avg_loss) if avg_loss < 100 else float("inf")
        wall_time = time.time() - start_time

        return {
            "perplexity": perplexity,
            "loss": avg_loss,
            "num_tokens": total_tokens,
            "num_sequences": total_sequences,
            "wall_time_seconds": wall_time,
        }

    @torch.no_grad()
    def evaluate_per_document(
        self,
        documents: List[torch.Tensor],
        verbose: bool = True,
    ) -> List[Dict[str, float]]:
        """
        Compute per-document perplexity for a list of documents.

        Each document is a 1D tensor of token IDs.

        Args:
            documents: List of document token tensors.
            verbose: Print progress information.

        Returns:
            List of dictionaries with per-document metrics:
                - "perplexity"
                - "loss"
                - "num_tokens"
                - "num_windows" (for sliding window)
        """
        results = []

        for doc_idx, doc in enumerate(documents):
            if verbose and (doc_idx + 1) % 10 == 0:
                print(f"  Document {doc_idx + 1}/{len(documents)} (tokens: {doc.size(0)})")

            doc = doc.to(self.device)
            doc_len = doc.size(0)

            if doc_len <= self.max_length + 1:
                input_ids = doc[:-1].unsqueeze(0)
                labels = doc[1:].unsqueeze(0)
                loss, tokens = self._sequence_loss(input_ids, labels)
                num_windows = 1
            else:
                input_ids = doc[:-1].unsqueeze(0)
                labels = doc[1:].unsqueeze(0)
                loss, tokens = self._sliding_window_loss(input_ids, labels)
                num_windows = max(1, (doc_len - 1 - self.max_length) // self.stride + 1)

            avg_loss = loss / tokens if tokens > 0 else float("inf")
            ppl = math.exp(avg_loss) if avg_loss < 100 else float("inf")

            results.append({
                "perplexity": ppl,
                "loss": avg_loss,
                "num_tokens": tokens,
                "num_windows": num_windows,
            })

        return results

    @torch.no_grad()
    def evaluate_streaming(
        self,
        stream: Iterator[Dict[str, torch.Tensor]],
        num_steps: int = 100,
        verbose: bool = True,
    ) -> Dict[str, float]:
        """
        Evaluate perplexity from a streaming iterator.

        Useful for online evaluation during training.

        Args:
            stream: Iterator yielding dicts with "input_ids" and "labels".
            num_steps: Number of batches to evaluate.
            verbose: Print progress.

        Returns:
            Dictionary with perplexity statistics.
        """
        total_loss = 0.0
        total_tokens = 0
        start_time = time.time()

        for step in range(num_steps):
            try:
                batch = next(stream)
            except StopIteration:
                break

            input_ids = batch["input_ids"].to(self.device)
            labels = batch.get("labels", input_ids.clone()).to(self.device)

            seq_len = input_ids.size(1)
            if seq_len > self.max_length:
                loss, tokens = self._sliding_window_loss(input_ids, labels)
            else:
                loss, tokens = self._sequence_loss(input_ids, labels)

            total_loss += loss
            total_tokens += tokens

        avg_loss = total_loss / total_tokens if total_tokens > 0 else float("inf")
        perplexity = math.exp(avg_loss) if avg_loss < 100 else float("inf")
        wall_time = time.time() - start_time

        return {
            "perplexity": perplexity,
            "loss": avg_loss,
            "num_tokens": total_tokens,
            "num_steps": step + 1,
            "wall_time_seconds": wall_time,
        }

    @torch.no_grad()
    def get_token_log_probs(
        self,
        input_ids: torch.LongTensor,
    ) -> torch.Tensor:
        """
        Get per-token log probabilities from the model.

        Args:
            input_ids: Token IDs of shape (batch_size, seq_length).

        Returns:
            Log probabilities of shape (batch_size, seq_length - 1).
        """
        self.model.eval()
        input_ids = input_ids.to(self.device)

        with torch.no_grad():
            outputs = self.model(input_ids=input_ids)
            logits = outputs["logits"][:, :-1, :]
            target_ids = input_ids[:, 1:]

            log_probs = F.log_softmax(logits, dim=-1)
            token_log_probs = log_probs.gather(
                dim=-1, index=target_ids.unsqueeze(-1)
            ).squeeze(-1)

        return token_log_probs

    @torch.no_grad()
    def _sequence_loss(
        self,
        input_ids: torch.LongTensor,
        labels: torch.LongTensor,
    ) -> Tuple[float, int]:
        """
        Compute the negative log-likelihood loss for a single sequence.

        Args:
            input_ids: Token IDs of shape (batch_size, seq_length).
            labels: Target token IDs of shape (batch_size, seq_length).

        Returns:
            Tuple of (total_loss, num_tokens).
        """
        outputs = self.model(input_ids=input_ids)
        logits = outputs["logits"]

        loss = F.cross_entropy(
            logits.view(-1, logits.size(-1)),
            labels.view(-1),
            reduction="sum",
        )

        mask = (labels.view(-1) != -100).sum().item()
        num_tokens = mask if mask > 0 else labels.numel()

        return loss.item(), num_tokens

    @torch.no_grad()
    def _sliding_window_loss(
        self,
        input_ids: torch.LongTensor,
        labels: torch.LongTensor,
    ) -> Tuple[float, int]:
        """
        Compute loss using a sliding window for sequences that exceed
        the model's maximum context length.

        Each position is evaluated in at least one window. The final
        loss for each token is averaged across all windows that contain
        it.

        Reference:
            "Efficient Streaming Language Models with Attention Sinks"
            (Press et al., 2021)

        Args:
            input_ids: Token IDs of shape (batch_size, seq_length).
            labels: Target token IDs of shape (batch_size, seq_length).

        Returns:
            Tuple of (total_loss, num_tokens).
        """
        batch_size, seq_length = input_ids.shape
        total_loss = 0.0
        total_tokens = 0

        # Process the first window fully
        start = 0
        end = min(self.max_length, seq_length)

        outputs = self.model(input_ids=input_ids[:, start:end])
        logits = outputs["logits"]

        loss = F.cross_entropy(
            logits.view(-1, logits.size(-1)),
            labels[:, start:end].contiguous().view(-1),
            reduction="sum",
        )
        total_loss += loss.item()
        total_tokens += (end - start) * batch_size

        # Slide the window
        while end < seq_length:
            start = start + self.stride
            end = min(start + self.max_length, seq_length)

            outputs = self.model(input_ids=input_ids[:, start:end])
            logits = outputs["logits"]

            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)),
                labels[:, start:end].contiguous().view(-1),
                reduction="sum",
            )
            total_loss += loss.item()
            total_tokens += (end - start) * batch_size

        return total_loss, total_tokens

    def compute_perplexity(
        self,
        loss: float,
        num_tokens: int,
    ) -> float:
        """
        Compute perplexity from total loss and token count.

        Args:
            loss: Total negative log-likelihood.
            num_tokens: Number of tokens evaluated.

        Returns:
            Perplexity value.
        """
        if num_tokens == 0:
            return float("inf")
        avg_loss = loss / num_tokens
        if avg_loss >= 100:
            return float("inf")
        return math.exp(avg_loss)

    def summary(
        self,
        results: Dict[str, float],
    ) -> str:
        """
        Generate a human-readable summary of perplexity results.

        Args:
            results: Dictionary from evaluate().

        Returns:
            Formatted summary string.
        """
        lines = [
            "=" * 60,
            "Perplexity Evaluation Summary",
            "=" * 60,
            f"  Perplexity:          {results['perplexity']:.4f}",
            f"  Avg negative log-likelihood: {results['loss']:.4f}",
            f"  Total tokens:        {results['num_tokens']:,}",
            f"  Total sequences:     {results['num_sequences']:,}",
            f"  Wall time:           {results['wall_time_seconds']:.2f}s",
            "-" * 60,
        ]
        return "\n".join(lines)
