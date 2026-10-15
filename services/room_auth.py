"""Short-lived signed room tokens for the WebRTC signaling service.

This is intentionally dependency-free so the signaling service can validate
tokens before Redis or the optional SFU stack is installed.
"""

from __future__ import annotations

import base64
import binascii
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


def issue_room_token(room: str, identity: str, role: str = "client", ttl: int = 3600, *, target_identity: str | None = None) -> str:
    if not isinstance(identity, str) or not identity.strip() or len(identity) > 128:
        raise ValueError("Identity must contain 1–128 characters")
    if not isinstance(room, str) or not room.strip() or len(room) > 128:
        raise ValueError("Invalid room")
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
    if role == 'agent':
        if not isinstance(target_identity, str) or not target_identity.strip() or len(target_identity) > 128:
            raise ValueError('Agent token requires a paired target_identity')
        payload['target_identity'] = target_identity
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signature = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{signature}"


def verify_room_token(token: str, room: str, identity: str | None = None) -> dict:
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError("Invalid token format")
        raw, signature = token.split(".", 1)
        expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid token signature")
        padded = raw + ("=" * (-len(raw) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if not isinstance(payload, dict):
            raise ValueError("Invalid token claims")
        if payload.get("role") not in {"admin", "client", "agent"}:
            raise ValueError("Invalid role")
        if not isinstance(payload.get("identity"), str) or not payload["identity"] or len(payload["identity"]) > 128:
            raise ValueError("Invalid identity")
        if payload["room"] != room or int(payload["exp"]) <= int(time.time()):
            raise ValueError("Expired or wrong-room token")
        if identity and payload["identity"] != identity:
            raise ValueError("Token identity mismatch")
        return payload
    except (
        ValueError,
        KeyError,
        TypeError,
        OverflowError,
        UnicodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Invalid room token") from exc