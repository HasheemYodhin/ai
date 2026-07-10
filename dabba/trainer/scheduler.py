import math
import torch


def get_scheduler(
    optimizer: torch.optim.Optimizer,
    name: str = "cosine",
    num_training_steps: int = 1000,
    warmup_steps: int = 0,
    **kwargs,
) -> torch.optim.lr_scheduler.LRScheduler:
    name = name.lower()
    if name not in ("cosine", "linear", "constant"):
        raise ValueError(f"Unknown scheduler: '{name}'. Choose from: cosine, linear, constant")

    def lr_lambda(current_step: int) -> float:
        if current_step < warmup_steps:
            return float(current_step) / float(max(1, warmup_steps))
        progress = float(current_step - warmup_steps) / float(max(1, num_training_steps - warmup_steps))
        if name == "cosine":
            return max(0.0, 0.5 * (1.0 + math.cos(math.pi * progress)))
        elif name == "linear":
            return max(0.0, 1.0 - progress)
        else:  # constant
            return 1.0

    return torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
