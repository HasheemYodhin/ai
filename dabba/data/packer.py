"""
Sequence packing module. Packs multiple variable-length sequences
into fixed-length sequences for efficient transformer training.

Packing concatenates short sequences and uses attention masks to
prevent cross-sequence attention. This improves training efficiency
by reducing padding overhead.
"""

from typing import Dict, List, Optional, Tuple
import torch


class SequencePacker:
    """
    Packs multiple short sequences into fixed-length sequences for
    efficient transformer training.

    Sequences are concatenated end-to-end with appropriate masking
    to prevent attention across sequence boundaries. This reduces
    the amount of padding needed and improves throughput.

    Usage:
        packer = SequencePacker(max_length=2048)
        packed = packer.pack(sequences)
    """

    def __init__(self, max_length: int = 2048):
        """
        Initialize the sequence packer.

        Args:
            max_length: Maximum packed sequence length.
        """
        self.max_length = max_length

    def pack(
        self, sequences: List[Dict[str, torch.Tensor]]
    ) -> Dict[str, torch.Tensor]:
        """
        Pack a list of sequences into a single fixed-length sequence.

        Each sequence dict should contain "input_ids" and "labels".

        Args:
            sequences: List of sequence dictionaries.

        Returns:
            Packed sequence with:
                - input_ids: Concatenated input IDs, truncated/padded to max_length
                - labels: Concatenated labels, truncated/padded to max_length
                - attention_mask: Binary mask (1 = real token, 0 = pad)
                - position_ids: Position IDs for each token
                - document_ids: Document boundary mask (1 = new doc starts here)
        """
        input_ids_list = []
        labels_list = []
        doc_boundaries = [1]

        total_length = 0
        for seq in sequences:
            seq_len = seq["input_ids"].size(0)
            if total_length + seq_len > self.max_length:
                break

            input_ids_list.append(seq["input_ids"])
            labels_list.append(seq["labels"])
            doc_boundaries.append(total_length + seq_len)
            total_length += seq_len

        if not input_ids_list:
            return self._make_packed([], [])

        input_ids = torch.cat(input_ids_list)[:self.max_length]
        labels = torch.cat(labels_list)[:self.max_length]
        actual_length = input_ids.size(0)

        padding_length = self.max_length - actual_length
        if padding_length > 0:
            input_ids = torch.cat(
                [input_ids, torch.zeros(padding_length, dtype=torch.long)]
            )
            labels = torch.cat(
                [labels, torch.full((padding_length,), -100, dtype=torch.long)]
            )

        attention_mask = torch.cat(
            [torch.ones(actual_length, dtype=torch.long),
             torch.zeros(padding_length, dtype=torch.long)]
        )

        position_ids = torch.cat(
            [torch.arange(actual_length, dtype=torch.long),
             torch.zeros(padding_length, dtype=torch.long)]
        )

        doc_mask = torch.zeros(self.max_length, dtype=torch.long)
        for boundary in doc_boundaries:
            if boundary < self.max_length:
                doc_mask[boundary] = 1

        return {
            "input_ids": input_ids,
            "labels": labels,
            "attention_mask": attention_mask,
            "position_ids": position_ids,
            "document_ids": doc_mask,
        }

    def _make_packed(
        self, input_ids_list: List[torch.Tensor], labels_list: List[torch.Tensor]
    ) -> Dict[str, torch.Tensor]:
        """
        Create a padded packed sequence from lists of tensors.

        Args:
            input_ids_list: List of input ID tensors.
            labels_list: List of label tensors.

        Returns:
            Packed sequence dictionary.
        """
        input_ids = torch.zeros(self.max_length, dtype=torch.long)
        labels = torch.full((self.max_length,), -100, dtype=torch.long)
        attention_mask = torch.zeros(self.max_length, dtype=torch.long)
        position_ids = torch.zeros(self.max_length, dtype=torch.long)
        doc_mask = torch.zeros(self.max_length, dtype=torch.long)
        doc_mask[0] = 1

        return {
            "input_ids": input_ids,
            "labels": labels,
            "attention_mask": attention_mask,
            "position_ids": position_ids,
            "document_ids": doc_mask,
        }

    def pack_batch(
        self, batch_sequences: List[List[Dict[str, torch.Tensor]]]
    ) -> Dict[str, torch.Tensor]:
        """
        Pack a batch of sequence lists into a batch of packed sequences.

        Args:
            batch_sequences: List of lists, where each inner list contains
                sequences to be packed into one sample.

        Returns:
            Batch of packed sequences with added batch dimension.
        """
        packed = [self.pack(seqs) for seqs in batch_sequences]
        return {
            key: torch.stack([p[key] for p in packed])
            for key in packed[0]
        }

    def get_causal_mask(
        self, attention_mask: torch.Tensor, document_ids: torch.Tensor
    ) -> torch.Tensor:
        """
        Create a causal attention mask for packed sequences that
        prevents:
            - Cross-document attention (different documents)
            - Future token attention (causal masking)
            - Padding token attention

        Args:
            attention_mask: Shape (batch, seq_len) - 1 for real tokens.
            document_ids: Shape (batch, seq_len) - 1 for document starts.

        Returns:
            Causal mask of shape (batch, 1, seq_len, seq_len).
        """
        batch_size, seq_len = attention_mask.shape
        causal_mask = torch.tril(
            torch.ones(seq_len, seq_len, dtype=torch.bool)
        ).unsqueeze(0).unsqueeze(0)

        doc_boundaries = document_ids.cumsum(dim=1)
        same_doc = doc_boundaries.unsqueeze(2) == doc_boundaries.unsqueeze(1)

        valid_tokens = attention_mask.bool().unsqueeze(1).unsqueeze(2)

        mask = causal_mask & same_doc.unsqueeze(1).expand(-1, 1, -1, -1)
        mask = mask & valid_tokens.expand(-1, -1, -1, seq_len).transpose(-2, -1)

        return mask
