"""Catalog of verified base-scene snapshots. Rows do not own or delete the files."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator


class SnapshotCatalogConflict(RuntimeError):
    """The same snapshot id is already registered with different identity fields."""


_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS base_scene_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    base_scene_id TEXT NOT NULL,
    base_frame_id TEXT NOT NULL,
    base_revision TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""
_REFERENCES = """
CREATE TABLE IF NOT EXISTS base_snapshot_references (
    snapshot_id TEXT NOT NULL,
    reference_kind TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, reference_kind, reference_id)
)
"""


def _is_unique_violation(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        text = str(exc).lower()
        return "unique" in text or "primary key" in text
    return exc.__class__.__name__ == "UniqueViolation"


class _Conn:
    def __init__(self, raw: object, dialect: str) -> None:
        self.raw = raw
        self.dialect = dialect

    def execute(self, sql: str, params: tuple = ()):
        statement = sql if self.dialect == "sqlite" else sql.replace("?", "%s")
        return self.raw.execute(statement, params)

    def query(self, sql: str, params: tuple = ()) -> list:
        return list(self.execute(sql, params).fetchall())

    @contextmanager
    def savepoint(self, name: str) -> Iterator[None]:
        self.execute(f"SAVEPOINT {name}")
        try:
            yield
        except Exception:
            self.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.execute(f"RELEASE SAVEPOINT {name}")
            raise
        else:
            self.execute(f"RELEASE SAVEPOINT {name}")


class BaseSnapshotRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        if database_url == "sqlite://:memory:" or database_url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            path = ":memory:" if database_url == "sqlite://:memory:" else database_url.removeprefix("sqlite:///")
            self._lock = threading.RLock()
            self._connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
            self._connection.row_factory = sqlite3.Row
        elif database_url.startswith("postgresql"):
            self.dialect = "postgres"
            self._lock = threading.RLock()
            self._connection = None
        else:
            raise ValueError(f"unsupported DATABASE_URL: {database_url!r}")
        self.migrate()

    @contextmanager
    def _immediate(self) -> Iterator[_Conn]:
        if self.dialect == "sqlite":
            with self._lock:
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    yield _Conn(self._connection, "sqlite")
                    self._connection.execute("COMMIT")
                except Exception:
                    try:
                        self._connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
            return
        import psycopg

        from psycopg.rows import dict_row

        with self._lock, psycopg.connect(self.database_url, row_factory=dict_row) as connection, connection.transaction():
            yield _Conn(connection, "postgres")

    def migrate(self) -> None:
        with self._immediate() as conn:
            if self.dialect == "postgres":
                conn.execute("SELECT pg_advisory_xact_lock(8421702)")
            conn.execute(_SNAPSHOTS)
            conn.execute(_REFERENCES)

    def register_snapshot(self, manifest: dict, manifest_sha256: str) -> bool:
        """Insert one ready catalog row. An identical row is a no-op. Files are not touched."""

        row = (
            manifest["snapshot_id"],
            manifest["base_scene_id"],
            manifest["base_frame_id"],
            manifest["base_revision"],
            manifest_sha256,
            int(manifest["total_bytes"]),
            "ready",
        )
        with self._immediate() as conn:
            existing = conn.query("SELECT * FROM base_scene_snapshots WHERE snapshot_id = ?", (row[0],))
            if existing:
                self._require_same(existing[0], row)
                return False
            try:
                with conn.savepoint("snapshot_register"):
                    conn.execute(
                        """
                        INSERT INTO base_scene_snapshots (
                            snapshot_id, base_scene_id, base_frame_id, base_revision,
                            manifest_sha256, size_bytes, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (*row, datetime.now(timezone.utc).isoformat()),
                    )
            except Exception as exc:
                if not _is_unique_violation(exc):
                    raise
                existing = conn.query("SELECT * FROM base_scene_snapshots WHERE snapshot_id = ?", (row[0],))
                self._require_same(existing[0], row)
                return False
            return True

    def add_reference(self, snapshot_id: str, reference_kind: str, reference_id: str) -> bool:
        if not snapshot_id or not reference_kind or not reference_id:
            raise ValueError("snapshot reference requires snapshot_id, kind and id")
        with self._immediate() as conn:
            found = conn.query(
                "SELECT snapshot_id FROM base_scene_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            )
            if not found:
                raise KeyError(snapshot_id)
            try:
                with conn.savepoint("snapshot_reference"):
                    conn.execute(
                        """
                        INSERT INTO base_snapshot_references (snapshot_id, reference_kind, reference_id, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (snapshot_id, reference_kind, reference_id, datetime.now(timezone.utc).isoformat()),
                    )
            except Exception as exc:
                if not _is_unique_violation(exc):
                    raise
                return False
            return True

    def reference_counts(self) -> dict[str, int]:
        with self._immediate() as conn:
            rows = conn.query(
                """
                SELECT snapshot_id, COUNT(*) AS reference_count FROM base_snapshot_references
                GROUP BY snapshot_id
                """
            )
        return {row["snapshot_id"]: int(row["reference_count"]) for row in rows}

    @staticmethod
    def _require_same(existing, row: tuple) -> None:
        current = (
            existing["snapshot_id"],
            existing["base_scene_id"],
            existing["base_frame_id"],
            existing["base_revision"],
            existing["manifest_sha256"],
            int(existing["size_bytes"]),
            existing["status"],
        )
        if current != row:
            raise SnapshotCatalogConflict("base_scene_snapshots row does not match the verified manifest")
