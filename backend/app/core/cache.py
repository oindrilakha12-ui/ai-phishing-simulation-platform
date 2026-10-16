"""In-process TTL cache with per-organization invalidation.

Analytics aggregates are cached per org. Any mutation that changes an org's campaign or
event data calls `cache.invalidate_org(org_id)`, so stale numbers are never served past a write.
If REDIS_URL is set, swap in a Redis-backed implementation (feature flag, see docs).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self.ttl = ttl_seconds
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_set(self, key: str, factory: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry and entry[0] > now:
                self.hits += 1
                return entry[1]
        self.misses += 1
        value = factory()
        with self._lock:
            self._data[key] = (now + self.ttl, value)
        return value

    def invalidate_org(self, org_id: str) -> None:
        prefix = f"org:{org_id}:"
        with self._lock:
            for key in [k for k in self._data if k.startswith(prefix)]:
                del self._data[key]

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


cache = TTLCache(ttl_seconds=120)
