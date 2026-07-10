#!/usr/bin/env python3
"""
Train Dabba - Your personal AI model
"""

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from pathlib import Path
import json

from dabba.config.model_config import ModelConfig
from dabba.model.transformer import Transformer
from dabba.tokenizer.bpe_tokenizer import BPETokenizer
from dabba.trainer.optimizer import AdamW
from dabba.trainer.lr_scheduler import LRScheduler
from dabba.trainer.checkpoint import CheckpointManager


class DabbaDataset(Dataset):
    """Dataset for training Dabba."""

    def __init__(self, text_path, tokenizer, seq_length=256, max_chars=800_000):
        print(f"Loading data from {text_path}...")
        with open(text_path, 'r', encoding='utf-8') as f:
            text = f.read()

        # Sample a manageable chunk — encoding 5M+ chars is extremely slow on CPU
        if len(text) > max_chars:
            text = text[:max_chars]
            print(f"Sampled first {max_chars:,} chars (full size: {len(text):,})")
        else:
            print(f"Text length: {len(text):,} characters")

        # Tokenize line-by-line to avoid hashing a huge string as a cache key
        print("Tokenizing (line by line)...")
        tokens = []
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if i % 500 == 0:
                print(f"   {i}/{len(lines)} lines...", flush=True)
            tokens.extend(tokenizer.encode(line))
        print(f"Total tokens: {len(tokens):,}")

        # Create sequences
        self.sequences = []
        for i in range(0, len(tokens) - seq_length, seq_length // 2):  # 50% overlap
            seq = tokens[i:i + seq_length]
            if len(seq) == seq_length:
                self.sequences.append(seq)

        print(f"Created {len(self.sequences)} sequences of length {seq_length}")

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        tokens = self.sequences[idx]
        input_ids = torch.tensor(tokens[:-1], dtype=torch.long)
        labels = torch.tensor(tokens[1:], dtype=torch.long)
        return input_ids, labels


def train_dabba():
    """Train your personal AI model - Dabba."""

    print("\n" + "="*70)
    print("🚀 TRAINING DABBA - YOUR PERSONAL AI MODEL")
    print("="*70)

    # Setup
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n📱 Device: {device}")

    output_dir = Path("./checkpoints/dabba-model")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load existing tokenizer (already trained on this dataset)
    print("\n📝 Loading existing tokenizer...")
    tokenizer_path = Path("./checkpoints/tokenizer/bpe_tokenizer.json")
    if not tokenizer_path.exists():
        raise FileNotFoundError(f"Tokenizer not found at {tokenizer_path}. Run tokenizer training first.")
    tokenizer = BPETokenizer.load(str(tokenizer_path))
    print(f"   ✓ Tokenizer loaded: {len(tokenizer.vocab)} tokens")

    # Model configuration
    print("\n📐 Model Configuration:")
    vocab_size = len(tokenizer.vocab)
    config = ModelConfig(
        vocab_size=vocab_size,
        hidden_size=384,
        num_layers=6,
        num_attention_heads=6,
        num_key_value_heads=3,
        intermediate_size=768,
        max_position_embeddings=256,
    )
    print(f"   - Parameters: {config.num_params / 1e6:.1f}M")
    print(f"   - Layers: {config.num_layers}")
    print(f"   - Attention heads: {config.num_attention_heads}")
    print(f"   - Hidden size: {config.hidden_size}")

    # Create model
    print("\n🧠 Creating model...")
    model = Transformer(config).to(device)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"   ✓ Model created: {total_params / 1e6:.2f}M parameters")

    # Load data
    print("\n📚 Loading training data...")
    data_path = Path("data/train/dabba_training_data.txt")
    if not data_path.exists():
        print(f"   ✗ Data not found at {data_path}")
        return

    dataset = DabbaDataset(str(data_path), tokenizer, seq_length=256)
    dataloader = DataLoader(dataset, batch_size=4, shuffle=True, drop_last=True)
    print(f"   ✓ Loaded {len(dataset)} samples")
    print(f"   ✓ {len(dataloader)} batches")

    # Setup training
    print("\n⚙️  Setting up training...")
    optimizer = AdamW(model.parameters(), lr=5e-4, weight_decay=0.01)
    scheduler = LRScheduler(optimizer, warmup_steps=200, max_steps=3000, decay_style="cosine")
    checkpoint_mgr = CheckpointManager(
        output_dir=str(output_dir),
        save_steps=200,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
    )
    print("   ✓ Training setup complete")

    # Training loop
    print("\n" + "="*70)
    print("🏋️ TRAINING START")
    print("="*70)

    model.train()
    total_loss = 0
    step = 0
    max_steps = 3000

    for epoch in range(20):
        for batch_idx, (input_ids, labels) in enumerate(dataloader):
            if step >= max_steps:
                break

            input_ids = input_ids.to(device)
            labels = labels.to(device)

            # Forward pass
            outputs = model(input_ids)
            logits = outputs["logits"]

            # Loss
            loss = nn.functional.cross_entropy(
                logits.reshape(-1, config.vocab_size),
                labels.reshape(-1),
                reduction='mean'
            )

            # Backward
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            total_loss += loss.item()
            step += 1

            # Logging
            if step % 50 == 0:
                avg_loss = total_loss / 50
                lr = scheduler.get_lr()
                print(f"Step {step:4d}/{max_steps} | Loss: {avg_loss:6.4f} | LR: {lr:.2e}")
                total_loss = 0

# Checkpointing
            if step % 200 == 0:
                checkpoint_mgr.save(step=step, metrics={"loss": loss.item()})
                print(f"           ✓ Checkpoint saved at step {step}")

    # Save final model
    print("\n" + "="*70)
    print("💾 SAVING DABBA")
    print("="*70)

    final_dir = output_dir / "final"
    final_dir.mkdir(exist_ok=True)

    # Save model state dict
    torch.save(model.state_dict(), final_dir / "model.pt")
    print(f"✓ Model weights saved to {final_dir / 'model.pt'}")

    # Save config
    torch.save({"config": config}, final_dir / "config.pt")
    print(f"✓ Config saved to {final_dir / 'config.pt'}")

    # Save metadata
    metadata = {
        "name": "Dabba",
        "description": "Personal AI model trained on diverse AI/ML knowledge",
        "version": "1.0",
        "parameters": total_params,
        "vocab_size": config.vocab_size,
        "max_position_embeddings": config.max_position_embeddings,
        "training_steps": step,
    }
    with open(final_dir / "metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"✓ Metadata saved")

    print("\n" + "="*70)
    print("✨ DABBA TRAINING COMPLETE!")
    print("="*70)
    print(f"\n📍 Model location: {final_dir}")
    print(f"📊 Final loss: {loss.item():.4f}")
    print(f"📈 Total steps: {step}")
    print(f"\n🚀 Next: Start the API server!")
    print(f"   The API will automatically load Dabba for inference.\n")


if __name__ == "__main__":
    train_dabba()
