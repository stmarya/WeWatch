"""Redis-backed participant state with a safe local-development fallback."""

from __future__ import annotations

import json
import logging
from collections.abc import MutableMapping


class SharedParticipants(MutableMapping):
    def __init__(self, redis_url: str | None, room: str = "default"):
        self._local: dict[str, dict] = {}
        self._redis = None
        safe_room = "".join(char if char.isalnum() or char in "-_" else "_" for char in room)
        self._prefix = f"wewatch:participants:{safe_room}:"
        if redis_url:
            try:
                import redis

                client = redis.Redis.from_url(redis_url, decode_responses=True)
                client.ping()
                self._redis = client
            except Exception as exc:
                logging.warning("Redis unavailable; using local participant state: %s", exc)

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

    def _key(self, key):
        return f"{self._prefix}{key}"

    def __getitem__(self, key):
        if self._redis:
            try:
                value = self._redis.get(self._key(key))
                if value is None:
                    raise KeyError(key)
                return json.loads(value)
            except (json.JSONDecodeError, TypeError) as exc:
                logging.warning("Removing corrupt participant state for %s: %s", key, exc)
                self._redis.delete(self._key(key))
                raise KeyError(key) from exc
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
        return iter(list(self._local))

    def __len__(self):
        if self._redis:
            return sum(1 for _ in self._redis.scan_iter(match=f"{self._prefix}*"))
        return len(self._local)

    def values(self):
        values = []
        for key in self:
            try:
                values.append(self[key])
            except KeyError:
                continue
        return values

    def items(self):
        items = []
        for key in self:
            try:
                items.append((key, self[key]))
            except KeyError:
                continue
        return items

    def clear(self):
        if self._redis:
            keys = list(self._redis.scan_iter(match=f"{self._prefix}*"))
            if keys:
                self._redis.delete(*keys)
        else:
            self._local.clear()

    def refresh(self, key):
        if self._redis:
            try:
                return bool(self._redis.expire(self._key(key), 300))
            except Exception:
                return False
        return key in self._local