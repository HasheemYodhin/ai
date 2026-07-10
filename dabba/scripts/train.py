"""
Main training script for dabba language models.

Loads configuration, initializes model, tokenizer, data pipeline,
and training loop. Supports resuming from checkpoints, mixed precision,
distributed training, and TensorBoard logging.

Usage:
    python -m dabba.scripts.train --config configs/train.yaml
    python -m dabba.scripts.train --model tiny --data ./data/train
    python -m dabba.scripts.train --resume ./checkpoints/checkpoint-1000
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Optional

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from dabba.config.model_config import ModelConfig
from dabba.config.training_config import TrainingConfig
from dabba.config.data_config import DataConfig
from dabba.utils.config_loader import load_config
from dabba.utils.logging import setup_logger, get_logger
from dabba.utils.distributed import (
    setup_distributed,
    cleanup_distributed,
    get_rank,
    get_world_size,
)
from dabba.tokenizer.bpe_tokenizer import BPETokenizer
from dabba.data.streaming_dataset import StreamingDataset
from dabba.data.dataloader import create_dataloader
from dabba.model.transformer import Transformer
from dabba.trainer.optimizer import AdamW
from dabba.trainer.lr_scheduler import LRScheduler
from dabba.trainer.train_step import TrainStep
from dabba.trainer.checkpoint import CheckpointManager
from dabba.trainer.validator import Validator
from dabba.trainer.metrics import MetricsTracker


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train a dabba language model from scratch"
    )
    parser.add_argument("--config", type=str, help="Path to YAML config file")
    parser.add_argument("--model", type=str, default="tiny",
                        choices=["tiny", "small", "base", "medium", "large", "xl", "xxl"],
                        help="Model size preset")
    parser.add_argument("--data", type=str, help="Path to training data directory")
    parser.add_argument("--output", type=str, default="./checkpoints",
                        help="Output directory for checkpoints")
    parser.add_argument("--resume", type=str, help="Resume from checkpoint path")
    parser.add_argument("--batch-size", type=int, help="Batch size per GPU")
    parser.add_argument("--lr", type=float, help="Learning rate")
    parser.add_argument("--max-steps", type=int, help="Maximum training steps")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--local-rank", type=int, default=-1,
                        help="Local rank for distributed training")
    return parser.parse_args()


def set_seed(seed: int) -> None:
    """Set random seeds for reproducibility."""
    import random
    import numpy as np
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def create_model(config: ModelConfig) -> Transformer:
    """
    Create a transformer model from the given configuration.

    Args:
        config: Model configuration.

    Returns:
        Initialized Transformer model.
    """
    logger = get_logger("dabba.scripts")
    logger.info(
        f"Creating model: {config.num_params / 1e6:.1f}M parameters "
        f"({config.num_layers} layers, {config.num_attention_heads} heads, "
        f"{config.hidden_size} hidden)"
    )
    model = Transformer(config)
    count = sum(p.numel() for p in model.parameters())
    logger.info(f"Model created: {count / 1e6:.2f}M parameters")
    return model


def create_tokenizer(data_config: DataConfig) -> Optional[BPETokenizer]:
    """
    Create or load a tokenizer.

    Args:
        data_config: Data configuration.

    Returns:
        BPETokenizer instance, or None if tokenization is handled elsewhere.
    """
    logger = get_logger("dabba.scripts")

    if data_config.tokenizer_path and Path(data_config.tokenizer_path).exists():
        logger.info(f"Loading tokenizer from {data_config.tokenizer_path}")
        return BPETokenizer.load(data_config.tokenizer_path)

    if data_config.train_tokenizer:
        logger.info("Will train tokenizer from data (requires training data)")
    else:
        logger.warning("No tokenizer found and train_tokenizer=False")

    return None


def main():
    args = parse_args()
    set_seed(args.seed + get_rank())

    logger = setup_logger(
        "dabba.scripts",
        level="info",
        rank=get_rank(),
    )

    if args.config:
        model_config, training_config, data_config, _ = load_config(args.config)
    else:
        model_config = ModelConfig.from_preset(args.model)
        training_config = TrainingConfig()
        data_config = DataConfig(train_data_path=args.data)

    if args.batch_size:
        training_config.batch_size = args.batch_size
    if args.lr:
        training_config.learning_rate = args.lr
    if args.max_steps:
        training_config.max_steps = args.max_steps
    if args.output:
        training_config.output_dir = args.output

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Using device: {device}")

    if device.type == "cuda":
        logger.info(
            f"GPU: {torch.cuda.get_device_name(0)} | "
            f"Memory: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f}GB"
        )

    model = create_model(model_config)
    model = model.to(device)

    if training_config.use_torch_compile and device.type == "cuda":
        logger.info("Compiling model with torch.compile...")
        model = torch.compile(model)

    tokenizer = create_tokenizer(data_config)

    logger.info("Creating data loaders...")
    train_loader = create_dataloader(
        data_path=data_config.train_data_path or args.data or "./data",
        seq_length=training_config.seq_length,
        batch_size=training_config.batch_size,
        shuffle=True,
        shuffle_buffer=data_config.shuffle_buffer_size,
        seed=training_config.seed,
        num_workers=training_config.num_workers,
        prefetch_factor=training_config.prefetch_factor,
        pack_sequences=data_config.pack_sequences,
        is_eval=False,
    )

    eval_loader = None
    if data_config.eval_data_path:
        eval_loader = create_dataloader(
            data_path=data_config.eval_data_path,
            seq_length=training_config.seq_length,
            batch_size=training_config.eval_batch_size,
            shuffle=False,
            num_workers=1,
            is_eval=True,
        )

    logger.info("Setting up optimizer, scheduler, and training components...")
    optimizer = AdamW(
        model.parameters(),
        lr=training_config.learning_rate,
        betas=(training_config.beta1, training_config.beta2),
        eps=training_config.epsilon,
        weight_decay=training_config.weight_decay,
    )

    scheduler = LRScheduler(
        optimizer=optimizer,
        warmup_steps=training_config.warmup_steps,
        max_steps=training_config.max_steps or 100000,
        lr_min_ratio=training_config.lr_min_ratio,
        decay_style=training_config.lr_decay_style,
    )

    train_step = TrainStep(
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        max_grad_norm=training_config.max_grad_norm,
        use_amp=training_config.use_amp,
        amp_dtype=training_config.amp_dtype,
        gradient_accumulation_steps=training_config.gradient_accumulation_steps,
        log_steps=training_config.log_steps,
    )

    checkpoint_manager = CheckpointManager(
        output_dir=training_config.output_dir,
        save_steps=training_config.save_steps,
        save_total_limit=training_config.save_total_limit,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        train_step=train_step,
    )

    validator = None
    if eval_loader is not None:
        validator = Validator(
            model=model,
            use_amp=training_config.use_amp,
            amp_dtype=training_config.amp_dtype,
            eval_iters=training_config.eval_iters,
        )

    metrics = MetricsTracker(
        log_dir=os.path.join(training_config.output_dir, "logs"),
        log_steps=training_config.log_steps,
    )

    start_step = 0
    if args.resume:
        loaded_step = checkpoint_manager.load(args.resume)
        if loaded_step is not None:
            start_step = loaded_step
            logger.info(f"Resumed training from step {start_step}")
    else:
        latest_step = checkpoint_manager.load_latest()
        if latest_step is not None:
            start_step = latest_step
            logger.info(f"Resumed training from latest checkpoint (step {start_step})")

    logger.info("Starting training...")
    logger.info(
        f"Model: {model_config.num_params / 1e6:.1f}M params | "
        f"Batch: {training_config.batch_size} | "
        f"Accumulation: {training_config.gradient_accumulation_steps} | "
        f"Effective batch: {training_config.batch_size * training_config.gradient_accumulation_steps}"
    )

    best_eval_loss = float("inf")
    no_improvement_steps = 0
    max_steps = training_config.max_steps or (training_config.num_epochs * 100_000_000)

    step = start_step
    while step < max_steps:
        for batch in train_loader:
            if step >= max_steps:
                break

            batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v
                     for k, v in batch.items()}

            step_metrics = train_step(batch)
            metrics.update(step_metrics, step=step)
            step = train_step.step_count

            if checkpoint_manager.should_save(step):
                save_metrics = {
                    "loss": metrics.get_running("loss") or 0,
                    "perplexity": metrics.get_perplexity() or 0,
                }
                checkpoint_manager.save(step, save_metrics)
                metrics.export_json()

            if validator and step % training_config.eval_steps == 0:
                eval_metrics = validator.validate(eval_loader)
                metrics.update(
                    {f"eval_{k}": v for k, v in eval_metrics.items()},
                    step=step,
                )

                current_eval_loss = eval_metrics["loss"]
                if current_eval_loss < best_eval_loss - training_config.early_stopping_threshold:
                    best_eval_loss = current_eval_loss
                    no_improvement_steps = 0
                    save_metrics = {
                        "loss": metrics.get_running("loss") or 0,
                        "eval_loss": current_eval_loss,
                        "perplexity": eval_metrics["perplexity"],
                    }
                    checkpoint_manager.save(step, save_metrics, is_best=True)
                else:
                    no_improvement_steps += training_config.eval_steps

                if (training_config.early_stopping_patience
                        and no_improvement_steps >= training_config.early_stopping_patience):
                    logger.info(f"Early stopping triggered at step {step}")
                    max_steps = step
                    break

    logger.info(f"Training completed at step {step}")
    checkpoint_manager.save(step, {"loss": metrics.get_running("loss") or 0})
    metrics.export_json()
    metrics.close()
    logger.info(f"Final checkpoint saved to {training_config.output_dir}")


if __name__ == "__main__":
    main()
