"""
Training configuration dataclass. Controls all aspects of the training
loop: optimization, learning rate scheduling, mixed precision, gradient
accumulation, checkpointing, validation, and logging.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrainingConfig:
    """
    Configuration for model training.

    Covers the optimizer (AdamW), learning rate schedule (cosine with
    linear warmup), mixed precision (AMP), gradient clipping, gradient
    accumulation, checkpointing, validation, early stopping, and logging.
    """

    # Optimizer
    learning_rate: float = 3e-4
    weight_decay: float = 0.1
    beta1: float = 0.9
    beta2: float = 0.95
    epsilon: float = 1e-8
    max_grad_norm: float = 1.0

    # Learning rate schedule
    lr_scheduler: str = "cosine"  # "cosine", "linear", "constant"
    warmup_steps: int = 2000
    lr_min_ratio: float = 0.1  # Minimum LR as fraction of peak
    lr_decay_style: str = "cosine"

    # Training
    num_epochs: int = 1
    max_steps: Optional[int] = None  # Overrides num_epochs if set
    batch_size: int = 32
    gradient_accumulation_steps: int = 1
    seq_length: int = 2048

    # Mixed precision
    use_amp: bool = True
    amp_dtype: str = "bfloat16"  # "float16", "bfloat16"
    use_torch_compile: bool = False

    # Checkpointing
    save_steps: int = 1000
    save_total_limit: int = 5
    output_dir: str = "./checkpoints"
    resume_from_checkpoint: Optional[str] = None

    # Validation
    eval_steps: int = 500
    eval_batch_size: Optional[int] = None
    eval_iters: int = 100

    # Early stopping
    early_stopping_patience: Optional[int] = None
    early_stopping_threshold: float = 0.001

    # Logging
    log_steps: int = 10
    log_to_tensorboard: bool = True
    log_to_wandb: bool = False
    wandb_project: Optional[str] = None
    wandb_run_name: Optional[str] = None

    # Data
    seed: int = 42
    num_workers: int = 4
    prefetch_factor: int = 2

    def __post_init__(self):
        if self.eval_batch_size is None:
            self.eval_batch_size = self.batch_size
