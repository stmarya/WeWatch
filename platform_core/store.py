"""Versioned SQLite pilot store with explicit tenant predicates and transactions."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

SCHEMA_VERSION = 1
SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
 password_hash TEXT NOT NULL, email_verified_at INTEGER, disabled_at INTEGER,
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id),
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships(
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('owner','admin','host','member','viewer')),
 created_at INTEGER NOT NULL, PRIMARY KEY(workspace_id,user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_owner_per_workspace ON memberships(workspace_id) WHERE role='owner';
CREATE INDEX IF NOT EXISTS memberships_by_user ON memberships(user_id,workspace_id);
CREATE TABLE IF NOT EXISTS account_sessions(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL UNIQUE,
 created_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
 revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS sessions_by_user ON account_sessions(user_id);
CREATE TABLE IF NOT EXISTS account_tokens(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')),
 token_hash TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL, used_at INTEGER,
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS invitations(
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 email TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','host','member','viewer')),
 invited_by TEXT NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL UNIQUE,
 created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER, accepted_at INTEGER
);
CREATE INDEX IF NOT EXISTS invitations_by_workspace ON invitations(workspace_id);
CREATE TABLE IF NOT EXISTS audit_events(
 id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id),
 actor_id TEXT REFERENCES users(id), event TEXT NOT NULL, resource_id TEXT,
 metadata TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_by_workspace ON audit_events(workspace_id,created_at);
'''


class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().absolute()
        if self.path.is_symlink():
            raise ValueError('Database path must not be a symlink')
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # The pilot database directory may contain authentication secrets.
        if os.name != 'nt' and self.path.parent.stat().st_mode & 0o077:
            raise ValueError('Platform database directory must be private (mode 0700)')
        self.migrate()
        if os.name != 'nt':
            self.path.chmod(0o600)

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=10000')
        return connection

    def migrate(self):
        connection = self.connect()
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)')
            versions = [row[0] for row in connection.execute('SELECT version FROM schema_migrations')]
            if any(version > SCHEMA_VERSION for version in versions):
                raise RuntimeError('Database schema is newer than this application')
            # Idempotent under parallel process startup. Future migrations must
            # be appended, not destructive replacement of existing tables.
            connection.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nINSERT OR IGNORE INTO schema_migrations VALUES (1, strftime(\'%s\',\'now\'));\nCOMMIT;')
        finally:
            connection.close()


@contextmanager
def transaction(connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def new_id():
    return uuid.uuid4().hex


def audit(connection, actor_id, event, workspace_id=None, resource_id=None, **metadata):
    # Only callers' explicit allowlisted metadata is recorded: never raw form
    # bodies, password hashes, invitation/reset tokens, audio or biometrics.
    connection.execute('INSERT INTO audit_events VALUES (?,?,?,?,?,?,?)',
                       (new_id(), workspace_id, actor_id, event, resource_id,
                        json.dumps(metadata, separators=(',', ':')), int(time.time())))
