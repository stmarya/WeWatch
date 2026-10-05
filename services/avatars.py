"""Self-hosted avatar catalog for WeWatch user profiles.

The SVG files in ``static/avatars`` were generated once with DiceBear using
CC0 1.0 styles only, so they can be used commercially without attribution and
without depending on a third-party API at runtime. Avatar IDs are validated
against this fixed catalog; user input is never used as a filesystem path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re


AVATAR_DIR = Path(__file__).resolve().parent.parent / "static" / "avatars"
AVATAR_ID_RE = re.compile(r"^[a-z0-9-]{1,48}$")
UPLOAD_PREFIX = "upload:"
UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$")

# (style id, display label). Every style listed here must be CC0 on DiceBear.
AVATAR_STYLES: tuple[tuple[str, str], ...] = (
    ("notionists", "Notionists"),
    ("lorelei", "Lorelei"),
    ("pixel-art", "Pixel Art"),
    ("thumbs", "Thumbs"),
)


@dataclass(frozen=True)
class Avatar:
    id: str
    style: str
    label: str
    url: str


def _load_catalog() -> tuple[Avatar, ...]:
    avatars: list[Avatar] = []
    for style, style_label in AVATAR_STYLES:
        for path in sorted(AVATAR_DIR.glob(f"{style}-*.svg")):
            avatar_id = path.stem
            suffix = avatar_id[len(style) + 1:]
            if not AVATAR_ID_RE.fullmatch(avatar_id) or not suffix.isdigit():
                continue
            avatars.append(
                Avatar(
                    id=avatar_id,
                    style=style,
                    label=f"{style_label} {int(suffix)}",
                    url=f"/static/avatars/{avatar_id}.svg",
                )
            )
    return tuple(avatars)


AVATARS: tuple[Avatar, ...] = _load_catalog()
_BY_ID = {avatar.id: avatar for avatar in AVATARS}


def is_valid_avatar(avatar_id: str | None) -> bool:
    return bool(avatar_id) and avatar_id in _BY_ID


def default_avatar_for(seed: str) -> str | None:
    """Pick a stable catalog avatar for users who have not chosen one."""
    if not AVATARS:
        return None
    digest = hashlib.sha256(str(seed or "").encode("utf-8")).digest()
    return AVATARS[int.from_bytes(digest[:4], "big") % len(AVATARS)].id


def upload_id(avatar_value: str | None) -> str | None:
    """Return the uploaded-photo ID for ``upload:<id>`` values, else None."""
    if avatar_value and avatar_value.startswith(UPLOAD_PREFIX):
        candidate = avatar_value[len(UPLOAD_PREFIX):]
        if UPLOAD_ID_RE.fullmatch(candidate):
            return candidate
    return None


def avatar_url(avatar_id: str | None, seed: str = "") -> str:
    uploaded = upload_id(avatar_id)
    if uploaded:
        return f"/media/avatars/{uploaded}.webp"
    chosen = avatar_id if is_valid_avatar(avatar_id) else default_avatar_for(seed)
    return _BY_ID[chosen].url if chosen else ""


def grouped_avatars() -> list[tuple[str, str, list[Avatar]]]:
    return [
        (style, label, [avatar for avatar in AVATARS if avatar.style == style])
        for style, label in AVATAR_STYLES
        if any(avatar.style == style for avatar in AVATARS)
    ]
