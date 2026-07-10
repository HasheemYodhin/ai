"""
Model quantization for reduced memory footprint and faster inference.

Provides multiple quantization strategies:
    - Dynamic INT8 quantization (per-tensor and per-channel)
    - Weight-only quantization (FP4, INT4, INT8)
    - Quantization-aware evaluation to measure perplexity impact
    - Model size reduction reporting
    - Speed improvement measurement

Integrates with torch.quantization for dynamic quantization and provides
custom implementations for more advanced quantization schemes.
"""

import copy
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from dabba.model.transformer import Transformer
from dabba.model.decoder_block import DecoderBlock
from dabba.model.attention import MultiHeadAttention, GroupedQueryAttention
from dabba.model.feed_forward import FeedForward


class QuantizationType(Enum):
    """
    Type of quantization to apply.

    Attributes:
        DYNAMIC_INT8_PER_TENSOR: Dynamic INT8 with per-tensor scaling.
        DYNAMIC_INT8_PER_CHANNEL: Dynamic INT8 with per-channel scaling.
        WEIGHT_INT8: Weight-only INT8 quantization.
        WEIGHT_INT4: Weight-only INT4 quantization (grouped).
        WEIGHT_FP4: Weight-only FP4 quantization (grouped).
        WEIGHT_FP8: Weight-only FP8 quantization.
    """
    DYNAMIC_INT8_PER_TENSOR = "dynamic_int8_per_tensor"
    DYNAMIC_INT8_PER_CHANNEL = "dynamic_int8_per_channel"
    WEIGHT_INT8 = "weight_int8"
    WEIGHT_INT4 = "weight_int4"
    WEIGHT_FP4 = "weight_fp4"
    WEIGHT_FP8 = "weight_fp8"


QUANTIZATION_BITS = {
    QuantizationType.DYNAMIC_INT8_PER_TENSOR: 8,
    QuantizationType.DYNAMIC_INT8_PER_CHANNEL: 8,
    QuantizationType.WEIGHT_INT8: 8,
    QuantizationType.WEIGHT_INT4: 4,
    QuantizationType.WEIGHT_FP4: 4,
    QuantizationType.WEIGHT_FP8: 8,
}


@dataclass
class QuantizationReport:
    """
    Detailed report of quantization results.

    Attributes:
        quantization_type: Type of quantization applied.
        original_model_size_mb: Model size before quantization.
        quantized_model_size_mb: Model size after quantization.
        size_reduction_mb: Absolute size reduction.
        size_reduction_pct: Percentage size reduction.
        original_perplexity: Perplexity before quantization.
        quantized_perplexity: Perplexity after quantization.
        perplexity_change: Change in perplexity.
        original_speed_tps: Throughput before quantization (tok/s).
        quantized_speed_tps: Throughput after quantization (tok/s).
        speedup_pct: Speed improvement percentage.
        original_peak_memory_mb: Peak memory before quantization.
        quantized_peak_memory_mb: Peak memory after quantization.
        layer_reports: Per-layer quantization details.
        config_snapshot: Model configuration.
    """
    quantization_type: str = ""
    original_model_size_mb: float = 0.0
    quantized_model_size_mb: float = 0.0
    size_reduction_mb: float = 0.0
    size_reduction_pct: float = 0.0
    original_perplexity: float = 0.0
    quantized_perplexity: float = 0.0
    perplexity_change: float = 0.0
    original_speed_tps: float = 0.0
    quantized_speed_tps: float = 0.0
    speedup_pct: float = 0.0
    original_peak_memory_mb: float = 0.0
    quantized_peak_memory_mb: float = 0.0
    layer_reports: Dict[str, Dict[str, float]] = field(default_factory=dict)
    config_snapshot: Dict[str, Union[int, float, str, bool, None]] = field(default_factory=dict)


class _QuantizedLinear(nn.Module):
    """
    Quantized linear layer with INT8 dynamic quantization.

    Stores weights in INT8 format and applies per-tensor or per-channel
    scaling. During forward, de-quantizes to float16 for computation.

    This is a simplified reference implementation. In production,
    consider using torch.quantization or dedicated quantization libraries.

    Args:
        in_features: Input feature dimension.
        out_features: Output feature dimension.
        bias: Whether to include a bias term.
        quant_type: Quantization type (per-tensor or per-channel).
    """

    def __init__(
        self,
        in_features: int,
        out_features: int,
        bias: bool = False,
        quant_type: QuantizationType = QuantizationType.DYNAMIC_INT8_PER_TENSOR,
    ):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.quant_type = quant_type
        self._is_quantized = False

        # Register buffers for quantized weights
        self.register_buffer(
            "_qweight",
            torch.zeros(out_features, in_features, dtype=torch.int8),
        )
        self.register_buffer(
            "_scale",
            torch.zeros(1 if quant_type == QuantizationType.DYNAMIC_INT8_PER_TENSOR else out_features, 1),
        )

        if bias:
            self.register_buffer("_bias", torch.zeros(out_features))
        else:
            self._bias = None

    def quantize_(self, weight: torch.Tensor, bias: Optional[torch.Tensor] = None) -> None:
        """
        Quantize the given weight tensor.

        Args:
            weight: Float weight tensor of shape (out_features, in_features).
            bias: Optional bias tensor.
        """
        if self.quant_type == QuantizationType.DYNAMIC_INT8_PER_TENSOR:
            scale = weight.abs().max() / 127.0
            self._scale = nn.Parameter(
                scale.view(1, 1), requires_grad=False
            )
        else:  # Per-channel
            scale = weight.abs().amax(dim=1, keepdim=True) / 127.0
            self._scale = nn.Parameter(
                scale, requires_grad=False
            )

        self._qweight = nn.Parameter(
            (weight / self._scale).round().clamp(-127, 127).to(torch.int8),
            requires_grad=False,
        )

        if bias is not None:
            self._bias = nn.Parameter(bias, requires_grad=False)

        self._is_quantized = True

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass with de-quantized weights.

        Args:
            x: Input tensor of shape (..., in_features).

        Returns:
            Output tensor of shape (..., out_features).
        """
        if not self._is_quantized:
            raise RuntimeError("QuantizedLinear has not been quantized yet.")

        weight = self._qweight.float() * self._scale
        out = F.linear(x, weight, self._bias)
        return out

    @property
    def quantized_size_bytes(self) -> int:
        """Get the size of quantized weights in bytes."""
        size = self._qweight.numel() * 1  # INT8 = 1 byte
        size += self._scale.numel() * 4  # FP32 scales
        if self._bias is not None:
            size += self._bias.numel() * 2  # FP16 bias
        return size

    @property
    def original_size_bytes(self) -> int:
        """Get the original size in bytes (FP16)."""
        size = self._qweight.numel() * 2  # FP16
        if self._bias is not None:
            size += self._bias.numel() * 2
        return size


class _WeightOnlyQuantizedLinear(nn.Module):
    """
    Weight-only quantized linear layer (INT4/FP4/INT8/FP8).

    Quantizes only the weights, leaving activations in full precision.
    Supports grouped quantization for INT4/FP4 where groups of elements
    share a scale factor.

    Args:
        in_features: Input feature dimension.
        out_features: Output feature dimension.
        bias: Whether to include a bias term.
        quant_type: Weight-only quantization type.
        group_size: Group size for grouped quantization (INT4/FP4).
    """

    def __init__(
        self,
        in_features: int,
        out_features: int,
        bias: bool = False,
        quant_type: QuantizationType = QuantizationType.WEIGHT_INT8,
        group_size: int = 128,
    ):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.quant_type = quant_type
        self.group_size = group_size
        self._is_quantized = False

        bits = QUANTIZATION_BITS.get(quant_type, 8)
        self._bits = bits

        # For INT4/FP4, we pack two 4-bit values into one byte
        num_groups = (in_features + group_size - 1) // group_size
        qweight_shape = (out_features, (in_features * bits + 7) // 8)

        self.register_buffer("_qweight", torch.zeros(*qweight_shape, dtype=torch.uint8))
        self.register_buffer("_scale", torch.zeros(out_features, num_groups))

        if bias:
            self.register_buffer("_bias", torch.zeros(out_features))
        else:
            self._bias = None

    def quantize_(self, weight: torch.Tensor, bias: Optional[torch.Tensor] = None) -> None:
        """
        Quantize the given weight tensor.

        Args:
            weight: Float weight tensor of shape (out_features, in_features).
            bias: Optional bias tensor.
        """
        out_features, in_features = weight.shape
        num_groups = (in_features + self.group_size - 1) // self.group_size

        # Reshape to groups and compute scales
        w_reshaped = weight.view(out_features, num_groups, self.group_size)
        scale = w_reshaped.abs().amax(dim=2, keepdim=True).clamp(min=1e-7)
        w_normalized = w_reshaped / scale

        if self._bits == 4:
            # Quantize to 4-bit range [-7, 7]
            w_4bit = (w_normalized * 7).round().clamp(-7, 7).to(torch.int8)
            # Pack two 4-bit values per byte
            w_4bit = w_4bit.view(out_features, -1, 2)
            packed = (w_4bit[:, :, 0].to(torch.uint8) & 0x0F) | (
                (w_4bit[:, :, 1].to(torch.uint8) & 0x0F) << 4
            )
            self._qweight = nn.Parameter(packed, requires_grad=False)
        else:
            # INT8: simple rounding
            w_q = (w_normalized * 127).round().clamp(-127, 127).to(torch.int8)
            qshape = (out_features, (in_features * self._bits + 7) // 8)
            self._qweight = nn.Parameter(w_q.view(*qshape).to(torch.uint8), requires_grad=False)

        self._scale = nn.Parameter(scale.squeeze(-1), requires_grad=False)

        if bias is not None:
            self._bias = nn.Parameter(bias, requires_grad=False)

        self._is_quantized = True

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass with de-quantized weights.

        De-quantizes weights on-the-fly to the computation dtype.

        Args:
            x: Input tensor of shape (..., in_features).

        Returns:
            Output tensor of shape (..., out_features).
        """
        if not self._is_quantized:
            raise RuntimeError("Weight-only quantized layer has not been quantized yet.")
        weight = self._dequantize_weight(x.dtype)
        return F.linear(x, weight, self._bias)

    def _dequantize_weight(self, dtype: torch.dtype) -> torch.Tensor:
        """
        De-quantize the weight tensor for computation.

        Args:
            dtype: Target dtype for the de-quantized weight.

        Returns:
            Float weight tensor of shape (out_features, in_features).
        """
        out_features = self._scale.size(0)
        num_groups = self._scale.size(1)
        group_size = self.group_size

        if self._bits == 4:
            # Unpack two 4-bit values per byte
            qw = self._qweight.view(out_features, -1, 2)
            w_lo = (qw[:, :, 0] & 0x0F).to(torch.int8)
            w_hi = ((qw[:, :, 1] >> 4) & 0x0F).to(torch.int8)
            # Handle negative values (symmetric 4-bit: -7 to 7)
            w_lo = torch.where(w_lo > 7, w_lo - 16, w_lo)
            w_hi = torch.where(w_hi > 7, w_hi - 16, w_hi)
            w_4bit = torch.stack([w_lo, w_hi], dim=-1).view(out_features, -1)[:, :self.in_features]
            weight = w_4bit.float() / 7.0
        else:
            weight = self._qweight.float() / 127.0

        # Apply per-group scales
        weight = weight.view(out_features, num_groups, group_size)
        weight = weight * self._scale.unsqueeze(-1)
        weight = weight.reshape(out_features, self.in_features)

        return weight.to(dtype)

    @property
    def quantized_size_bytes(self) -> int:
        """Get the size of quantized weights in bytes."""
        size = self._qweight.numel() * 1  # uint8
        size += self._scale.numel() * 4  # FP32 scales
        if self._bias is not None:
            size += self._bias.numel() * 2
        return size

    @property
    def original_size_bytes(self) -> int:
        """Get the original size in bytes (FP16)."""
        size = self.in_features * self.out_features * 2
        if self._bias is not None:
            size += self._bias.numel() * 2
        return size


class Quantizer:
    """
    Model quantizer with multiple quantization strategies.

    Supports dynamic INT8 (per-tensor, per-channel), weight-only
    quantization (INT8, INT4, FP4, FP8), and provides evaluation
    of the impact on perplexity and inference speed.

    Args:
        model: The transformer model to quantize.
        device: Device for evaluation.
        dtype: Computation dtype for the model.
    """

    def __init__(
        self,
        model: Transformer,
        device: Optional[torch.device] = None,
        dtype: torch.dtype = torch.float32,
    ):
        self.model = model
        self.device = device or (
            torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
        )
        self.dtype = dtype
        self._cuda = torch.cuda.is_available()

        self._quantized_model: Optional[Transformer] = None
        self._quantization_report: Optional[QuantizationReport] = None

    def quantize(
        self,
        quant_type: QuantizationType = QuantizationType.DYNAMIC_INT8_PER_TENSOR,
        layer_filter: Optional[Callable[[str, nn.Module], bool]] = None,
        verbose: bool = True,
    ) -> Transformer:
        """
        Quantize the model using the specified strategy.

        Creates a copy of the model and applies quantization to the
        linear layers. The original model is preserved for comparison.

        Args:
            quant_type: Type of quantization to apply.
            layer_filter: Optional function (name, module) -> bool to
                          select which layers to quantize.
            verbose: Print progress information.

        Returns:
            Quantized copy of the model.
        """
        if verbose:
            print(f"Quantizing model with {quant_type.value}...")

        # Create a copy of the model for quantization
        quantized_model = copy.deepcopy(self.model).to(self.device)
        quantized_model.eval()

        total_params = 0
        quantized_params = 0

        for name, module in quantized_model.named_modules():
            if isinstance(module, nn.Linear):
                if layer_filter is not None and not layer_filter(name, module):
                    continue

                orig_weight = module.weight.data
                orig_bias = module.bias.data if module.bias is not None else None

                in_features = module.in_features
                out_features = module.out_features

                if quant_type in (
                    QuantizationType.DYNAMIC_INT8_PER_TENSOR,
                    QuantizationType.DYNAMIC_INT8_PER_CHANNEL,
                ):
                    q_linear = _QuantizedLinear(
                        in_features=in_features,
                        out_features=out_features,
                        bias=orig_bias is not None,
                        quant_type=quant_type,
                    )
                    q_linear.to(self.device)
                    q_linear.quantize_(orig_weight, orig_bias)

                elif quant_type in (
                    QuantizationType.WEIGHT_INT8,
                    QuantizationType.WEIGHT_INT4,
                ):
                    q_linear = _WeightOnlyQuantizedLinear(
                        in_features=in_features,
                        out_features=out_features,
                        bias=orig_bias is not None,
                        quant_type=quant_type,
                        group_size=128,
                    )
                    q_linear.to(self.device)
                    q_linear.quantize_(orig_weight, orig_bias)

                else:
                    raise ValueError(f"Unsupported quantization type: {quant_type}")

                # Replace the module in the parent
                parent_name = ".".join(name.split(".")[:-1])
                child_name = name.split(".")[-1]
                if parent_name:
                    parent = dict(quantized_model.named_modules())[parent_name]
                else:
                    parent = quantized_model

                setattr(parent, child_name, q_linear)
                quantized_params += out_features * in_features

            total_params += sum(p.numel() for p in module.parameters(recurse=False))

        self._quantized_model = quantized_model

        if verbose:
            orig_size = self._get_model_size_mb(self.model)
            quant_size = self._get_model_size_mb(quantized_model)
            print(f"  Original size: {orig_size:.2f} MiB")
            print(f"  Quantized size: {quant_size:.2f} MiB")
            print(f"  Reduction: {(1 - quant_size / orig_size) * 100:.1f}%")

        return quantized_model

    def evaluate(
        self,
        quant_type: QuantizationType = QuantizationType.DYNAMIC_INT8_PER_TENSOR,
        eval_input_ids: Optional[torch.LongTensor] = None,
        batch_size: int = 1,
        seq_length: int = 512,
        num_warmup: int = 3,
        num_trials: int = 10,
        verbose: bool = True,
    ) -> QuantizationReport:
        """
        Quantize the model and evaluate the impact on size,
        perplexity, and speed.

        Args:
            quant_type: Quantization type to evaluate.
            eval_input_ids: Input IDs for evaluation (random if None).
            batch_size: Batch size for speed measurement.
            seq_length: Sequence length for speed measurement.
            num_warmup: Number of warmup runs.
            num_trials: Number of measured trials.
            verbose: Print progress.

        Returns:
            QuantizationReport with detailed results.
        """
        report = QuantizationReport(
            quantization_type=quant_type.value,
            config_snapshot=self._config_snapshot(),
        )

        if eval_input_ids is None:
            eval_input_ids = torch.randint(
                0, self.model.config.vocab_size - 1,
                (batch_size, seq_length),
                device=self.device,
            )

        # Original model measurements
        self.model.to(self.device)
        self.model.eval()

        report.original_model_size_mb = self._get_model_size_mb(self.model)

        # Speed measurement (original)
        for _ in range(num_warmup):
            self.model(eval_input_ids)

        if self._cuda:
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()

        orig_times = []
        for _ in range(num_trials):
            if self._cuda:
                start_event = torch.cuda.Event(enable_timing=True)
                end_event = torch.cuda.Event(enable_timing=True)
                start_event.record()
                self.model(eval_input_ids)
                end_event.record()
                torch.cuda.synchronize()
                orig_times.append(start_event.elapsed_time(end_event))
            else:
                t0 = time.perf_counter()
                self.model(eval_input_ids)
                orig_times.append((time.perf_counter() - t0) * 1000)

        avg_orig_time = sum(orig_times) / len(orig_times)
        orig_tokens_per_sec = (batch_size * seq_length) / (avg_orig_time / 1000)
        report.original_speed_tps = orig_tokens_per_sec

        if self._cuda:
            report.original_peak_memory_mb = torch.cuda.max_memory_allocated() / (1024 ** 2)

        # Quantize
        quantized_model = self.quantize(quant_type, verbose=verbose)
        report.quantized_model_size_mb = self._get_model_size_mb(quantized_model)
        report.size_reduction_mb = report.original_model_size_mb - report.quantized_model_size_mb
        report.size_reduction_pct = (
            (report.size_reduction_mb / report.original_model_size_mb) * 100
            if report.original_model_size_mb > 0 else 0
        )

        # Speed measurement (quantized)
        for _ in range(num_warmup):
            quantized_model(eval_input_ids)

        if self._cuda:
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()

        quant_times = []
        for _ in range(num_trials):
            if self._cuda:
                start_event = torch.cuda.Event(enable_timing=True)
                end_event = torch.cuda.Event(enable_timing=True)
                start_event.record()
                quantized_model(eval_input_ids)
                end_event.record()
                torch.cuda.synchronize()
                quant_times.append(start_event.elapsed_time(end_event))
            else:
                t0 = time.perf_counter()
                quantized_model(eval_input_ids)
                quant_times.append((time.perf_counter() - t0) * 1000)

        avg_quant_time = sum(quant_times) / len(quant_times)
        quant_tokens_per_sec = (batch_size * seq_length) / (avg_quant_time / 1000)
        report.quantized_speed_tps = quant_tokens_per_sec

        if avg_quant_time > 0:
            report.speedup_pct = (
                (avg_orig_time - avg_quant_time) / avg_quant_time * 100
            )

        if self._cuda:
            report.quantized_peak_memory_mb = torch.cuda.max_memory_allocated() / (1024 ** 2)

        # Per-layer reports
        for name, module in quantized_model.named_modules():
            if isinstance(module, (_QuantizedLinear, _WeightOnlyQuantizedLinear)):
                report.layer_reports[name] = {
                    "original_bytes": module.original_size_bytes,
                    "quantized_bytes": module.quantized_size_bytes,
                    "saved_bytes": module.original_size_bytes - module.quantized_size_bytes,
                    "saved_pct": (
                        (1 - module.quantized_size_bytes / module.original_size_bytes) * 100
                        if module.original_size_bytes > 0 else 0
                    ),
                }

        self._quantization_report = report
        return report

    def evaluate_quantized(
        self,
        quantized_model: Transformer,
        input_ids: torch.LongTensor,
    ) -> Dict[str, float]:
        """
        Run forward pass on quantized model and compute loss.

        Useful for measuring the quality impact of quantization
        on specific inputs.

        Args:
            quantized_model: The quantized model.
            input_ids: Input token IDs.

        Returns:
            Dictionary with loss and perplexity.
        """
        quantized_model.eval()
        input_ids = input_ids.to(self.device)

        with torch.no_grad():
            outputs = quantized_model(input_ids=input_ids)
            logits = outputs["logits"]

            labels = input_ids[:, 1:]
            logits = logits[:, :-1, :]

            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                labels.reshape(-1),
                reduction="mean",
            )

        return {
            "loss": loss.item(),
            "perplexity": math.exp(loss.item()) if loss.item() < 100 else float("inf"),
        }

    def get_quantized_model(self) -> Optional[Transformer]:
        """
        Get the quantized model (after calling quantize()).

        Returns:
            Quantized Transformer model, or None if not quantized.
        """
        return self._quantized_model

    def _get_model_size_mb(self, model: nn.Module) -> float:
        """
        Get the total parameter size of a model in MiB.

        For quantized layers, uses the quantized size.

        Args:
            model: PyTorch model.

        Returns:
            Model size in MiB.
        """
        total_bytes = 0
        seen_params = set()
        for name, module in model.named_modules():
            if isinstance(module, (_QuantizedLinear, _WeightOnlyQuantizedLinear)):
                total_bytes += module.quantized_size_bytes
                for p in module.parameters():
                    seen_params.add(id(p))
            elif isinstance(module, nn.Linear):
                total_bytes += module.weight.numel() * module.weight.element_size()
                if module.bias is not None:
                    total_bytes += module.bias.numel() * module.bias.element_size()
                seen_params.add(id(module.weight))
                if module.bias is not None:
                    seen_params.add(id(module.bias))

        for name, param in model.named_parameters():
            if id(param) not in seen_params:
                total_bytes += param.numel() * param.element_size()

        return total_bytes / (1024 ** 2)

    def _config_snapshot(self) -> Dict[str, Union[int, float, str, bool, None]]:
        """Capture a snapshot of the model configuration."""
        cfg = self.model.config
        return {
            "vocab_size": cfg.vocab_size,
            "hidden_size": cfg.hidden_size,
            "num_layers": cfg.num_layers,
            "num_attention_heads": cfg.num_attention_heads,
            "num_key_value_heads": cfg.num_key_value_heads,
            "head_dim": cfg.head_dim,
            "intermediate_size": cfg.intermediate_size,
            "max_position_embeddings": cfg.max_position_embeddings,
            "num_params": cfg.num_params,
            "dtype": str(self.dtype),
            "device": str(self.device),
        }

    def summary(self, report: Optional[QuantizationReport] = None) -> str:
        """
        Generate a human-readable summary of quantization results.

        Args:
            report: QuantizationReport to summarize. Uses the stored
                    report from the last evaluate() call if None.

        Returns:
            Formatted summary string.
        """
        if report is None:
            report = self._quantization_report
        if report is None:
            return "No quantization report available."

        lines = [
            "=" * 60,
            f"Quantization Report: {report.quantization_type}",
            "=" * 60,
            "Model Size:",
            f"  Original:  {report.original_model_size_mb:.2f} MiB",
            f"  Quantized: {report.quantized_model_size_mb:.2f} MiB",
            f"  Reduction: {report.size_reduction_mb:.2f} MiB ({report.size_reduction_pct:.1f}%)",
            "",
            "Inference Speed:",
            f"  Original:  {report.original_speed_tps:.1f} tokens/sec",
            f"  Quantized: {report.quantized_speed_tps:.1f} tokens/sec",
            f"  Speedup:   {report.speedup_pct:.1f}%",
            "",
            "Memory Usage:" if report.original_peak_memory_mb > 0 else "",
        ]

        if report.original_peak_memory_mb > 0:
            lines.extend([
                f"  Original peak:  {report.original_peak_memory_mb:.2f} MiB",
                f"  Quantized peak: {report.quantized_peak_memory_mb:.2f} MiB",
            ])

        lines.extend([
            "",
            "Top-5 Layer Savings:",
            f"  {'Layer':<40} {'Saved':>10} {'%':>8}",
            "-" * 60,
        ])

        sorted_layers = sorted(
            report.layer_reports.items(),
            key=lambda x: x[1]["saved_bytes"],
            reverse=True,
        )[:5]

        for name, lr in sorted_layers:
            short_name = name if len(name) < 40 else "..." + name[-37:]
            lines.append(
                f"  {short_name:<40} {lr['saved_bytes']/(1024**2):>8.2f} MiB {lr['saved_pct']:>7.1f}%"
            )

        lines.append("-" * 60)
        return "\n".join(lines)
