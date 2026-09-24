"""Small, dependency-free helpers used at trust boundaries."""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from threading import Lock


_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_face_name(value: str, default: str = "user_default") -> str:
    """Return a filesystem-safe, bounded identity name."""
    value = (value or "").strip()
    value = _NAME_RE.sub("_", value).strip("._-")
    return value[:64] or default


class Cooldown:
    """Thread-safe per-key cooldown for notifications and expensive actions."""

    def __init__(self, seconds: float = 15.0):
        self.seconds = seconds
        self._last: dict[str, float] = {}
        self._lock = Lock()

    def ready(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key, 0.0)
            if now - last < self.seconds:
                return False
            self._last[key] = now
            return True


class MajorityVote:
    """Keep an identity stable across transient detector misclassifications."""

    def __init__(self, size: int = 5):
        self._votes = deque(maxlen=size)

    def add(self, value: str) -> str:
        self._votes.append(value)
        counts = {item: self._votes.count(item) for item in set(self._votes)}
        return max(counts, key=counts.get)

    def clear(self) -> None:
        self._votes.clear()


class SlidingWindowRateLimiter:
    """Small in-memory limiter for single-process endpoints and socket events.

    Production deployments with multiple workers should enforce the same
    limits at the reverse proxy or Redis layer as well. This class still
    prevents accidental floods during local development and single-process
    operation without adding another dependency.
    """

    def __init__(self, max_events: int, window_seconds: float):
        if max_events < 1 or window_seconds <= 0:
            raise ValueError("Rate limit values must be positive")
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.max_events:
                return False
            events.append(now)
            if len(self._events) > 4096:
                self._events = defaultdict(
                    deque,
                    {
                        item_key: item_events
                        for item_key, item_events in self._events.items()
                        if item_events
                    },
                )
            return True