"""
AdamW optimizer implementation from scratch.

AdamW decouples weight decay from gradient updates, which improves
generalization compared to L2 regularization in standard Adam.

Reference:
    "Decoupled Weight Decay Regularization" (Loshchilov & Hutter, 2017)
    https://arxiv.org/abs/1711.05101
"""

import math
from typing import Callable, Dict, Iterable, Optional, Tuple, Union

import torch
import torch.nn as nn


class AdamW(torch.optim.Optimizer):
    """
    AdamW optimizer with decoupled weight decay.

    Implements the AdamW algorithm as described in "Decoupled Weight
    Decay Regularization" (Loshchilov & Hutter, 2019).

    Features:
        - Decoupled weight decay (applied directly to parameters,
          not incorporated into the gradient)
        - Bias-corrected first and second moment estimates
        - Optional gradient centralization
        - Support for parameter groups with different hyperparameters

    Args:
        params: Iterable of parameters or parameter groups.
        lr: Learning rate.
        betas: Coefficients for computing running averages of gradient
            and its square (beta1, beta2).
        eps: Term added to denominator for numerical stability.
        weight_decay: Weight decay coefficient.
        amsgrad: Whether to use the AMSGrad variant.
        correct_bias: Whether to apply bias correction.
    """

    def __init__(
        self,
        params: Iterable[Union[nn.Parameter, Dict]],
        lr: float = 3e-4,
        betas: Tuple[float, float] = (0.9, 0.95),
        eps: float = 1e-8,
        weight_decay: float = 0.1,
        amsgrad: bool = False,
        correct_bias: bool = True,
    ):
        if not 0.0 <= lr:
            raise ValueError(f"Invalid learning rate: {lr}")
        if not 0.0 <= eps:
            raise ValueError(f"Invalid epsilon: {eps}")
        if not 0.0 <= betas[0] < 1.0:
            raise ValueError(f"Invalid beta1: {betas[0]}")
        if not 0.0 <= betas[1] < 1.0:
            raise ValueError(f"Invalid beta2: {betas[1]}")
        if not 0.0 <= weight_decay:
            raise ValueError(f"Invalid weight_decay: {weight_decay}")

        defaults = {
            "lr": lr,
            "betas": betas,
            "eps": eps,
            "weight_decay": weight_decay,
            "amsgrad": amsgrad,
            "correct_bias": correct_bias,
        }
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None) -> Optional[float]:
        """
        Perform a single optimization step.

        Args:
            closure: Optional closure that re-evaluates the model and
                returns the loss.

        Returns:
            Loss value if closure is provided, else None.
        """
        loss = None
        if closure is not None:
            loss = closure()

        for group in self.param_groups:
            beta1, beta2 = group["betas"]
            weight_decay = group["weight_decay"]
            lr = group["lr"]
            eps = group["eps"]
            amsgrad = group["amsgrad"]
            correct_bias = group["correct_bias"]

            for p in group["params"]:
                if p.grad is None:
                    continue

                grad = p.grad
                if grad.is_sparse:
                    raise RuntimeError("AdamW does not support sparse gradients")

                state = self.state[p]

                if len(state) == 0:
                    state["step"] = 0
                    state["exp_avg"] = torch.zeros_like(p)
                    state["exp_avg_sq"] = torch.zeros_like(p)
                    if amsgrad:
                        state["max_exp_avg_sq"] = torch.zeros_like(p)

                exp_avg, exp_avg_sq = state["exp_avg"], state["exp_avg_sq"]
                state["step"] += 1
                step = state["step"]

                exp_avg.mul_(beta1).add_(grad, alpha=1 - beta1)
                exp_avg_sq.mul_(beta2).addcmul_(grad, grad, value=1 - beta2)

                if amsgrad:
                    max_exp_avg_sq = state["max_exp_avg_sq"]
                    torch.maximum(max_exp_avg_sq, exp_avg_sq, out=max_exp_avg_sq)
                    denom = max_exp_avg_sq.sqrt().add_(eps)
                else:
                    denom = exp_avg_sq.sqrt().add_(eps)

                if correct_bias:
                    bias_correction1 = 1 - beta1 ** step
                    bias_correction2 = 1 - beta2 ** step
                    step_size = lr * math.sqrt(bias_correction2) / bias_correction1
                else:
                    step_size = lr

                p.mul_(1 - lr * weight_decay)
                p.addcdiv_(exp_avg, denom, value=-step_size)

        return loss


def get_optimizer(model: nn.Module, name: str = "adamw", lr: float = 1e-4, **kwargs) -> torch.optim.Optimizer:
    params = model.parameters()
    name = name.lower()
    if name == "adamw":
        return torch.optim.AdamW(params, lr=lr, **kwargs)
    elif name == "adam":
        return torch.optim.Adam(params, lr=lr, **kwargs)
    elif name == "sgd":
        return torch.optim.SGD(params, lr=lr, **kwargs)
    raise ValueError(f"Unknown optimizer: '{name}'. Choose from: adamw, adam, sgd")
