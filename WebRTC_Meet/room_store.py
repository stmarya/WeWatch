"""Small shared room-state store.

Redis is used when REDIS_URL is configured; an in-process store keeps local
development and single-process deployments functional.
"""

from __future__ import annotations

import json
import logging
from threading import RLock


class RoomStore:
    def __init__(self, redis_url: str | None, room: str):
        self._local: dict[str, object] = {}
        self._lock = RLock()
        self._prefix = f"wewatch:room:{room}:"
        self._redis = None
        if redis_url:
            try:
                import redis

                client = redis.Redis.from_url(redis_url, decode_responses=True)
                client.ping()
                self._redis = client
            except Exception as exc:
                logging.warning("Redis room state unavailable; using local state: %s", exc)

    @property
    def shared(self):
        return self._redis is not None

    def healthy(self):
        if not self._redis:
            return False
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    def get(self, name, default=None):
        if self._redis:
            value = self._redis.get(self._prefix + name)
            return default if value is None else json.loads(value)
        with self._lock:
            return self._local.get(name, default)

    def set(self, name, value, ttl=86400):
        if self._redis:
            self._redis.set(self._prefix + name, json.dumps(value), ex=ttl)
        else:
            with self._lock:
                self._local[name] = value

    def delete(self, name):
        if self._redis:
            self._redis.delete(self._prefix + name)
        else:
            with self._lock:
                self._local.pop(name, None)