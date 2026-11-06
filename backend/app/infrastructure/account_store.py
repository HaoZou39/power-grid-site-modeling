"""Users and sessions in the same database as jobs."""

from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

logger = logging.getLogger(__name__)

SESSION_HOURS = 12
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCK_SECONDS = 60
_hasher = PasswordHasher()  # Argon2id
_DUMMY_HASH = _hasher.hash("unused-timing-pad")


@dataclass(frozen=True)
class UserRecord:
    id: str
    username: str
    password_hash: str
    role: str
    disabled_at: str | None
    created_at: str


@dataclass(frozen=True)
class SessionRecord:
    token_hash: str
    user_id: str
    csrf_token: str
    expires_at: str
    created_at: str


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("密码至少 8 位")
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


class AccountStore:
    def __init__(self, database_url: str, repository: Any) -> None:
        self.database_url = database_url
        if database_url.startswith("postgresql"):
            self.dialect = "postgres"
            self._connection = None
            self._lock = threading.RLock()
            self._repository = repository
        else:
            self.dialect = "sqlite"
            self._connection = repository._connection
            self._lock = repository._lock
            self._repository = repository
        self.migrate()

    def migrate(self) -> None:
        """Repeatable. Adds missing tables and columns without rewriting existing rows."""
        if self.dialect == "sqlite":
            self._migrate_sqlite()
        else:
            self._migrate_postgres()

    def _migrate_sqlite(self) -> None:
        with self._lock:
            connection = self._connection
            connection.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    disabled_at TEXT,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    csrf_token TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS login_attempts (
                    username TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    locked_until TEXT
                )"""
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "owner_id" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN owner_id TEXT")

    def _migrate_postgres(self) -> None:
        import psycopg

        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    disabled_at TEXT,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    csrf_token TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS login_attempts (
                    username TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    locked_until TEXT
                )"""
            )
            connection.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS owner_id TEXT")

    def _execute(self, sql: str, params: tuple = ()) -> None:
        if self.dialect == "sqlite":
            with self._lock:
                self._connection.execute(sql, params)
            return
        import psycopg

        with psycopg.connect(self.database_url) as connection:
            connection.execute(sql.replace("?", "%s"), params)

    def _query(self, sql: str, params: tuple = ()) -> list[Any]:
        if self.dialect == "sqlite":
            with self._lock:
                return list(self._connection.execute(sql, params).fetchall())
        import psycopg

        with psycopg.connect(self.database_url) as connection:
            return list(connection.execute(sql.replace("?", "%s"), params).fetchall())

    def count_users(self) -> int:
        return int(self._query("SELECT COUNT(*) FROM users")[0][0])

    def create_user(self, username: str, password: str, role: str) -> UserRecord:
        if role not in {"admin", "user"}:
            raise ValueError("角色只能是 admin 或 user")
        user_id = secrets.token_hex(16)
        created = _iso(_now())
        try:
            self._execute(
                "INSERT INTO users (id, username, password_hash, role, disabled_at, created_at) VALUES (?, ?, ?, ?, NULL, ?)",
                (user_id, username, hash_password(password), role, created),
            )
        except (sqlite3.IntegrityError, Exception) as exc:
            if "unique" in str(exc).lower() or isinstance(exc, sqlite3.IntegrityError):
                raise ValueError("用户名已存在") from exc
            raise
        found = self.get_user(user_id)
        if found is None:
            raise RuntimeError("created user could not be read back")
        return found

    def get_user(self, user_id: str) -> UserRecord | None:
        rows = self._query(
            "SELECT id, username, password_hash, role, disabled_at, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        return _user(rows[0]) if rows else None

    def get_user_by_username(self, username: str) -> UserRecord | None:
        rows = self._query(
            "SELECT id, username, password_hash, role, disabled_at, created_at FROM users WHERE username = ?",
            (username,),
        )
        return _user(rows[0]) if rows else None

    def list_users(self) -> list[UserRecord]:
        rows = self._query(
            "SELECT id, username, password_hash, role, disabled_at, created_at FROM users ORDER BY created_at, username"
        )
        return [_user(row) for row in rows]

    def set_disabled(self, user_id: str, disabled: bool) -> UserRecord | None:
        moment = _iso(_now()) if disabled else None
        self._execute("UPDATE users SET disabled_at = ? WHERE id = ?", (moment, user_id))
        if disabled:
            self.delete_sessions_for_user(user_id)
        return self.get_user(user_id)

    def set_password(self, user_id: str, password: str) -> None:
        self._execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
        self.delete_sessions_for_user(user_id)

    def active_admin_count(self) -> int:
        return int(self._query("SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled_at IS NULL")[0][0])

    def assign_unowned_jobs(self, owner_id: str) -> int:
        rows = self._query("SELECT COUNT(*) FROM jobs WHERE owner_id IS NULL")
        count = int(rows[0][0])
        if count:
            self._execute("UPDATE jobs SET owner_id = ? WHERE owner_id IS NULL", (owner_id,))
        return count

    def login_locked(self, username: str) -> bool:
        rows = self._query("SELECT locked_until FROM login_attempts WHERE username = ?", (username,))
        if not rows or rows[0][0] is None:
            return False
        return datetime.fromisoformat(rows[0][0]) > _now()

    def record_login_failure(self, username: str) -> None:
        rows = self._query("SELECT failures FROM login_attempts WHERE username = ?", (username,))
        failures = (int(rows[0][0]) if rows else 0) + 1
        locked = _iso(_now() + timedelta(seconds=LOGIN_LOCK_SECONDS)) if failures >= LOGIN_FAILURE_LIMIT else None
        if rows:
            self._execute(
                "UPDATE login_attempts SET failures = ?, locked_until = ? WHERE username = ?",
                (failures, locked, username),
            )
        else:
            self._execute(
                "INSERT INTO login_attempts (username, failures, locked_until) VALUES (?, ?, ?)",
                (username, failures, locked),
            )

    def clear_login_failures(self, username: str) -> None:
        self._execute("DELETE FROM login_attempts WHERE username = ?", (username,))

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        """Wrong password and unknown user both return None. Disabled users return None."""
        if self.login_locked(username):
            raise PermissionError("locked")
        user = self.get_user_by_username(username)
        if user is None:
            verify_password(_DUMMY_HASH, password)
            self.record_login_failure(username)
            return None
        if not verify_password(user.password_hash, password) or user.disabled_at is not None:
            self.record_login_failure(username)
            return None
        self.clear_login_failures(username)
        return user

    def create_session(self, user_id: str) -> tuple[str, str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        created = _now()
        self._execute(
            "INSERT INTO sessions (token_hash, user_id, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (hash_token(token), user_id, csrf, _iso(created + timedelta(hours=SESSION_HOURS)), _iso(created)),
        )
        return token, csrf, _iso(created + timedelta(hours=SESSION_HOURS))

    def session_user(self, token: str) -> tuple[UserRecord, str] | None:
        if not token:
            return None
        rows = self._query(
            """SELECT u.id, u.username, u.password_hash, u.role, u.disabled_at, u.created_at, s.csrf_token, s.expires_at
               FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?""",
            (hash_token(token),),
        )
        if not rows:
            return None
        row = rows[0]
        if datetime.fromisoformat(row[7]) <= _now() or row[4] is not None:
            self._execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
            return None
        return _user(row[:6]), row[6]

    def delete_session(self, token: str) -> None:
        self._execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))

    def delete_sessions_for_user(self, user_id: str) -> None:
        self._execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def _user(row: Any) -> UserRecord:
    return UserRecord(
        id=row[0], username=row[1], password_hash=row[2], role=row[3], disabled_at=row[4], created_at=row[5],
    )


def ensure_bootstrap_admin(store: AccountStore) -> None:
    """Create the first admin only when the table is empty and credentials were supplied."""
    import os

    if store.count_users() > 0:
        return
    username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not username or not password:
        logger.error("users table is empty and BOOTSTRAP_ADMIN_USERNAME/PASSWORD were not set")
        return
    store.create_user(username, password, "admin")
    logger.info("created the initial admin account %s", username)
