"""Minimal LiveKit-compatible JWT generation without a heavy SDK dependency."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def issue_livekit_token(room: str, identity: str, ttl: int = 3600) -> str:
    api_key = os.getenv("LIVEKIT_API_KEY", "").strip()
    api_secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise RuntimeError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required")
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {
        "iss": api_key,
        "sub": identity[:128],
        "nbf": now,
        "exp": now + max(60, min(ttl, 86400)),
        "video": {"roomJoin": True, "room": room, "canPublish": True, "canSubscribe": True},
    }
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode()
    signature = _b64(hmac.new(api_secret.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"