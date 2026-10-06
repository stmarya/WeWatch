"""Tiny database adapter so account storage runs on SQLite or PostgreSQL.

SQLite remains the zero-config default for single-node/local use. Set
``WEBWATCH_DATABASE_URL=postgresql://user:pass@host:5432/db`` to share
accounts between multiple app replicas. Queries are written with ``?``
placeholders and translated for psycopg.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any, Iterator


class IntegrityError(Exception):
    """Backend-neutral unique/foreign-key violation."""


class Database:
    dialect = "sqlite"

    @contextmanager
    def transaction(self) -> Iterator["Connection"]:  # pragma: no cover - interface
        raise NotImplementedError
        yield


class Connection:
    def __init__(self, raw: Any, dialect: str):
        self.raw = raw
        self.dialect = dialect

    def execute(self, sql: str, params: tuple | list = ()):
        if self.dialect == "postgres":
            sql = sql.replace("?", "%s")
            try:
                return self.raw.execute(sql, params)
            except Exception as exc:  # psycopg.errors.IntegrityError subclasses
                if _is_pg_integrity_error(exc):
                    raise IntegrityError(str(exc)) from exc
                raise
        try:
            return self.raw.execute(sql, params)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc


def _is_pg_integrity_error(exc: Exception) -> bool:
    try:
        import psycopg
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, psycopg.IntegrityError)


class SQLiteDatabase(Database):
    dialect = "sqlite"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield Connection(conn, self.dialect)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


class PostgresDatabase(Database):
    dialect = "postgres"

    def __init__(self, url: str, pool_size: int = 10):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on deployment
            raise RuntimeError(
                "PostgreSQL requires the 'psycopg[binary]' package (see requirements.txt)."
            ) from exc
        self._psycopg = psycopg
        self._row_factory = dict_row
        self.url = url
        self._pool = None
        try:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(
                url, min_size=1, max_size=pool_size, kwargs={"row_factory": dict_row}, open=True
            )
        except ImportError:
            self._pool = None

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        if self._pool is not None:
            with self._pool.connection() as conn:
                with conn.transaction():
                    yield Connection(conn, self.dialect)
            return
        with self._psycopg.connect(self.url, row_factory=self._row_factory) as conn:
            with conn.transaction():
                yield Connection(conn, self.dialect)


def open_database(url_or_path: str | Path) -> Database:
    value = str(url_or_path)
    if value.startswith(("postgres://", "postgresql://")):
        return PostgresDatabase(value)
    if value.startswith("sqlite:///"):
        value = value[len("sqlite:///"):]
    return SQLiteDatabase(value)
