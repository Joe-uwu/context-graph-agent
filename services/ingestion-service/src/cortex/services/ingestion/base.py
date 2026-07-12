"""Shared connector machinery: dedup, retry with backoff, token-bucket rate limiting.

Real connectors subclass BaseConnector to inherit these so per-source code stays about
the API, not about resilience plumbing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class TokenBucket:
    """Simple rate limiter. In production this is backed by Redis so it is shared across
    connector replicas; here it is in-process."""

    def __init__(self, rate_per_sec: float, capacity: int) -> None:
        self._rate = rate_per_sec
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last = time.monotonic()

    def take(self, n: int = 1) -> None:
        while True:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= n:
                self._tokens -= n
                return
            time.sleep((n - self._tokens) / self._rate)


class BaseConnector:
    def __init__(self, source: str, *, rate_per_sec: float = 10.0, capacity: int = 20) -> None:
        self.source = source
        self._seen: set[str] = set()
        self._bucket = TokenBucket(rate_per_sec, capacity)

    def dedup(self, external_id: str) -> bool:
        """Return True if this id is new (and record it), False if already seen."""
        if external_id in self._seen:
            return False
        self._seen.add(external_id)
        return True

    def with_retry(self, fn: Callable[[], T], *, attempts: int = 5, base_delay: float = 0.2) -> T:
        last: Exception | None = None
        for i in range(attempts):
            try:
                self._bucket.take()
                return fn()
            except Exception as exc:  # noqa: BLE001 - connectors retry transient API errors
                last = exc
                time.sleep(base_delay * (2**i))
        assert last is not None
        raise last
