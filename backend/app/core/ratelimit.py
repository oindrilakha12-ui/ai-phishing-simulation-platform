"""Tiny in-process sliding-window rate limiter.

Good enough for a single instance. With several instances you would back this with Redis
(see PRODUCTION_ROADMAP.md).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import RateLimited


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        """Record one hit. Return False if the caller is over the limit."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit_setting: str):
    """FastAPI dependency factory: `Depends(rate_limit("auth", "rate_limit_auth"))`."""
    from app.core.config import get_settings

    def _dep(request: Request) -> None:
        limit = getattr(get_settings(), limit_setting)
        if not limiter.hit(f"{bucket}:{client_ip(request)}", limit):
            raise RateLimited(f"Too many {bucket} requests, please slow down")

    return _dep
