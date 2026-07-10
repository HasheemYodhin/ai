"""
CLI-specific configuration for the dabba terminal agent.

Manages CLI settings at ~/.config/dabba/cli_config.yaml including API
endpoint, default generation parameters, theme, and key bindings.
"""

from __future__ import annotations

import os
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from dabba.utils.paths import get_dabba_config_dir

CLI_CONFIG_PATH = get_dabba_config_dir() / "cli_config.yaml"


@dataclass
class CliConfig:
    """
    CLI-specific configuration for the dabba terminal agent.

    Attributes:
        api_endpoint: Base URL for the dabba API server.
        api_key: Optional API key for authentication.
        default_model: Default model name to use.
        default_temperature: Default sampling temperature.
        default_max_tokens: Default maximum tokens per response.
        default_top_p: Default top-p sampling value.
        stream_output: Whether to stream tokens in real-time.
        show_token_usage: Display token counts after responses.
        show_tool_calls: Display tool call details.
        require_tool_approval: Require user approval before tool execution.
        permission_mode: One of "allow", "deny", "ask".
        history_file: Path to conversation history file.
        max_history_files: Maximum number of history files to keep.
        theme: Color theme name ("dark", "light", "monokai", etc.).
        syntax_theme: Pygments syntax highlighting theme.
        auto_save_interval: Seconds between auto-saves (0 to disable).
        watch_files: Enable file watching for context.
        watch_extensions: File extensions to watch.
    """

    api_endpoint: str = "http://localhost:8080"
    api_key: str = ""
    default_model: str = "dabba"
    effort: str = "medium"
    api_keys: Dict[str, str] = field(default_factory=dict)
    default_temperature: float = 0.7
    default_max_tokens: int = 4096
    default_top_p: float = 0.9
    stream_output: bool = True
    show_token_usage: bool = True
    show_tool_calls: bool = True
    require_tool_approval: bool = True
    permission_mode: str = "ask"
    history_file: str = str(get_dabba_config_dir() / "history.jsonl")
    max_history_files: int = 50
    theme: str = "dark"
    syntax_theme: str = "monokai"
    auto_save_interval: int = 120
    watch_files: bool = True
    watch_extensions: List[str] = field(
        default_factory=lambda: [".py", ".js", ".ts", ".rs", ".go", ".md", ".txt", ".yaml", ".json", ".toml"]
    )
    # Remote/container execution allowlists — empty means "deny all" by
    # default, since these tools reach outside the local sandboxed cwd.
    allowed_ssh_hosts: List[str] = field(default_factory=list)
    allowed_docker_containers: List[str] = field(default_factory=list)
    allowed_docker_images: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> CliConfig:
        """
        Load CLI configuration from a YAML file.

        Creates the file with defaults if it does not exist.

        Args:
            path: Path to the config file. Defaults to ~/.config/dabba/cli_config.yaml.

        Returns:
            Loaded CliConfig instance.
        """
        config_path = path or CLI_CONFIG_PATH
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            instance = cls()
            instance.save(config_path)
            return instance

        with open(config_path, "r") as f:
            raw = yaml.safe_load(f) or {}

        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in raw.items() if k in valid_keys}
        return cls(**filtered)

    def save(self, path: Optional[Path] = None) -> None:
        """
        Save CLI configuration to a YAML file.

        Args:
            path: Target file path. Defaults to the current config path.
        """
        config_path = path or CLI_CONFIG_PATH
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            yaml.dump(asdict(self), f, default_flow_style=False, sort_keys=False)

    def set(self, key: str, value: str) -> None:
        """
        Set a configuration key from a string value.

        Performs type coercion to match the field type.

        Args:
            key: Configuration key name.
            value: String value to parse and set.

        Raises:
            KeyError: If the key is not a valid configuration field.
            ValueError: If the value cannot be coerced to the field type.
        """
        if key not in self.__dataclass_fields__:
            raise KeyError(f"Unknown configuration key: '{key}'")

        field_def = self.__dataclass_fields__[key]
        field_type = field_def.type

        type_map: Dict[type, type] = {
            str: str,
            int: int,
            float: float,
            bool: bool,
        }

        if field_type in type_map:
            coerced = type_map[field_type](value)
        elif field_type == bool:
            coerced = value.lower() in ("true", "yes", "1", "on")
        elif getattr(field_type, "__origin__", None) is list:
            coerced = [v.strip() for v in value.split(",") if v.strip()]
        else:
            coerced = value

        setattr(self, key, coerced)
        self.save()

    def get_api_headers(self) -> Dict[str, str]:
        """
        Get HTTP headers for API requests.

        Returns:
            Dictionary of headers including authorization if configured.
        """
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
