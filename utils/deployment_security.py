"""Deployment configuration checks shared by the dashboard and signaling app."""

from __future__ import annotations

import ipaddress


def is_loopback_host(host: str) -> bool:
    """Return whether a bind/URL host is loopback-only."""
    normalized = str(host or "").strip().strip("[]").rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def require_long_secret(name: str, value: str, minimum: int = 32) -> None:
    if not isinstance(value, str) or len(value) < minimum:
        raise RuntimeError(f"{name} must be configured with at least {minimum} characters")
    if value.strip().lower() in {"change-me", "secret", "password"}:
        raise RuntimeError(f"{name} must not use a placeholder value")


def validate_dashboard_config(
    *,
    environment: str,
    host: str,
    cookie_secure: bool,
    session_secret: str,
    privacy_acknowledged: bool,
) -> None:
    require_long_secret("WEBWATCH_SESSION_SECRET", session_secret)
    if environment == "production":
        if not cookie_secure:
            raise RuntimeError("WEBWATCH_COOKIE_SECURE must be true in production")
        if not privacy_acknowledged:
            raise RuntimeError(
                "Production requires WEWATCH_PRIVACY_ACKNOWLEDGED=true after "
                "the operator has established notice, consent, and retention policies"
            )
    elif not is_loopback_host(host):
        raise RuntimeError(
            "The built-in development dashboard must bind only to loopback; "
            "use a production WSGI server for network deployment"
        )


def validate_signaling_config(
    *,
    environment: str,
    host: str,
    allow_unsafe_werkzeug: bool,
    require_join_token: bool,
    admin_token: str,
    signing_secret: str,
) -> None:
    if allow_unsafe_werkzeug and not is_loopback_host(host):
        raise RuntimeError(
            "Unsafe Werkzeug is permitted only on a loopback signaling host"
        )
    if environment == "production":
        if allow_unsafe_werkzeug:
            raise RuntimeError("Unsafe Werkzeug must be disabled in production")
        if not require_join_token:
            raise RuntimeError("WEBRTC_REQUIRE_JOIN_TOKEN must be true in production")
        require_long_secret("WEBRTC_ADMIN_TOKEN", admin_token)
        require_long_secret("WEBRTC_SECRET_KEY", signing_secret)
        if admin_token == signing_secret:
            raise RuntimeError(
                "WEBRTC_ADMIN_TOKEN and WEBRTC_SECRET_KEY must be different secrets"
            )