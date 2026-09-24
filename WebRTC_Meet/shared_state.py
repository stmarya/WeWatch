"""Redis-backed participant state with a safe local-development fallback."""

from __future__ import annotations

import json
import logging
from collections.abc import MutableMapping


class SharedParticipants(MutableMapping):
    def __init__(self, redis_url: str | None):
        self._local: dict[str, dict] = {}
        self._redis = None
        self._prefix = "wewatch:participants:"
        if redis_url:
            try:
                import redis

                client = redis.Redis.from_url(redis_url, decode_responses=True)
                client.ping()
                self._redis = client
            except Exception as exc:
                logging.warning("Redis unavailable; using local participant state: %s", exc)

    def _key(self, key):
        return f"{self._prefix}{key}"

    def __getitem__(self, key):
        if self._redis:
            value = self._redis.get(self._key(key))
            if value is None:
                raise KeyError(key)
            return json.loads(value)
        return self._local[key]

    def __setitem__(self, key, value):
        if self._redis:
            self._redis.set(self._key(key), json.dumps(value), ex=300)
        else:
            self._local[key] = value

    def __delitem__(self, key):
        if self._redis:
            if not self._redis.delete(self._key(key)):
                raise KeyError(key)
        else:
            del self._local[key]

    def __iter__(self):
        if self._redis:
            prefix_len = len(self._prefix)
            return iter(
                [key[prefix_len:] for key in self._redis.scan_iter(match=f"{self._prefix}*")]
            )
        return iter(self._local)

    def __len__(self):
        if self._redis:
            return sum(1 for _ in self._redis.scan_iter(match=f"{self._prefix}*"))
        return len(self._local)

    def values(self):
        return [self[key] for key in self]

    def items(self):
        return [(key, self[key]) for key in self]

    def clear(self):
        if self._redis:
            keys = list(self._redis.scan_iter(match=f"{self._prefix}*"))
            if keys:
                self._redis.delete(*keys)
        else:
            self._local.clear()

    def refresh(self, key):
        if self._redis:
            return bool(self._redis.expire(self._key(key), 300))
        return key in self._local