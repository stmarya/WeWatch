"""Persistent user accounts for WeWatch.

The store intentionally exposes a small API and never returns password hashes
from public lookups. SQLite is the default single-node store; set
``WEBWATCH_DATABASE_URL`` to a PostgreSQL URL when running multiple replicas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from services.avatars import avatar_url, default_avatar_for, is_valid_avatar
from services.db import Database, IntegrityError, open_database


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


class InvalidTokenError(ValueError):
    pass


EMAIL_VERIFY_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(hours=1)
TOKEN_PURPOSES = {"verify_email", "change_email", "reset_password"}


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
    email_verified_at: str | None = None

    @property
    def email_verified(self) -> bool:
        return bool(self.email_verified_at)

    @property
    def avatar_url(self) -> str:
        return avatar_url(self.avatar, self.id)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_in(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat(timespec="seconds")


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


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
    _PUBLIC_COLUMNS = (
        "id, display_name, email, role, created_at, last_login_at, avatar, bio, "
        "updated_at, session_epoch, email_verified_at"
    )

    def __init__(self, path_or_url: str | Path | Database):
        self.db = path_or_url if isinstance(path_or_url, Database) else open_database(path_or_url)
        self.path = getattr(self.db, "path", None)
        self.initialize()

    # ------------------------------------------------------------------ schema
    def initialize(self) -> None:
        if self.db.dialect == "postgres":
            self._initialize_postgres()
        else:
            self._initialize_sqlite()

    def _initialize_sqlite(self) -> None:
        with self.db.transaction() as conn:
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
                    session_epoch INTEGER NOT NULL DEFAULT 0,
                    email_verified_at TEXT
                )
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE)")
            # Forward-only migration for databases created by older versions.
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            for column, ddl in (
                ("avatar", "ALTER TABLE users ADD COLUMN avatar TEXT"),
                ("bio", "ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT ''"),
                ("session_epoch", "ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0"),
                ("email_verified_at", "ALTER TABLE users ADD COLUMN email_verified_at TEXT"),
            ):
                if column not in existing:
                    conn.execute(ddl)
                    if column == "email_verified_at":
                        # Accounts created before verification existed are grandfathered.
                        conn.execute("UPDATE users SET email_verified_at = created_at")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    purpose TEXT NOT NULL,
                    new_email TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id, purpose)")

    def _initialize_postgres(self) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT,
                    avatar TEXT,
                    bio TEXT NOT NULL DEFAULT '',
                    session_epoch INTEGER NOT NULL DEFAULT 0,
                    email_verified_at TEXT
                )
                """
            )
            # Emails are normalized to lowercase before every write.
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (lower(email))")
            for ddl in (
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS session_epoch INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TEXT",
            ):
                conn.execute(ddl)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    purpose TEXT NOT NULL,
                    new_email TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id, purpose)")

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _public(row) -> PublicUser:
        return PublicUser(
            row["id"], row["display_name"], row["email"], row["role"],
            row["created_at"], row["last_login_at"], row["avatar"], row["bio"] or "",
            row["updated_at"], int(row["session_epoch"] or 0), row["email_verified_at"],
        )

    def _email_taken(self, conn, email: str, exclude_user_id: str | None = None) -> bool:
        row = conn.execute(
            "SELECT id FROM users WHERE lower(email) = ?", (normalize_email(email),)
        ).fetchone()
        return bool(row) and row["id"] != exclude_user_id

    def _require_current_password(self, conn, user_id: str, password: str) -> None:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ? AND is_active = 1", (user_id,)
        ).fetchone()
        stored = row["password_hash"] if row else DUMMY_PASSWORD_HASH
        if not verify_password(stored, password) or row is None:
            raise InvalidCurrentPasswordError("Password saat ini tidak sesuai.")

    def _issue_token(self, conn, user_id: str, purpose: str, ttl: timedelta, new_email: str | None = None) -> str:
        if purpose not in TOKEN_PURPOSES:
            raise ValueError("Unsupported token purpose")
        # Only the newest link of each purpose stays valid.
        conn.execute(
            "DELETE FROM auth_tokens WHERE user_id = ? AND purpose = ? AND used_at IS NULL",
            (user_id, purpose),
        )
        raw = secrets.token_urlsafe(32)
        conn.execute(
            """
            INSERT INTO auth_tokens (token_hash, user_id, purpose, new_email, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (hash_token(raw), user_id, purpose, new_email, utc_now(), _utc_in(ttl)),
        )
        return raw

    def _consume_token(self, conn, raw: str, purpose: str):
        token_hash = hash_token(raw)
        now = utc_now()
        cursor = conn.execute(
            """
            UPDATE auth_tokens SET used_at = ?
            WHERE token_hash = ? AND purpose = ? AND used_at IS NULL AND expires_at > ?
            """,
            (now, token_hash, purpose, now),
        )
        if cursor.rowcount != 1:
            raise InvalidTokenError("Link tidak valid atau sudah kedaluwarsa.")
        row = conn.execute(
            """
            SELECT t.user_id, t.new_email FROM auth_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token_hash = ? AND u.is_active = 1
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            raise InvalidTokenError("Link tidak valid atau sudah kedaluwarsa.")
        return row

    def token_is_valid(self, raw: str, purpose: str) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM auth_tokens
                WHERE token_hash = ? AND purpose = ? AND used_at IS NULL AND expires_at > ?
                """,
                (hash_token(raw), purpose, utc_now()),
            ).fetchone()
        return row is not None

    # -------------------------------------------------------------- accounts
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
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO users
                        (id, display_name, email, password_hash, role, is_active, created_at, updated_at, avatar)
                    VALUES (?, ?, ?, ?, 'user', 1, ?, ?, ?)
                    """,
                    (user_id, name, normalized_email, password_hash, now, now, avatar),
                )
        except IntegrityError as exc:
            raise DuplicateEmailError("Email sudah terdaftar.") from exc
        return PublicUser(user_id, name, normalized_email, "user", now, None, avatar, "", now, 0, None)

    def authenticate(self, email: str, password: str) -> PublicUser | None:
        normalized_email = normalize_email(email)
        with self.db.transaction() as conn:
            row = conn.execute(
                f"SELECT {self._PUBLIC_COLUMNS}, password_hash, is_active FROM users WHERE lower(email) = ?",
                (normalized_email,),
            ).fetchone()
            if row is None:
                verify_password(DUMMY_PASSWORD_HASH, password)
                return None
            if not row["is_active"] or not verify_password(row["password_hash"], password):
                return None
            now = utc_now()
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, row["id"]))
        user = self._public(row)
        return PublicUser(**{**user.__dict__, "last_login_at": now})

    def get_user(self, user_id: str) -> PublicUser | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                f"SELECT {self._PUBLIC_COLUMNS} FROM users WHERE id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
        return self._public(row) if row else None

    def update_profile(self, user_id: str, display_name: str, bio: str, avatar: str | None) -> PublicUser:
        errors = validate_profile(display_name, bio, avatar)
        if errors:
            raise ValueError(next(iter(errors.values())))
        with self.db.transaction() as conn:
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

    def set_avatar(self, user_id: str, avatar: str) -> PublicUser:
        """Set any stored avatar value (catalog ID or ``upload:<id>``); server-side only."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE users SET avatar = ?, updated_at = ? WHERE id = ? AND is_active = 1",
                (avatar, utc_now(), user_id),
            )
        return self.get_user(user_id)

    # ---------------------------------------------------- email verification
    def issue_email_verification(self, user_id: str) -> str:
        with self.db.transaction() as conn:
            return self._issue_token(conn, user_id, "verify_email", EMAIL_VERIFY_TTL)

    def verify_email(self, raw_token: str) -> PublicUser:
        with self.db.transaction() as conn:
            row = self._consume_token(conn, raw_token, "verify_email")
            now = utc_now()
            conn.execute(
                "UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?), updated_at = ? WHERE id = ?",
                (now, now, row["user_id"]),
            )
            user_id = row["user_id"]
        return self.get_user(user_id)

    def request_email_change(self, user_id: str, current_password: str, new_email: str) -> str:
        error = _email_error(new_email)
        if error:
            raise ValueError(error)
        normalized_email = normalize_email(new_email)
        with self.db.transaction() as conn:
            self._require_current_password(conn, user_id, current_password)
            current = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            if current and normalize_email(current["email"]) == normalized_email:
                raise ValueError("Email baru sama dengan email saat ini.")
            if self._email_taken(conn, normalized_email, user_id):
                raise DuplicateEmailError("Email sudah digunakan akun lain.")
            return self._issue_token(conn, user_id, "change_email", EMAIL_VERIFY_TTL, normalized_email)

    def confirm_email_change(self, raw_token: str) -> tuple[PublicUser, str]:
        """Apply a pending email change. Returns (user, previous_email)."""
        try:
            with self.db.transaction() as conn:
                row = self._consume_token(conn, raw_token, "change_email")
                previous = conn.execute("SELECT email FROM users WHERE id = ?", (row["user_id"],)).fetchone()
                now = utc_now()
                conn.execute(
                    "UPDATE users SET email = ?, email_verified_at = ?, updated_at = ? WHERE id = ?",
                    (row["new_email"], now, now, row["user_id"]),
                )
                user_id = row["user_id"]
        except IntegrityError as exc:
            raise DuplicateEmailError("Email sudah digunakan akun lain.") from exc
        return self.get_user(user_id), previous["email"]

    def pending_email_change(self, user_id: str) -> str | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT new_email FROM auth_tokens
                WHERE user_id = ? AND purpose = 'change_email' AND used_at IS NULL AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, utc_now()),
            ).fetchone()
        return row["new_email"] if row else None

    # -------------------------------------------------------------- passwords
    def change_password(self, user_id: str, current_password: str, new_password: str) -> PublicUser:
        error = password_error(new_password)
        if error:
            raise ValueError(error)
        with self.db.transaction() as conn:
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

    def request_password_reset(self, email: str) -> tuple[PublicUser, str] | None:
        """Return (user, raw_token) for active accounts, otherwise None."""
        with self.db.transaction() as conn:
            row = conn.execute(
                f"SELECT {self._PUBLIC_COLUMNS} FROM users WHERE lower(email) = ? AND is_active = 1",
                (normalize_email(email),),
            ).fetchone()
            if row is None:
                return None
            return self._public(row), self._issue_token(conn, row["id"], "reset_password", PASSWORD_RESET_TTL)

    def reset_password(self, raw_token: str, new_password: str) -> PublicUser:
        error = password_error(new_password)
        if error:
            raise ValueError(error)
        with self.db.transaction() as conn:
            row = self._consume_token(conn, raw_token, "reset_password")
            now = utc_now()
            # Following an emailed link also proves ownership of the address.
            conn.execute(
                """
                UPDATE users
                SET password_hash = ?, session_epoch = session_epoch + 1,
                    email_verified_at = COALESCE(email_verified_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (hash_password(new_password), now, now, row["user_id"]),
            )
            conn.execute(
                "DELETE FROM auth_tokens WHERE user_id = ? AND purpose = 'reset_password' AND used_at IS NULL",
                (row["user_id"],),
            )
            user_id = row["user_id"]
        return self.get_user(user_id)

    # --------------------------------------------------------- privacy / GDPR
    def export_user(self, user_id: str) -> dict:
        user = self.get_user(user_id)
        if user is None:
            raise LookupError("Akun tidak ditemukan.")
        return {
            "id": user.id,
            "display_name": user.display_name,
            "email": user.email,
            "email_verified_at": user.email_verified_at,
            "role": user.role,
            "bio": user.bio,
            "avatar": user.avatar,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_login_at": user.last_login_at,
            "pending_email_change": self.pending_email_change(user_id),
        }

    def delete_user(self, user_id: str, current_password: str) -> PublicUser:
        """Permanently delete the account. Returns the deleted user for cleanup."""
        user = self.get_user(user_id)
        with self.db.transaction() as conn:
            self._require_current_password(conn, user_id, current_password)
            conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return user
