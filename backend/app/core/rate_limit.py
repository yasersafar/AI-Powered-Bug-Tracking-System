"""Small in-process sliding-window rate limiter used for /auth/login.

Each backend replica keeps its own counters. That is enough to slow down password guessing
against a single instance; a multi-replica deployment should put the same limit on the
reverse proxy (documented in docs/deployment).
"""

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Record an attempt. Returns None if allowed, else seconds until the next slot frees."""
        current = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and current - hits[0] >= self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_attempts:
                return max(0.0, self.window_seconds - (current - hits[0]))
            hits.append(current)
            return None

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
