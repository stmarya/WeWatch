"""Persistent local user accounts for WeWatch.

The store intentionally exposes a small API and never returns password hashes
from public lookups. SQLite is the default single-node store; deployments that
run multiple app replicas should replace it with a shared transactional store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from pathlib import Path
from uuid import uuid4

from services.avatars import avatar_url, default_avatar_for, is_valid_avatar


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 64 * 1024 * 1024
BIO_MAX_LENGTH = 280


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=SCRYPT_DKLEN, maxmem=SCRYPT_MAXMEM,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(stored: str, password: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = stored.split("$", 5)
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64decode(salt), n=int(n), r=int(r), p=int(p),
            dklen=SCRYPT_DKLEN, maxmem=SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(actual, _b64decode(expected))
    except (ValueError, TypeError):
        return False


# A constant dummy hash keeps unknown-email authentication on the password-hash
# path and reduces account-enumeration timing differences.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


class DuplicateEmailError(ValueError):
    pass


class InvalidCurrentPasswordError(ValueError):
    pass


@dataclass(frozen=True)
class PublicUser:
    id: str
    display_name: str
    email: str
    role: str
    created_at: str
    last_login_at: str | None
    avatar: str | None = None
    bio: str = ""
    updated_at: str | None = None
    session_epoch: int = 0

    @property
    def avatar_url(self) -> str:
        return avatar_url(self.avatar, self.id)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(value: str) -> str:
    return str(value or "").strip().casefold()


def normalize_display_name(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_bio(value: str) -> str:
    # Keep intentional line breaks but trim trailing whitespace on each line.
    lines = [line.rstrip() for line in str(value or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def _display_name_error(display_name: str) -> str | None:
    name = normalize_display_name(display_name)
    if len(name) < 2 or len(name) > 100:
        return "Nama harus terdiri dari 2–100 karakter."
    return None


def _email_error(email: str) -> str | None:
    normalized_email = normalize_email(email)
    if len(normalized_email) > 254 or not EMAIL_RE.fullmatch(normalized_email):
        return "Masukkan alamat email yang valid."
    return None


def password_error(password: str) -> str | None:
    if len(password) < 12:
        return "Password minimal 12 karakter."
    if len(password) > 128:
        return "Password maksimal 128 karakter."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password harus mengandung huruf dan angka."
    return None


def validate_registration(display_name: str, email: str, password: str) -> dict[str, str]:
    errors: dict[str, str] = {}
    for field, error in (
        ("display_name", _display_name_error(display_name)),
        ("email", _email_error(email)),
        ("password", password_error(password)),
    ):
        if error:
            errors[field] = error
    return errors


def validate_profile(display_name: str, bio: str, avatar: str | None) -> dict[str, str]:
    errors: dict[str, str] = {}
    name_error = _display_name_error(display_name)
    if name_error:
        errors["display_name"] = name_error
    if len(normalize_bio(bio)) > BIO_MAX_LENGTH:
        errors["bio"] = f"Bio maksimal {BIO_MAX_LENGTH} karakter."
    if avatar and not is_valid_avatar(avatar):
        errors["avatar"] = "Pilih avatar dari daftar yang tersedia."
    return errors


class UserStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT,
                    avatar TEXT,
                    bio TEXT NOT NULL DEFAULT '',
                    session_epoch INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE)")
            # Lightweight forward-only migration for databases created before
            # profile fields existed.
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
            for column, ddl in (
                ("avatar", "ALTER TABLE users ADD COLUMN avatar TEXT"),
                ("bio", "ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT ''"),
                ("session_epoch", "ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in existing:
                    conn.execute(ddl)

    _PUBLIC_COLUMNS = (
        "id, display_name, email, role, created_at, last_login_at, avatar, bio, updated_at, session_epoch"
    )

    @staticmethod
    def _public(row: sqlite3.Row) -> PublicUser:
        return PublicUser(
            row["id"], row["display_name"], row["email"], row["role"],
            row["created_at"], row["last_login_at"], row["avatar"], row["bio"] or "",
            row["updated_at"], int(row["session_epoch"] or 0),
        )

    def create_user(
        self, display_name: str, email: str, password: str, avatar: str | None = None
    ) -> PublicUser:
        errors = validate_registration(display_name, email, password)
        if avatar and not is_valid_avatar(avatar):
            errors["avatar"] = "Pilih avatar dari daftar yang tersedia."
        if errors:
            raise ValueError(next(iter(errors.values())))
        user_id = uuid4().hex
        avatar = avatar or default_avatar_for(user_id)
        name = normalize_display_name(display_name)
        normalized_email = normalize_email(email)
        password_hash = hash_password(password)
        now = utc_now()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users
                        (id, display_name, email, password_hash, role, is_active, created_at, updated_at, avatar)
                    VALUES (?, ?, ?, ?, 'user', 1, ?, ?, ?)
                    """,
                    (user_id, name, normalized_email, password_hash, now, now, avatar),
                )
        except sqlite3.IntegrityError as exc:
            if "email" in str(exc).lower() or "unique" in str(exc).lower():
                raise DuplicateEmailError("Email sudah terdaftar.") from exc
            raise
        return PublicUser(user_id, name, normalized_email, "user", now, None, avatar, "", now, 0)

    def authenticate(self, email: str, password: str) -> PublicUser | None:
        normalized_email = normalize_email(email)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, display_name, email, password_hash, role, created_at, last_login_at,
                       is_active, avatar, bio, updated_at, session_epoch
                FROM users WHERE email = ? COLLATE NOCASE
                """,
                (normalized_email,),
            ).fetchone()
            if row is None:
                verify_password(DUMMY_PASSWORD_HASH, password)
                return None
            if not row["is_active"] or not verify_password(row["password_hash"], password):
                return None
            now = utc_now()
            conn.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row["id"]),
            )
        return PublicUser(
            row["id"], row["display_name"], row["email"], row["role"], row["created_at"], now,
            row["avatar"], row["bio"] or "", now, int(row["session_epoch"] or 0),
        )

    def get_user(self, user_id: str) -> PublicUser | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._PUBLIC_COLUMNS} FROM users WHERE id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
        return self._public(row) if row else None

    def _require_current_password(self, conn: sqlite3.Connection, user_id: str, password: str) -> None:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ? AND is_active = 1", (user_id,)
        ).fetchone()
        stored = row["password_hash"] if row else DUMMY_PASSWORD_HASH
        if not verify_password(stored, password) or row is None:
            raise InvalidCurrentPasswordError("Password saat ini tidak sesuai.")

    def update_profile(self, user_id: str, display_name: str, bio: str, avatar: str | None) -> PublicUser:
        errors = validate_profile(display_name, bio, avatar)
        if errors:
            raise ValueError(next(iter(errors.values())))
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET display_name = ?, bio = ?, avatar = COALESCE(?, avatar), updated_at = ?
                WHERE id = ? AND is_active = 1
                """,
                (normalize_display_name(display_name), normalize_bio(bio), avatar or None, utc_now(), user_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("Akun tidak ditemukan.")
        return self.get_user(user_id)

    def change_email(self, user_id: str, current_password: str, new_email: str) -> PublicUser:
        error = _email_error(new_email)
        if error:
            raise ValueError(error)
        normalized_email = normalize_email(new_email)
        try:
            with self._connect() as conn:
                self._require_current_password(conn, user_id, current_password)
                conn.execute(
                    "UPDATE users SET email = ?, updated_at = ? WHERE id = ? AND is_active = 1",
                    (normalized_email, utc_now(), user_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEmailError("Email sudah digunakan akun lain.") from exc
        return self.get_user(user_id)

    def change_password(self, user_id: str, current_password: str, new_password: str) -> PublicUser:
        error = password_error(new_password)
        if error:
            raise ValueError(error)
        with self._connect() as conn:
            self._require_current_password(conn, user_id, current_password)
            # Bumping the epoch invalidates every other session for this user.
            conn.execute(
                """
                UPDATE users
                SET password_hash = ?, session_epoch = session_epoch + 1, updated_at = ?
                WHERE id = ? AND is_active = 1
                """,
                (hash_password(new_password), utc_now(), user_id),
            )
        return self.get_user(user_id)
