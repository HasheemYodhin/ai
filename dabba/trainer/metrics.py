"""
Metrics tracking for training and evaluation.

Provides loss tracking, smoothed metrics, perplexity computation,
and logging utilities for TensorBoard and console output.
"""

import json
import math
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

import torch
from torch.utils.tensorboard import SummaryWriter


class MetricsTracker:
    """
    Tracks training and validation metrics over time.

    Supports:
        - Running average of loss and other scalar metrics
        - Perplexity computation from loss
        - TensorBoard logging
        - JSON metrics export
        - Metric history for analysis

    Args:
        log_dir: Directory for TensorBoard logs and metrics export.
        log_steps: Log metrics every N steps.
        window_size: Number of steps for running averages.
    """

    def __init__(
        self,
        log_dir: str = "./logs",
        log_steps: int = 10,
        window_size: int = 100,
    ):
        self.log_dir = Path(log_dir)
        self.log_steps = log_steps
        self.window_size = window_size

        self._metrics: Dict[str, List[float]] = {}
        self._windows: Dict[str, deque] = {}
        self._step_counter = 0
        self._global_step = 0

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._writer = None

    @property
    def writer(self) -> SummaryWriter:
        """Lazy-initialized TensorBoard SummaryWriter."""
        if self._writer is None:
            self._writer = SummaryWriter(log_dir=str(self.log_dir))
        return self._writer

    @property
    def history(self) -> Dict[str, List[Dict]]:
        """History as {metric_name: [{step, value}, ...]}."""
        return {
            name: [{"step": i, "value": v} for i, v in enumerate(vals)]
            for name, vals in self._metrics.items()
        }

    def update(self, metrics_or_key, value: Optional[float] = None, step: Optional[int] = None) -> None:
        """
        Update metrics.

        Accepts either update("key", value) or update({"key": value}).
        """
        if isinstance(metrics_or_key, str):
            metrics = {metrics_or_key: value}
        else:
            metrics = metrics_or_key

        if step is not None:
            self._global_step = step
        else:
            self._global_step += 1

        self._step_counter += 1

        for key, val in metrics.items():
            if key not in self._metrics:
                self._metrics[key] = []
                self._windows[key] = deque(maxlen=self.window_size)
            self._metrics[key].append(val)
            self._windows[key].append(val)

    def _log_tensorboard(self, metrics: Dict[str, float]) -> None:
        """
        Log metrics to TensorBoard.

        Args:
            metrics: Dictionary of metric name to value.
        """
        for key, value in metrics.items():
            self.writer.add_scalar(key, value, self._global_step)
        self.writer.flush()

    def _log_console(self, metrics: Dict[str, float]) -> None:
        """
        Log metrics to console at the configured interval.

        Args:
            metrics: Dictionary of metric name to value.
        """
        if self._step_counter % self.log_steps == 0:
            parts = [f"Step {self._global_step}"]
            for key, value in metrics.items():
                if "lr" in key.lower():
                    parts.append(f"{key}: {value:.2e}")
                elif "loss" in key.lower():
                    parts.append(f"{key}: {value:.4f}")
                elif "ppl" in key.lower() or "perplexity" in key.lower():
                    parts.append(f"{key}: {value:.2f}")
                else:
                    parts.append(f"{key}: {value:.4f}")
            print(" | ".join(parts))

    def get_running(self, name: str) -> Optional[float]:
        """
        Get the running average of a metric.

        Args:
            name: Metric name.

        Returns:
            Running average value, or None if metric not tracked.
        """
        window = self._windows.get(name)
        if window and len(window) > 0:
            return sum(window) / len(window)
        return None

    def get_best(self, name: str, minimize: bool = True) -> Optional[float]:
        """
        Get the best (min or max) value for a metric.

        Args:
            name: Metric name.
            minimize: If True, return minimum. Otherwise return maximum.

        Returns:
            Best value, or None if metric not tracked.
        """
        values = self._metrics.get(name)
        if not values:
            return None
        return min(values) if minimize else max(values)

    def get_perplexity(self, loss_name: str = "loss") -> Optional[float]:
        """
        Compute perplexity from the latest loss value.

        Args:
            loss_name: Name of the loss metric.

        Returns:
            Perplexity value, or None if loss not tracked.
        """
        loss = self.get_running(loss_name)
        if loss is not None:
            return math.exp(min(loss, 100))
        return None

    def export_json(self, path: Optional[str] = None) -> str:
        """
        Export all metrics to a JSON file.

        Args:
            path: Output file path (default: log_dir/metrics.json).

        Returns:
            Path to the exported file.
        """
        export_path = Path(path or self.log_dir / "metrics.json")
        data = {
            "metrics": {
                name: {
                    "values": values,
                    "mean": sum(values) / len(values) if values else 0,
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                    "latest": values[-1] if values else 0,
                }
                for name, values in self._metrics.items()
            },
            "total_steps": self._global_step,
        }
        with open(export_path, "w") as f:
            json.dump(data, f, indent=2)
        return str(export_path)

    def average(self, key: str) -> float:
        """Return the mean of all recorded values for key."""
        vals = self._metrics.get(key, [])
        return sum(vals) / len(vals) if vals else 0.0

    def latest(self, key: str) -> Optional[float]:
        """Return the most recent value for key, or None."""
        vals = self._metrics.get(key)
        return vals[-1] if vals else None

    def best(self, key: str, mode: str = "min") -> Optional[Dict]:
        """Return {step, value} for the best recorded value."""
        vals = self._metrics.get(key)
        if not vals:
            return None
        if mode == "min":
            idx = vals.index(min(vals))
        else:
            idx = vals.index(max(vals))
        return {"step": idx, "value": vals[idx]}

    def reset(self) -> None:
        """Clear all metric history."""
        self._metrics.clear()
        self._windows.clear()
        self._step_counter = 0
        self._global_step = 0

    def save(self, path: str) -> None:
        """Save history to a JSON file."""
        with open(path, "w") as f:
            json.dump(self.history, f)

    @classmethod
    def load(cls, path: str) -> "MetricsTracker":
        """Load history from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, List[Dict]]:
        """Return history as a plain dict."""
        return self.history

    @classmethod
    def from_dict(cls, data: Dict[str, List[Dict]]) -> "MetricsTracker":
        """Create a MetricsTracker from a saved history dict."""
        tracker = cls(log_dir="/tmp/dabba_metrics_load")
        for key, entries in data.items():
            for entry in entries:
                tracker._metrics.setdefault(key, []).append(entry["value"])
                tracker._windows.setdefault(key, deque(maxlen=tracker.window_size)).append(entry["value"])
        return tracker

    def close(self) -> None:
        """Close the TensorBoard writer."""
        if self._writer is not None:
            self._writer.close()
            self._writer = None
