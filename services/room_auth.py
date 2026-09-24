"""Short-lived signed room tokens for the WebRTC signaling service.

This is intentionally dependency-free so the signaling service can validate
tokens before Redis or the optional SFU stack is installed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time


def _secret() -> bytes:
    secret = os.getenv("WEBRTC_SECRET_KEY", "").strip()
    if len(secret) < 32:
        raise RuntimeError("WEBRTC_SECRET_KEY must contain at least 32 characters")
    return secret.encode("utf-8")


def issue_room_token(room: str, identity: str, role: str = "client", ttl: int = 3600) -> str:
    if role not in {"admin", "client", "agent"}:
        raise ValueError("Unsupported room role")
    now = int(time.time())
    payload = {
        "room": room,
        "identity": identity[:128],
        "role": role,
        "iat": now,
        "exp": now + max(60, min(ttl, 86400)),
    }
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signature = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{signature}"


def verify_room_token(token: str, room: str, identity: str | None = None) -> dict:
    try:
        raw, signature = token.split(".", 1)
        expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid token signature")
        padded = raw + ("=" * (-len(raw) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload["room"] != room or int(payload["exp"]) < int(time.time()):
            raise ValueError("Expired or wrong-room token")
        if identity and payload["identity"] != identity:
            raise ValueError("Token identity mismatch")
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid room token") from exc