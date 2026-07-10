"""
API server configuration for FastAPI-based serving.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ApiConfig:
    """
    Configuration for the FastAPI inference server with OpenAI-compatible
    endpoints, authentication, and rate limiting.
    """

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 1
    cors_origins: List[str] = field(
        default_factory=lambda: ["*"]
    )

    # Model serving
    default_model: str = "dabba"
    available_models: List[str] = field(
        default_factory=lambda: ["dabba", "llama3", "gpt-4"]
    )
    max_context_length: int = 128000
    max_generation_tokens: int = 4096

    # Authentication
    auth_enabled: bool = True
    api_keys: List[str] = field(default_factory=lambda: [])
    jwt_secret: Optional[str] = None
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 300
    rate_limit_burst: int = 40

    # Streaming
    stream_chunk_size: int = 4  # tokens per chunk
    stream_timeout_seconds: int = 300

    # OpenAI compatibility
    openai_compatible: bool = True
    api_prefix: str = "/v1"

    # Logging
    log_level: str = "info"
    log_requests: bool = True
    log_to_file: bool = False
    log_file: Optional[str] = None

    # Health check
    health_check_path: str = "/health"

    # File uploads
    max_upload_size_mb: int = 100
    upload_dir: str = "./tmp/uploads"
