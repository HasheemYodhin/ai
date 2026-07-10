"""
Rate limiting middleware for the API server.

Uses a token bucket algorithm with per-key and per-IP tracking
to prevent abuse while allowing burst traffic.
"""

import asyncio
import time
from collections import defaultdict
from typing import Dict, Optional, Tuple

from fastapi import HTTPException, Request


class TokenBucket:
    """
    Token bucket rate limiter.

    Maintains a bucket that refills at a steady rate up to a maximum
    burst capacity. Each request consumes one token.

    Args:
        rate: Number of tokens (requests) per minute.
        burst: Maximum burst size.
    """

    def __init__(self, rate: float = 60, burst: int = 10):
        self.rate = rate / 60.0  # Convert to per-second
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self) -> bool:
        """
        Try to consume one token from the bucket.

        Returns:
            True if a token was available and consumed.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


class RateLimiter:
    """
    Rate limiter for API endpoints.

    Supports per-API-key and per-IP rate limiting with configurable
    limits and burst allowance.

    Args:
        requests_per_minute: Maximum requests per minute.
        burst: Maximum burst size.
        enabled: If False, rate limiting is disabled.
        max_requests: Alias for requests_per_minute.
        window_seconds: Window duration in seconds (60 = 1 minute).
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        burst: int = 10,
        enabled: bool = True,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ):
        if max_requests is not None:
            requests_per_minute = max_requests
        if window_seconds is not None and window_seconds > 0:
            requests_per_minute = int(requests_per_minute * 60 / window_seconds)
        self._window_seconds = window_seconds if window_seconds else 60
        self._max_requests = max_requests if max_requests is not None else requests_per_minute
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self.enabled = enabled
        self._key_buckets: Dict[str, TokenBucket] = {}
        self._ip_buckets: Dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()
        # Synchronous per-user tracking for the simple interface
        self._sync_counts: Dict[str, int] = {}
        self._sync_windows: Dict[str, float] = {}

    def allow_request(self, user_id: str) -> bool:
        """Synchronous rate check for a user/key."""
        now = time.time()
        window = self._window_seconds
        if window <= 0:
            return True  # Zero-length window always allows
        last = self._sync_windows.get(user_id, 0)
        if now - last >= window:
            self._sync_counts[user_id] = 0
            self._sync_windows[user_id] = now
        count = self._sync_counts.get(user_id, 0)
        if count < self._max_requests:
            self._sync_counts[user_id] = count + 1
            return True
        return False

    def get_remaining(self, user_id: str) -> int:
        """Return remaining requests allowed in the current window."""
        now = time.time()
        window = self._window_seconds
        if window <= 0:
            return self._max_requests
        last = self._sync_windows.get(user_id, 0)
        if now - last >= window:
            return self._max_requests
        used = self._sync_counts.get(user_id, 0)
        return max(0, self._max_requests - used)

    def reset(self, user_id: str) -> None:
        """Reset the rate limit counter for a user."""
        self._sync_counts.pop(user_id, None)
        self._sync_windows.pop(user_id, None)

    async def _get_bucket(self, key: str, buckets: Dict) -> TokenBucket:
        """
        Get or create a token bucket for a key.

        Args:
            key: The rate limit key (API key or IP address).
            buckets: The bucket dictionary to look up.

        Returns:
            TokenBucket for the given key.
        """
        async with self._lock:
            if key not in buckets:
                buckets[key] = TokenBucket(
                    rate=self.requests_per_minute,
                    burst=self.burst,
                )
            return buckets[key]

    async def check(self, api_key: Optional[str] = None, ip: str = "") -> bool:
        """
        Check if a request is within rate limits.

        Args:
            api_key: Optional API key for per-key limiting.
            ip: Client IP address for per-IP limiting.

        Returns:
            True if the request is allowed.

        Raises:
            HTTPException: If rate limit is exceeded.
        """
        if not self.enabled:
            return True

        if api_key:
            bucket = await self._get_bucket(api_key, self._key_buckets)
            if not await bucket.consume():
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded for this API key",
                    headers={"Retry-After": "60"},
                )

        if ip:
            bucket = await self._get_bucket(ip, self._ip_buckets)
            if not await bucket.consume():
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded for this IP address",
                    headers={"Retry-After": "60"},
                )

        return True

    async def check_request(
        self,
        request: Request,
        api_key: Optional[str] = None,
    ) -> bool:
        """
        Convenience method to check rate limits from a FastAPI request.

        Args:
            request: FastAPI Request object.
            api_key: Optional API key.

        Returns:
            True if the request is allowed.
        """
        ip = request.client.host if request.client else "unknown"
        return await self.check(api_key=api_key, ip=ip)
