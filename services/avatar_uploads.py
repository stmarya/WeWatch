"""Validate, sanitize, and store user-uploaded profile photos.

Uploads are fully decoded and re-encoded with Pillow: this strips EXIF/GPS and
any other metadata, neutralizes polyglot files, and normalizes every photo to a
256x256 WebP. Files are stored outside ``static/`` under random names.
"""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import secrets

from services.avatars import UPLOAD_ID_RE, UPLOAD_PREFIX, upload_id

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SOURCE_PIXELS = 4096 * 4096
OUTPUT_SIZE = 256
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class AvatarUploadError(ValueError):
    pass


def upload_dir() -> Path:
    configured = os.getenv("WEBWATCH_UPLOAD_DIR", "").strip()
    base = Path(configured) if configured else Path(__file__).resolve().parent.parent / "uploads"
    path = base / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def process_avatar_upload(data: bytes) -> bytes:
    """Return sanitized WebP bytes or raise AvatarUploadError."""
    if not data:
        raise AvatarUploadError("Pilih file foto terlebih dahulu.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AvatarUploadError("Ukuran foto maksimal 2 MB.")
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - deployment issue
        raise AvatarUploadError("Upload foto belum tersedia di server ini.") from exc

    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    try:
        with Image.open(BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise AvatarUploadError("Format foto harus JPG, PNG, atau WebP.")
            probe.verify()
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > MAX_SOURCE_PIXELS:
                raise AvatarUploadError("Resolusi foto terlalu besar (maks. 4096×4096).")
            image.seek(0)  # first frame only for animated WebP/PNG
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            image = ImageOps.fit(image, (OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="WEBP", quality=85, method=4)
            return output.getvalue()
    except AvatarUploadError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError) as exc:
        raise AvatarUploadError("File bukan gambar yang valid.") from exc


def save_avatar_upload(data: bytes) -> str:
    """Process and persist an upload. Returns the stored avatar value."""
    clean = process_avatar_upload(data)
    new_id = secrets.token_hex(16)
    target = upload_dir() / f"{new_id}.webp"
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(clean)
    os.replace(tmp, target)
    return f"{UPLOAD_PREFIX}{new_id}"


def delete_avatar_upload(avatar_value: str | None) -> None:
    uploaded = upload_id(avatar_value)
    if not uploaded:
        return
    try:
        (upload_dir() / f"{uploaded}.webp").unlink(missing_ok=True)
    except OSError:
        pass


def uploaded_file_path(filename: str) -> Path | None:
    stem, _, ext = filename.partition(".")
    if ext != "webp" or not UPLOAD_ID_RE.fullmatch(stem):
        return None
    path = upload_dir() / f"{stem}.webp"
    return path if path.is_file() else None
