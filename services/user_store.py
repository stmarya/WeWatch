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


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 64 * 1024 * 1024


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


@dataclass(frozen=True)
class PublicUser:
    id: str
    display_name: str
    email: str
    role: str
    created_at: str
    last_login_at: str | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(value: str) -> str:
    return str(value or "").strip().casefold()


def normalize_display_name(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def validate_registration(display_name: str, email: str, password: str) -> dict[str, str]:
    errors: dict[str, str] = {}
    name = normalize_display_name(display_name)
    normalized_email = normalize_email(email)
    if len(name) < 2 or len(name) > 100:
        errors["display_name"] = "Nama harus terdiri dari 2–100 karakter."
    if len(normalized_email) > 254 or not EMAIL_RE.fullmatch(normalized_email):
        errors["email"] = "Masukkan alamat email yang valid."
    if len(password) < 12:
        errors["password"] = "Password minimal 12 karakter."
    elif len(password) > 128:
        errors["password"] = "Password maksimal 128 karakter."
    elif not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors["password"] = "Password harus mengandung huruf dan angka."
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
                    last_login_at TEXT
                )
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE)")

    def create_user(self, display_name: str, email: str, password: str) -> PublicUser:
        errors = validate_registration(display_name, email, password)
        if errors:
            raise ValueError(next(iter(errors.values())))
        user_id = uuid4().hex
        name = normalize_display_name(display_name)
        normalized_email = normalize_email(email)
        password_hash = hash_password(password)
        now = utc_now()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users
                        (id, display_name, email, password_hash, role, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'user', 1, ?, ?)
                    """,
                    (user_id, name, normalized_email, password_hash, now, now),
                )
        except sqlite3.IntegrityError as exc:
            if "email" in str(exc).lower() or "unique" in str(exc).lower():
                raise DuplicateEmailError("Email sudah terdaftar.") from exc
            raise
        return PublicUser(user_id, name, normalized_email, "user", now, None)

    def authenticate(self, email: str, password: str) -> PublicUser | None:
        normalized_email = normalize_email(email)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, display_name, email, password_hash, role, created_at, last_login_at, is_active
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
            row["id"], row["display_name"], row["email"], row["role"], row["created_at"], now
        )

    def get_user(self, user_id: str) -> PublicUser | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, display_name, email, role, created_at, last_login_at
                FROM users WHERE id = ? AND is_active = 1
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return PublicUser(
            row["id"], row["display_name"], row["email"], row["role"],
            row["created_at"], row["last_login_at"],
        )
