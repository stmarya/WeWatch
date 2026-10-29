"""Privacy-preserving retention helpers for locally stored WeWatch data."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable


RETENTION_ENV_VARS = (
    "WEBWATCH_RETENTION_GALLERY_DAYS",
    "WEBWATCH_RETENTION_FACE_DAYS",
    "WEBWATCH_RETENTION_MOOD_DAYS",
    "WEBWATCH_RETENTION_ATTENDANCE_DAYS",
)


def retention_days(name: str) -> int:
    raw = os.getenv(name, "0").strip()
    try:
        days = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a non-negative integer") from exc
    if days < 0 or days > 3650:
        raise RuntimeError(f"{name} must be between 0 and 3650 days")
    return days


def validate_production_privacy(
    *,
    environment: str,
    privacy_acknowledged: bool,
    retention: dict[str, int],
) -> None:
    if environment != "production":
        return
    if not privacy_acknowledged:
        raise RuntimeError(
            "Production requires WEWATCH_PRIVACY_ACKNOWLEDGED=true after "
            "notice and subject-consent procedures are in place"
        )
    missing = [name for name in RETENTION_ENV_VARS if retention.get(name, 0) <= 0]
    if missing:
        raise RuntimeError(
            "Production requires an explicit positive retention period for: "
            + ", ".join(missing)
        )


def purge_old_files(
    directory: str | Path,
    suffixes: set[str],
    days: int,
    *,
    now: float | None = None,
) -> int:
    """Delete matching files older than the configured retention period."""
    if days <= 0:
        return 0
    folder = Path(directory)
    if not folder.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - (days * 86400)
    removed = 0
    for path in folder.iterdir():
        try:
            if path.is_file() and path.suffix.lower() in suffixes and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            logging.exception("Could not remove expired privacy data: %s", path.name)
    return removed


def purge_old_file(path: str | Path, days: int, *, now: float | None = None) -> bool:
    """Delete one file if it is older than an explicitly configured period."""
    if days <= 0:
        return False
    candidate = Path(path)
    try:
        cutoff = (time.time() if now is None else now) - (days * 86400)
        if candidate.is_file() and candidate.stat().st_mtime < cutoff:
            candidate.unlink()
            return True
    except OSError:
        logging.exception("Could not remove expired privacy data: %s", candidate.name)
    return False


def start_retention_worker(cleanup: Callable[[], None], interval_seconds: int = 3600) -> None:
    """Run a best-effort cleanup cycle periodically in a daemon thread."""
    def loop() -> None:
        while True:
            time.sleep(max(60, interval_seconds))
            try:
                cleanup()
            except Exception:
                logging.exception("Privacy retention cleanup failed")

    threading.Thread(target=loop, name="wewatch-retention", daemon=True).start()