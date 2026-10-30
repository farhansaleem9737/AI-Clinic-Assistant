"""A small fixed-window rate limiter for public, token-guessing-prone
endpoints (D87).

Kept in process memory: it bounds attempts per client IP on one API process.
Several processes would each keep their own count, so behind a load balancer
this is a floor, not a guarantee; a shared store (e.g. Redis) would be needed
for a global limit.
"""

import time
from collections.abc import Callable
from threading import Lock

from fastapi import Request

from app.core.exceptions import RateLimitedError


class FixedWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], tuple[float, int]] = {}
        self._lock = Lock()

    def hit(self, scope: str, key: str, limit: int, window_seconds: float) -> bool:
        """Count one attempt. False when the caller is over the limit."""
        now = time.monotonic()
        with self._lock:
            start, count = self._hits.get((scope, key), (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            count += 1
            self._hits[(scope, key)] = (start, count)
            if len(self._hits) > 10_000:  # forget stale windows
                self._hits = {k: v for k, v in self._hits.items() if now - v[0] < window_seconds}
            return count <= limit

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = FixedWindowLimiter()


def rate_limit(scope: str, limit: Callable[[], int], window_seconds: float = 60) -> Callable:
    """Dependency: at most ``limit()`` requests per client IP per window."""

    async def dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        if not limiter.hit(scope, ip, limit(), window_seconds):
            raise RateLimitedError("Too many attempts. Please wait a minute and try again.")

    return dependency
