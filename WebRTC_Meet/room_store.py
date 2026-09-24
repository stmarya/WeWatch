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
            try:
                value = self._redis.get(self._prefix + name)
                return default if value is None else json.loads(value)
            except (json.JSONDecodeError, TypeError) as exc:
                logging.warning("Ignoring corrupt room state %s: %s", name, exc)
                self._redis.delete(self._prefix + name)
                return default
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

    def update(self, name, updater, default=None, ttl=86400, retries=5):
        """Atomically update one JSON value when Redis is available."""
        if not self._redis:
            with self._lock:
                current = self._local.get(name, default)
                updated = updater(current)
                self._local[name] = updated
                return updated

        from redis.exceptions import WatchError

        key = self._prefix + name
        for _ in range(retries):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    try:
                        current = default if raw is None else json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        logging.warning("Resetting corrupt room state %s during update", name)
                        current = default
                    updated = updater(current)
                    pipe.multi()
                    pipe.set(key, json.dumps(updated), ex=ttl)
                    pipe.execute()
                    return updated
            except WatchError:
                continue
        raise RuntimeError(f"Could not atomically update room state: {name}")