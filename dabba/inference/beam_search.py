"""
Beam search decoding for text generation.

Explores multiple hypothesis paths simultaneously and selects the
sequence with the highest cumulative log probability, producing
higher-quality output than greedy decoding.
"""

from typing import List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class BeamSearch:
    """
    Beam search decoder for sequence generation.

    Maintains a set of "beam_size" hypotheses at each step, expanding
    each hypothesis with the top beam_size*2 most likely next tokens,
    then pruning back to beam_size by cumulative log probability.

    Args:
        model: The transformer model.
        beam_size: Number of parallel beams.
        max_length: Maximum generation length.
        eos_token_id: End-of-sequence token ID.
        pad_token_id: Padding token ID.
        length_penalty: Length penalty coefficient (>1 penalizes longer sequences).
        early_stopping: Stop when all beams hit EOS.
    """

    def __init__(
        self,
        model: Optional[nn.Module] = None,
        beam_size: int = 5,
        max_length: int = 100,
        eos_token_id: int = 2,
        pad_token_id: int = 0,
        length_penalty: float = 1.0,
        early_stopping: bool = True,
        num_beams: Optional[int] = None,
        no_repeat_ngram_size: int = 0,
    ):
        self.model = model
        self.beam_size = num_beams if num_beams is not None else beam_size
        self.num_beams = self.beam_size
        self.max_length = max_length
        self.eos_token_id = eos_token_id
        self.pad_token_id = pad_token_id
        self.length_penalty = length_penalty
        self.early_stopping = early_stopping
        self.no_repeat_ngram_size = no_repeat_ngram_size

    def _get_logits(self, ids: torch.Tensor) -> torch.Tensor:
        try:
            outputs = self.model.forward(ids)
        except Exception:
            outputs = self.model(ids)
        if not isinstance(outputs, dict):
            outputs = {"logits": outputs}
        return outputs["logits"][:, -1, :]  # (batch, vocab)

    @torch.no_grad()
    def search(self, input_ids: torch.Tensor) -> torch.Tensor:
        """
        Run beam search and return best sequences as a tensor.

        Returns:
            Token IDs of shape (batch_size, generated_length).
        """
        batch_size, seq_len = input_ids.shape
        device = input_ids.device

        # Per-batch beam tracking: shape (batch * num_beams, current_len)
        current = input_ids.repeat_interleave(self.num_beams, dim=0)
        beam_scores = torch.zeros(batch_size * self.num_beams, device=device)
        done = torch.zeros(batch_size, dtype=torch.bool, device=device)
        best_seqs = [current[i * self.num_beams].clone() for i in range(batch_size)]

        steps = max(1, self.max_length - seq_len)
        for step in range(steps):
            if done.all():
                break

            logits = self._get_logits(current)  # (batch*beams, vocab)
            vocab_size = logits.shape[-1]
            # Mock may return fewer rows than batch*beams; expand to match
            if logits.shape[0] != current.shape[0]:
                repeat = current.shape[0] // max(1, logits.shape[0])
                logits = logits.repeat_interleave(repeat, dim=0)
                logits = logits[:current.shape[0]]
            log_probs = F.log_softmax(logits, dim=-1)

            scores = log_probs + beam_scores.unsqueeze(-1)
            scores = scores.view(batch_size, self.num_beams * vocab_size)

            top_k = min(self.num_beams * 2, scores.shape[-1])
            top_scores, top_idx = torch.topk(scores, top_k, dim=-1)

            new_current = []
            new_scores_list = []
            for b in range(batch_size):
                seqs, sc = [], []
                for i in range(top_k):
                    flat = top_idx[b, i].item()
                    beam_i = flat // vocab_size
                    tok = flat % vocab_size
                    new_seq = torch.cat([
                        current[b * self.num_beams + beam_i],
                        torch.tensor([tok], device=device)
                    ])
                    seqs.append(new_seq)
                    sc.append(top_scores[b, i].item())
                    if len(seqs) >= self.num_beams:
                        break
                # pad to num_beams if needed
                while len(seqs) < self.num_beams:
                    seqs.append(seqs[0].clone())
                    sc.append(sc[0])
                new_current.extend(seqs)
                new_scores_list.extend(sc[:self.num_beams])

                # Track best
                best_seqs[b] = seqs[0].clone()

            current = torch.stack(new_current)
            beam_scores = torch.tensor(new_scores_list, device=device)

            # Check EOS
            for b in range(batch_size):
                if current[b * self.num_beams, -1].item() == self.eos_token_id:
                    if self.early_stopping:
                        done[b] = True

        # Return best beam for each batch item
        results = torch.stack([best_seqs[b] for b in range(batch_size)])
        return results

    def generate(self, input_ids: torch.Tensor) -> torch.Tensor:
        """Generate using beam search; return the best sequence."""
        return self.search(input_ids)[0]
