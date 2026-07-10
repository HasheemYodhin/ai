#!/usr/bin/env python3
"""Quick training script to train your own AI model."""

import os
import torch
from pathlib import Path
from torch.utils.data import DataLoader, Dataset

from dabba.config.model_config import ModelConfig
from dabba.config.training_config import TrainingConfig
from dabba.model.transformer import Transformer
from dabba.tokenizer.bpe_tokenizer import BPETokenizer
from dabba.trainer.optimizer import AdamW
from dabba.trainer.lr_scheduler import LRScheduler
from dabba.trainer.checkpoint import CheckpointManager


class TextDataset(Dataset):
    """Simple text dataset for training."""

    def __init__(self, text_path, tokenizer, seq_length=128):
        with open(text_path, 'r') as f:
            text = f.read()

        tokens = tokenizer.encode(text)
        self.sequences = []

        for i in range(0, len(tokens) - seq_length, seq_length):
            self.sequences.append(tokens[i:i + seq_length])

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        tokens = self.sequences[idx]
        input_ids = torch.tensor(tokens[:-1], dtype=torch.long)
        labels = torch.tensor(tokens[1:], dtype=torch.long)
        return input_ids, labels


def train():
    """Train a small model."""
    print("=" * 60)
    print("TRAINING YOUR AI MODEL")
    print("=" * 60)

    # Setup device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Create output directory
    output_dir = Path("./checkpoints/my-model")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create a small model config
    config = ModelConfig(
        vocab_size=5000,
        hidden_size=256,
        num_layers=4,
        num_attention_heads=4,
        num_key_value_heads=2,
        intermediate_size=1024,
        max_position_embeddings=128,
    )
    print(f"\nModel: {config.num_params / 1e6:.1f}M parameters")
    print(f"Architecture: {config.num_layers} layers, {config.num_attention_heads} heads")

    # Initialize model
    model = Transformer(config).to(device)

    # Initialize tokenizer
    print("\nInitializing tokenizer...")
    tokenizer = BPETokenizer()

    # Load training data
    print("Loading training data...")
    data_path = Path("data/train/training_data.txt")
    if not data_path.exists():
        print(f"Training data not found at {data_path}")
        return

    dataset = TextDataset(str(data_path), tokenizer, seq_length=128)
    dataloader = DataLoader(dataset, batch_size=8, shuffle=True, drop_last=True)
    print(f"Training samples: {len(dataset)}")
    print(f"Batches per epoch: {len(dataloader)}")

    # Setup training
    optimizer = AdamW(model.parameters(), lr=1e-3)
    scheduler = LRScheduler(optimizer, warmup_steps=100, max_steps=500, decay_style="cosine")
    checkpoint_mgr = CheckpointManager(
        output_dir=str(output_dir),
        save_steps=100,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
    )

    # Training loop
    print("\n" + "=" * 60)
    print("STARTING TRAINING")
    print("=" * 60)

    model.train()
    total_loss = 0
    step = 0
    max_steps = 500

    for epoch in range(1):
        for batch_idx, (input_ids, labels) in enumerate(dataloader):
            if step >= max_steps:
                break

            input_ids = input_ids.to(device)
            labels = labels.to(device)

            # Forward pass
            outputs = model(input_ids)
            logits = outputs["logits"]  # Shape: (batch, seq_len, vocab_size)

            # Compute loss
            loss = torch.nn.functional.cross_entropy(
                logits.reshape(-1, config.vocab_size),
                labels.reshape(-1)
            )

            # Backward pass
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            total_loss += loss.item()
            step += 1

            if step % 50 == 0:
                avg_loss = total_loss / 50
                print(f"Step {step:3d}/{max_steps} | Loss: {avg_loss:.4f} | LR: {scheduler.get_last_lr()[0]:.2e}")
                total_loss = 0

            if step % 100 == 0:
                checkpoint_mgr.save_checkpoint(step=step, metrics={"loss": loss.item()})
                print(f"  → Checkpoint saved")

    # Final save
    final_path = output_dir / "final"
    final_path.mkdir(exist_ok=True)
    torch.save(model.state_dict(), final_path / "model.pt")
    torch.save({"config": config}, final_path / "config.pt")
    print(f"\n✓ Training complete! Model saved to {final_path}")
    print(f"  Model checkpoint: {final_path / 'model.pt'}")


if __name__ == "__main__":
    train()
