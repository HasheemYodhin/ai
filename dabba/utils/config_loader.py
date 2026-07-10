"""
Configuration loading utilities. Supports loading from YAML files
and merging with command-line overrides.
"""

import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar

from dabba.config.model_config import ModelConfig
from dabba.config.training_config import TrainingConfig
from dabba.config.data_config import DataConfig
from dabba.config.rag_config import RagConfig
from dabba.config.agent_config import AgentConfig
from dabba.config.multimodal_config import MultimodalConfig
from dabba.config.api_config import ApiConfig

T = TypeVar("T")


def load_yaml(path: str) -> Dict[str, Any]:
    """
    Load a YAML file and return its contents as a dictionary.

    Args:
        path: Path to the YAML file.

    Returns:
        Dictionary of configuration values.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the YAML is malformed.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_json(path: str) -> Dict[str, Any]:
    """
    Load a JSON file and return its contents as a dictionary.

    Args:
        path: Path to the JSON file.

    Returns:
        Dictionary of configuration values.
    """
    path = Path(path)
    with open(path, "r") as f:
        return json.load(f)


def load_config(
    config_path: str,
    model_preset: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> tuple:
    """
    Load complete configuration from a YAML file with optional overrides.

    The YAML file should contain sections for 'model', 'training', 'data',
    and optionally 'rag', 'agent', 'multimodal', 'api'.

    Args:
        config_path: Path to the YAML configuration file.
        model_preset: Optional model preset name ("tiny", "small", etc.).
        overrides: Optional dictionary of overrides (e.g., from CLI).

    Returns:
        Tuple of (ModelConfig, TrainingConfig, DataConfig, optional_configs_dict).
    """
    raw = load_yaml(config_path)

    if overrides:
        _deep_merge(raw, overrides)

    model_kwargs = raw.get("model", {})
    if model_preset:
        model_config = ModelConfig.from_preset(model_preset, **model_kwargs)
    else:
        model_config = ModelConfig(**model_kwargs)

    training_config = TrainingConfig(**raw.get("training", {}))
    data_config = DataConfig(**raw.get("data", {}))

    optional = {}
    if "rag" in raw:
        optional["rag"] = RagConfig(**raw["rag"])
    if "agent" in raw:
        optional["agent"] = AgentConfig(**raw["agent"])
    if "multimodal" in raw:
        optional["multimodal"] = MultimodalConfig(**raw["multimodal"])
    if "api" in raw:
        optional["api"] = ApiConfig(**raw["api"])

    return model_config, training_config, data_config, optional


def _deep_merge(base: Dict, override: Dict) -> None:
    """
    Recursively merge override dictionary into base dictionary.

    Args:
        base: Base dictionary to merge into.
        override: Override dictionary with new values.
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def save_config(config: Any, path: str) -> None:
    """
    Save a dataclass configuration to a YAML file.

    Args:
        config: A dataclass instance (ModelConfig, TrainingConfig, etc.).
        path: File path to save to.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(config, "__dataclass_fields__"):
        data = {k: getattr(config, k) for k in config.__dataclass_fields__}
    elif isinstance(config, dict):
        data = config
    else:
        data = config

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
