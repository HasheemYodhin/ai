"""
API authentication module.

Supports API key-based authentication (Bearer tokens) and optional
JWT-based authentication for user sessions.
"""

import hashlib
import hmac
import time
from typing import Dict, List, Optional, Set

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from dabba.config.api_config import ApiConfig


class ApiKeyAuth:
    """
    API key authentication handler.

    Validates API keys from the Authorization header using Bearer scheme.
    Supports multiple API keys with optional rate limit tiers.

    Args:
        api_keys: List of valid API keys.
        config: API configuration (for JWT settings).
    """

    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        config: Optional[ApiConfig] = None,
    ):
        self.api_keys: Set[str] = set(api_keys or [])
        self.config = config
        self._key_metadata: Dict[str, Dict] = {}
        self._rate_limits: Dict[str, int] = {}

        self.security = HTTPBearer(auto_error=False)

    def add_key(self, key: str, metadata: Optional[Dict] = None) -> None:
        """
        Add a valid API key.

        Args:
            key: The API key string.
            metadata: Optional metadata (e.g., rate limit tier, user ID).
        """
        self.api_keys.add(key)
        if metadata:
            self._key_metadata[key] = metadata

    def remove_key(self, key: str) -> None:
        """Remove an API key."""
        self.api_keys.discard(key)
        self._key_metadata.pop(key, None)

    def is_valid(self, key: str) -> bool:
        """
        Check if an API key is valid.

        Uses constant-time comparison to prevent timing attacks.

        Args:
            key: API key to validate.

        Returns:
            True if the key is valid.
        """
        for valid_key in self.api_keys:
            if hmac.compare_digest(key, valid_key):
                return True
        return False

    async def __call__(
        self,
        credentials: Optional[HTTPAuthorizationCredentials] = Security(HTTPBearer(auto_error=False)),
        request: Optional[Request] = None,
    ) -> Optional[str]:
        """
        FastAPI dependency for API key authentication.

        Args:
            credentials: Bearer token from the Authorization header.
            request: FastAPI request object.

        Returns:
            The validated API key if authentication succeeds.

        Raises:
            HTTPException: If authentication fails.
        """
        if not self.api_keys:
            return None

        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Missing authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not self.is_valid(credentials.credentials):
            raise HTTPException(
                status_code=403,
                detail="Invalid API key",
            )

        return credentials.credentials

    def generate_key(self, prefix: str = "dab-") -> str:
        """
        Generate a new API key.

        Args:
            prefix: Prefix for the key.

        Returns:
            A new API key string.
        """
        import secrets
        key = prefix + secrets.token_hex(24)
        return key

    def hash_key(self, key: str) -> str:
        """
        Hash an API key for storage (never store raw keys).

        Args:
            key: API key to hash.

        Returns:
            SHA-256 hash of the key.
        """
        return hashlib.sha256(key.encode()).hexdigest()


def authenticate_request(token: Optional[str] = None, api_key: Optional[str] = None) -> bool:
    """Simple callable for test mocking; real auth is handled by ApiKeyAuth."""
    return bool(token or api_key)
