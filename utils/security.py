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

class RedisRateLimiter:
    """Sliding-window limiter shared by every app replica through Redis.

    Uses one sorted set per key. If Redis is unavailable the limiter falls back
    to a local in-memory window so authentication keeps working (and is still
    throttled per process) instead of failing open globally.
    """

    def __init__(self, client, name: str, max_events: int, window_seconds: float):
        if max_events < 1 or window_seconds <= 0:
            raise ValueError("Rate limit values must be positive")
        self.client = client
        self.name = name
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._fallback = SlidingWindowRateLimiter(max_events, window_seconds)
        self._redis_down_until = 0.0

    def allow(self, key: str) -> bool:
        import logging
        import secrets as _secrets

        if time.monotonic() < self._redis_down_until:
            return self._fallback.allow(key)

        redis_key = f"wewatch:ratelimit:{self.name}:{key}"
        now = time.time()
        member = f"{now:.6f}:{_secrets.token_hex(4)}"
        try:
            pipe = self.client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, now - self.window_seconds)
            pipe.zadd(redis_key, {member: now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, int(self.window_seconds) + 1)
            _, _, count, _ = pipe.execute()
            if count > self.max_events:
                # Do not let rejected attempts extend the window indefinitely.
                self.client.zrem(redis_key, member)
                return False
            return True
        except Exception as exc:  # redis.exceptions.RedisError and connection errors
            logging.warning("Redis rate limiter unavailable (%s); using local fallback for 30s", exc)
            # Circuit breaker: avoid paying the connect timeout on every request.
            self._redis_down_until = time.monotonic() + 30
            return self._fallback.allow(key)


_redis_client = None


def make_rate_limiter(name: str, max_events: int, window_seconds: float, redis_url: str | None = None):
    """Return a Redis-backed limiter when ``redis_url`` is set, else in-memory."""
    global _redis_client
    if redis_url:
        try:
            import redis

            if _redis_client is None:
                _redis_client = redis.Redis.from_url(redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
            return RedisRateLimiter(_redis_client, name, max_events, window_seconds)
        except ImportError:
            pass
    return SlidingWindowRateLimiter(max_events, window_seconds)
