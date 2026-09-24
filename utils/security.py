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