"""Central provider reliability, routing, and normalized errors."""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar

from dabba.platform.core import PlatformStore, get_platform_store, utc_ms

T = TypeVar("T")


@dataclass
class ProviderFailure(Exception):
    message: str
    code: str
    retryable: bool
    status_code: int = 503
    provider: Optional[str] = None
    model: Optional[str] = None
    retry_after_ms: Optional[int] = None
    fallback_model: Optional[str] = None

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "type": "provider_error",
            "code": self.code,
            "retryable": self.retryable,
            "provider": self.provider,
            "model": self.model,
            "retryAfterMs": self.retry_after_ms,
            "fallbackModel": self.fallback_model,
        }


def normalize_provider_error(
    exc: Exception, *, provider: Optional[str] = None, model: Optional[str] = None
) -> ProviderFailure:
    if isinstance(exc, ProviderFailure):
        return exc
    raw = str(exc)
    lowered = raw.lower()
    if any(
        marker in lowered
        for marker in (
            "resourceexhausted",
            "resource exhausted",
            "request limit reached",
            "capacity",
            "overloaded",
            "503",
        )
    ):
        return ProviderFailure(
            "The selected model is temporarily at capacity.",
            "provider_capacity",
            True,
            503,
            provider,
            model,
        )
    if any(marker in lowered for marker in ("429", "rate limit", "too many requests")):
        return ProviderFailure(
            "The provider rate limit was reached. Dabba will retry shortly.",
            "provider_rate_limit",
            True,
            429,
            provider,
            model,
        )
    if any(
        marker in lowered for marker in ("timed out", "timeout", "deadline exceeded")
    ):
        return ProviderFailure(
            "The model took too long to respond.",
            "provider_timeout",
            True,
            504,
            provider,
            model,
        )
    if any(
        marker in lowered
        for marker in ("401", "403", "unauthorized", "invalid api key", "forbidden")
    ):
        return ProviderFailure(
            "The provider credentials are missing, expired, or lack permission.",
            "provider_authentication",
            False,
            401,
            provider,
            model,
        )
    if any(
        marker in lowered
        for marker in ("context length", "maximum context", "too many tokens")
    ):
        return ProviderFailure(
            "The request is larger than this model's context window.",
            "context_length_exceeded",
            False,
            422,
            provider,
            model,
        )
    return ProviderFailure(
        "The model provider could not complete this request.",
        "provider_unavailable",
        True,
        503,
        provider,
        model,
    )


class ProviderGateway:
    """Persistent circuit breakers, retries, fallback chains, and health."""

    def __init__(
        self,
        store: Optional[PlatformStore] = None,
        *,
        max_attempts: int = 2,
        failure_threshold: int = 3,
        cooldown_seconds: int = 60,
    ):
        self.store = store or get_platform_store()
        self.max_attempts = max(1, max_attempts)
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(1, cooldown_seconds)
        self._lock = threading.RLock()

    def fallback_chain(self, model: str) -> list[str]:
        raw = os.environ.get("DABBA_MODEL_FALLBACKS", "")
        if not raw:
            return []
        try:
            configured = json.loads(raw)
        except ValueError:
            return []
        value = configured.get(model, []) if isinstance(configured, dict) else []
        if isinstance(value, str):
            value = [value]
        return [
            candidate
            for candidate in value
            if isinstance(candidate, str) and candidate != model
        ]

    def run(
        self,
        model: str,
        operation: Callable[[str], T],
        *,
        provider_for: Callable[[str], str],
    ) -> T:
        models = [model, *self.fallback_chain(model)]
        last_failure: Optional[ProviderFailure] = None
        for index, candidate in enumerate(models):
            provider = provider_for(candidate)
            if self._is_blocked(provider, candidate):
                last_failure = ProviderFailure(
                    "The selected model is cooling down after repeated failures.",
                    "provider_circuit_open",
                    True,
                    503,
                    provider,
                    candidate,
                    retry_after_ms=self.cooldown_seconds * 1000,
                )
                continue
            for attempt in range(self.max_attempts):
                started = time.perf_counter()
                try:
                    result = operation(candidate)
                    self._success(
                        provider, candidate, (time.perf_counter() - started) * 1000
                    )
                    return result
                except Exception as exc:
                    failure = normalize_provider_error(
                        exc, provider=provider, model=candidate
                    )
                    last_failure = failure
                    self._failure(provider, candidate, failure)
                    if not failure.retryable or attempt + 1 >= self.max_attempts:
                        break
                    time.sleep(self._backoff(attempt))
            if last_failure and index + 1 < len(models):
                last_failure.fallback_model = models[index + 1]
        raise last_failure or ProviderFailure(
            "No provider was available for this request.",
            "no_provider_available",
            True,
            model=model,
        )

    def stream(
        self,
        model: str,
        operation: Callable[[str], Iterator[str]],
        *,
        provider_for: Callable[[str], str],
    ) -> Iterator[str]:
        models = [model, *self.fallback_chain(model)]
        last_failure: Optional[ProviderFailure] = None
        for index, candidate in enumerate(models):
            provider = provider_for(candidate)
            if self._is_blocked(provider, candidate):
                continue
            for attempt in range(self.max_attempts):
                started = time.perf_counter()
                emitted = False
                try:
                    for token in operation(candidate):
                        emitted = emitted or bool(token)
                        yield token
                    self._success(
                        provider, candidate, (time.perf_counter() - started) * 1000
                    )
                    return
                except Exception as exc:
                    failure = normalize_provider_error(
                        exc, provider=provider, model=candidate
                    )
                    last_failure = failure
                    self._failure(provider, candidate, failure)
                    # Retrying a partially emitted stream duplicates content. Provider
                    # adapters may implement their own continuation before this layer.
                    if emitted:
                        raise failure
                    if not failure.retryable or attempt + 1 >= self.max_attempts:
                        break
                    time.sleep(self._backoff(attempt))
            if last_failure and index + 1 < len(models):
                last_failure.fallback_model = models[index + 1]
        raise last_failure or ProviderFailure(
            "No provider was available for this request.",
            "no_provider_available",
            True,
            model=model,
        )

    def health(self) -> list[Dict[str, Any]]:
        rows = self.store.fetchall(
            "SELECT * FROM provider_health ORDER BY provider, model"
        )
        return [
            {
                "provider": row["provider"],
                "model": row["model"],
                "state": row["state"],
                "successes": row["successes"],
                "failures": row["failures"],
                "consecutiveFailures": row["consecutive_failures"],
                "latencyMs": row["latency_ms"],
                "lastErrorCode": row["last_error_code"],
                "lastErrorMessage": row["last_error_message"],
                "blockedUntil": row["blocked_until"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    def _is_blocked(self, provider: str, model: str) -> bool:
        row = self.store.fetchone(
            "SELECT blocked_until FROM provider_health WHERE provider=? AND model=?",
            (provider, model),
        )
        return bool(row and row["blocked_until"] and row["blocked_until"] > utc_ms())

    def _success(self, provider: str, model: str, latency_ms: float) -> None:
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO provider_health
                    (provider, model, state, successes, latency_ms, updated_at)
                VALUES (?, ?, 'healthy', 1, ?, ?)
                ON CONFLICT(provider, model) DO UPDATE SET
                    state='healthy',
                    successes=provider_health.successes+1,
                    consecutive_failures=0,
                    latency_ms=CASE
                        WHEN provider_health.latency_ms IS NULL THEN excluded.latency_ms
                        ELSE provider_health.latency_ms*0.8 + excluded.latency_ms*0.2 END,
                    last_error_code=NULL,
                    last_error_message=NULL,
                    blocked_until=NULL,
                    updated_at=excluded.updated_at
                """,
                (provider, model, latency_ms, now),
            )

    def _failure(self, provider: str, model: str, failure: ProviderFailure) -> None:
        now = utc_ms()
        with self.store.transaction() as conn:
            current = conn.execute(
                """
                SELECT consecutive_failures FROM provider_health
                WHERE provider=? AND model=?
                """,
                (provider, model),
            ).fetchone()
            consecutive = int(current["consecutive_failures"] if current else 0) + 1
            blocked_until = (
                now + self.cooldown_seconds * 1000
                if consecutive >= self.failure_threshold
                else None
            )
            state = "open" if blocked_until else "degraded"
            conn.execute(
                """
                INSERT INTO provider_health
                    (provider, model, state, failures, consecutive_failures,
                     last_error_code, last_error_message, blocked_until, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, model) DO UPDATE SET
                    state=excluded.state,
                    failures=provider_health.failures+1,
                    consecutive_failures=excluded.consecutive_failures,
                    last_error_code=excluded.last_error_code,
                    last_error_message=excluded.last_error_message,
                    blocked_until=excluded.blocked_until,
                    updated_at=excluded.updated_at
                """,
                (
                    provider,
                    model,
                    state,
                    consecutive,
                    failure.code,
                    failure.message,
                    blocked_until,
                    now,
                ),
            )

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(4.0, 0.5 * (2**attempt)) + random.uniform(0.0, 0.2)
