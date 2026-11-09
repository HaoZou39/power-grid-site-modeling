"""Personal planning workspace metadata, its current plan, and immutable plan revisions."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from backend.app.domain.planning_content import (
    PLAN_BYTE_LIMIT,
    PlanContentHashMismatch,
    PlanNotWritable,
    PlanRevisionConflict,
    PlanTooLarge,
    assert_snapshot,
    canonical_plan,
    canonical_snapshot,
    parse_stored_plan,
)

NAME_LIMIT = 80
EMPTY_PLAN = '{"routing":null,"schema_version":1,"site":null}'

_FIELDS = (
    "workspace_id",
    "owner_id",
    "base_scene_id",
    "base_frame_id",
    "base_revision",
    "workspace_revision",
    "display_name",
    "created_at",
    "updated_at",
    "deleted_at",
    "content_schema_version",
    "content_json",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS planning_workspaces (
    workspace_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    base_scene_id TEXT NOT NULL,
    base_frame_id TEXT NOT NULL,
    base_revision TEXT NOT NULL,
    workspace_revision TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    content_schema_version INTEGER NOT NULL DEFAULT 1,
    content_json TEXT NOT NULL DEFAULT '{"routing":null,"schema_version":1,"site":null}'
)
"""


_REVISION_FIELDS = (
    "workspace_id",
    "revision_id",
    "owner_id",
    "base_scene_id",
    "base_frame_id",
    "base_revision",
    "schema_version",
    "content_json",
    "content_sha256",
    "created_at",
)

_REVISIONS = """
CREATE TABLE IF NOT EXISTS planning_workspace_revisions (
    workspace_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    base_scene_id TEXT NOT NULL,
    base_frame_id TEXT NOT NULL,
    base_revision TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    content_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, revision_id)
)
"""

_REVISION_INDEX = """
CREATE INDEX IF NOT EXISTS planning_workspace_revisions_created_idx
ON planning_workspace_revisions (workspace_id, created_at, revision_id)
"""

# Reject writes from the application role. A database superuser can still bypass this.
_SQLITE_PROTECTION = (
    """
    CREATE TRIGGER IF NOT EXISTS planning_workspace_revisions_no_update
    BEFORE UPDATE ON planning_workspace_revisions
    BEGIN
        SELECT RAISE(ABORT, 'planning_workspace_revisions are immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS planning_workspace_revisions_no_delete
    BEFORE DELETE ON planning_workspace_revisions
    BEGIN
        SELECT RAISE(ABORT, 'planning_workspace_revisions are immutable');
    END
    """,
)

_POSTGRES_PROTECTION = (
    """
    CREATE OR REPLACE FUNCTION planning_workspace_revisions_immutable()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION 'planning_workspace_revisions are immutable';
    END;
    $$
    """,
    """
    CREATE OR REPLACE TRIGGER planning_workspace_revisions_no_update
    BEFORE UPDATE ON planning_workspace_revisions
    FOR EACH ROW
    EXECUTE FUNCTION planning_workspace_revisions_immutable()
    """,
    """
    CREATE OR REPLACE TRIGGER planning_workspace_revisions_no_delete
    BEFORE DELETE ON planning_workspace_revisions
    FOR EACH ROW
    EXECUTE FUNCTION planning_workspace_revisions_immutable()
    """,
)


class RevisionConsistencyError(Exception):
    """An existing revision row does not match the workspace snapshot being recorded."""


@dataclass(frozen=True)
class WorkspaceRevision:
    workspace_id: str
    revision_id: str
    owner_id: str
    base_scene_id: str
    base_frame_id: str
    base_revision: str
    schema_version: int
    content_json: str
    content_sha256: str
    created_at: str


@dataclass(frozen=True)
class PlanningWorkspace:
    workspace_id: str
    owner_id: str
    base_scene_id: str
    base_frame_id: str
    base_revision: str
    workspace_revision: str
    display_name: str
    created_at: str
    updated_at: str
    deleted_at: str | None
    content_schema_version: int
    content_json: str


def clean_display_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("工作区名称不能为空")
    if len(cleaned) > NAME_LIMIT:
        raise ValueError(f"工作区名称不能超过 {NAME_LIMIT} 个字")
    return cleaned


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _values(row: object, names: tuple[str, ...]) -> tuple:
    return tuple(row[name] if hasattr(row, "keys") else row[index] for index, name in enumerate(names))


def _record(row: object) -> PlanningWorkspace:
    return PlanningWorkspace(*_values(row, _FIELDS))


def _revision(row: object) -> WorkspaceRevision:
    return WorkspaceRevision(*_values(row, _REVISION_FIELDS))


def _checked_revision(record: WorkspaceRevision) -> None:
    document = assert_snapshot(record.content_json, record.content_sha256)
    if document.schema_version != record.schema_version:
        raise PlanContentHashMismatch()


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
    def savepoint(self) -> Iterator[None]:
        self.execute("SAVEPOINT revision_write")
        try:
            yield
        except Exception:
            self.execute("ROLLBACK TO SAVEPOINT revision_write")
            self.execute("RELEASE SAVEPOINT revision_write")
            raise
        else:
            self.execute("RELEASE SAVEPOINT revision_write")


class WorkspaceRepository:
    """SQLite and PostgreSQL share one statement shape. `?` is translated for Postgres."""

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
        """One write transaction. Callers that already hold the scene lock must not take it again here."""
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

        with self._lock, psycopg.connect(self.database_url) as connection, connection.transaction():
            yield _Conn(connection, "postgres")

    def migrate(self) -> None:
        statements = (
            _SCHEMA,
            "CREATE INDEX IF NOT EXISTS planning_workspaces_owner_idx ON planning_workspaces (owner_id)",
            "CREATE INDEX IF NOT EXISTS planning_workspaces_scene_idx ON planning_workspaces (base_scene_id)",
        )
        alters = (
            "ALTER TABLE planning_workspaces ADD COLUMN content_schema_version INTEGER NOT NULL DEFAULT 1",
            f"ALTER TABLE planning_workspaces ADD COLUMN content_json TEXT NOT NULL DEFAULT '{EMPTY_PLAN}'",
        )
        with self._immediate() as db:
            if self.dialect == "postgres":
                db.query("SELECT pg_advisory_xact_lock(8421701)")
            for statement in statements:
                db.execute(statement)
            if self.dialect == "sqlite":
                present = {row[1] for row in db.execute("PRAGMA table_info(planning_workspaces)").fetchall()}
                for column, statement in zip(("content_schema_version", "content_json"), alters, strict=True):
                    if column not in present:
                        db.execute(statement)
            else:
                for statement in alters:
                    db.execute(statement.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS", 1))
            db.execute(_REVISIONS)
            db.execute(_REVISION_INDEX)
            self._backfill_revisions(db)
            for statement in _SQLITE_PROTECTION if self.dialect == "sqlite" else _POSTGRES_PROTECTION:
                db.execute(statement)

    def insert(
        self,
        *,
        owner_id: str,
        base_scene_id: str,
        base_frame_id: str,
        base_revision: str,
        display_name: str,
    ) -> PlanningWorkspace:
        if not owner_id or not base_scene_id or not base_frame_id or not base_revision:
            raise ValueError("工作区缺少所属用户或基础场景版本")
        now = _now()
        record = PlanningWorkspace(
            workspace_id=str(uuid.uuid4()),
            owner_id=owner_id,
            base_scene_id=base_scene_id,
            base_frame_id=base_frame_id,
            base_revision=base_revision,
            workspace_revision=str(uuid.uuid4()),
            display_name=clean_display_name(display_name),
            created_at=now,
            updated_at=now,
            deleted_at=None,
            content_schema_version=1,
            content_json=EMPTY_PLAN,
        )
        with self._immediate() as db:
            self._insert_workspace(db, record)
            _document, canonical, digest = canonical_snapshot(record.content_json)
            self._insert_or_verify(
                db, self._revision_row(record, record.workspace_revision, _document.schema_version, canonical, digest, now),
            )
        return record

    def get(self, workspace_id: str) -> PlanningWorkspace | None:
        rows = self._query(
            f"SELECT {', '.join(_FIELDS)} FROM planning_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        )
        return _record(rows[0]) if rows else None

    def list_active(self, owner_id: str, base_scene_id: str | None = None) -> list[PlanningWorkspace]:
        sql = f"""SELECT {", ".join(_FIELDS)} FROM planning_workspaces
                  WHERE owner_id = ? AND deleted_at IS NULL"""
        params: list[str] = [owner_id]
        if base_scene_id is not None:
            sql += " AND base_scene_id = ?"
            params.append(base_scene_id)
        sql += " ORDER BY created_at, workspace_id"
        return [_record(row) for row in self._query(sql, tuple(params))]

    def rename(self, workspace_id: str, owner_id: str, display_name: str) -> PlanningWorkspace | None:
        """Update the name only when this owner still holds the live row."""
        rows = self._query(
            f"""UPDATE planning_workspaces SET display_name = ?, updated_at = ?
                WHERE workspace_id = ? AND owner_id = ? AND deleted_at IS NULL
                RETURNING {", ".join(_FIELDS)}""",
            (clean_display_name(display_name), _now(), workspace_id, owner_id),
        )
        return _record(rows[0]) if rows else None

    def soft_delete(self, workspace_id: str, owner_id: str) -> PlanningWorkspace | None:
        rows = self._query(
            f"""UPDATE planning_workspaces SET deleted_at = ?, updated_at = ?
                WHERE workspace_id = ? AND owner_id = ? AND deleted_at IS NULL
                RETURNING {", ".join(_FIELDS)}""",
            (_now(), _now(), workspace_id, owner_id),
        )
        return _record(rows[0]) if rows else None

    def save_plan_side(
        self,
        workspace_id: str,
        owner_id: str,
        expected_revision: str,
        side: str,
        value: dict | None,
    ) -> tuple[PlanningWorkspace, bool]:
        """Replace one side only when the expected revision still matches. Same content keeps the revision."""
        if side not in {"site", "routing"}:
            raise ValueError("未知规划内容")
        try:
            with self._immediate() as db:
                return self._save_plan_side(db, workspace_id, owner_id, expected_revision, side, value)
        except PlanRevisionConflict:
            self._lost_plan_update(workspace_id, owner_id)

    def count_active_for_scene(self, base_scene_id: str) -> int:
        rows = self._query(
            "SELECT COUNT(*) FROM planning_workspaces WHERE base_scene_id = ? AND deleted_at IS NULL",
            (base_scene_id,),
        )
        return int(rows[0][0])

    def get_revision(self, workspace_id: str, revision_id: str) -> WorkspaceRevision | None:
        """Read one revision even after the workspace is soft-deleted. A bad hash is refused."""
        rows = self._query(
            f"""SELECT {", ".join(_REVISION_FIELDS)} FROM planning_workspace_revisions
                WHERE workspace_id = ? AND revision_id = ?""",
            (workspace_id, revision_id),
        )
        if not rows:
            return None
        record = _revision(rows[0])
        _checked_revision(record)
        return record

    def list_revisions(self, workspace_id: str) -> list[WorkspaceRevision]:
        rows = self._query(
            f"""SELECT {", ".join(_REVISION_FIELDS)} FROM planning_workspace_revisions
                WHERE workspace_id = ? ORDER BY created_at, revision_id""",
            (workspace_id,),
        )
        records = [_revision(row) for row in rows]
        for record in records:
            _checked_revision(record)
        return records

    def _backfill_revisions(self, db: _Conn) -> None:
        """Record the current row once. Earlier revisions were never stored, so they are not invented."""
        for row in db.query(f"SELECT {', '.join(_FIELDS)} FROM planning_workspaces"):
            current = _record(row)
            _document, canonical, digest = canonical_snapshot(current.content_json)
            self._insert_or_verify(
                db,
                self._revision_row(current, current.workspace_revision, _document.schema_version, canonical, digest, _now()),
            )

    def _save_plan_side(self, db: _Conn, workspace_id: str, owner_id: str, expected_revision: str, side: str, value: dict | None):
        locking = " FOR UPDATE" if self.dialect == "postgres" else ""
        rows = db.query(
            f"""SELECT {", ".join(_FIELDS)} FROM planning_workspaces
                WHERE workspace_id = ? AND owner_id = ? AND deleted_at IS NULL{locking}""",
            (workspace_id, owner_id),
        )
        if not rows:
            raise PlanNotWritable()
        current = _record(rows[0])
        if current.workspace_revision != expected_revision:
            raise PlanRevisionConflict()
        document = parse_stored_plan(current.content_json)
        replacement = document.model_dump(mode="json")
        replacement[side] = value
        encoded = canonical_plan(replacement)
        if len(encoded.encode()) > PLAN_BYTE_LIMIT:
            raise PlanTooLarge()
        changed = encoded != canonical_plan(document.model_dump(mode="json"))
        if changed:
            revision_id = str(uuid.uuid4())
            now = _now()
            _document, canonical, digest = canonical_snapshot(encoded)
            self._insert_or_verify(
                db, self._revision_row(current, revision_id, _document.schema_version, canonical, digest, now),
            )
            updated = db.query(
                f"""UPDATE planning_workspaces
                    SET content_json = ?, content_schema_version = ?, workspace_revision = ?, updated_at = ?
                    WHERE workspace_id = ? AND owner_id = ? AND deleted_at IS NULL AND workspace_revision = ?
                    RETURNING {", ".join(_FIELDS)}""",
                (canonical, _document.schema_version, revision_id, now, workspace_id, owner_id, expected_revision),
            )
        else:
            updated = db.query(
                f"""UPDATE planning_workspaces SET content_schema_version = content_schema_version
                    WHERE workspace_id = ? AND owner_id = ? AND deleted_at IS NULL AND workspace_revision = ?
                    RETURNING {", ".join(_FIELDS)}""",
                (workspace_id, owner_id, expected_revision),
            )
        if not updated:
            raise PlanRevisionConflict()
        return _record(updated[0]), changed

    def _revision_row(
        self,
        current: PlanningWorkspace,
        revision_id: str,
        schema_version: int,
        canonical: str,
        digest: str,
        created_at: str,
    ) -> WorkspaceRevision:
        return WorkspaceRevision(
            workspace_id=current.workspace_id,
            revision_id=revision_id,
            owner_id=current.owner_id,
            base_scene_id=current.base_scene_id,
            base_frame_id=current.base_frame_id,
            base_revision=current.base_revision,
            schema_version=schema_version,
            content_json=canonical,
            content_sha256=digest,
            created_at=created_at,
        )

    def _insert_workspace(self, db: _Conn, record: PlanningWorkspace) -> None:
        db.execute(
            f"""INSERT INTO planning_workspaces ({", ".join(_FIELDS)})
                VALUES ({", ".join("?" for _ in _FIELDS)})""",
            tuple(getattr(record, name) for name in _FIELDS),
        )

    def _insert_or_verify(self, db: _Conn, revision: WorkspaceRevision) -> None:
        existing = self._find_revision(db, revision.workspace_id, revision.revision_id)
        if existing is not None:
            self._require_same(existing, revision)
            return
        try:
            with db.savepoint():
                db.execute(
                    f"""INSERT INTO planning_workspace_revisions ({", ".join(_REVISION_FIELDS)})
                        VALUES ({", ".join("?" for _ in _REVISION_FIELDS)})""",
                    tuple(getattr(revision, name) for name in _REVISION_FIELDS),
                )
        except Exception as exc:
            if not _is_unique_violation(exc):
                raise
            existing = self._find_revision(db, revision.workspace_id, revision.revision_id)
            if existing is None:
                raise
            self._require_same(existing, revision)

    def _find_revision(self, db: _Conn, workspace_id: str, revision_id: str) -> WorkspaceRevision | None:
        rows = db.query(
            f"""SELECT {", ".join(_REVISION_FIELDS)} FROM planning_workspace_revisions
                WHERE workspace_id = ? AND revision_id = ?""",
            (workspace_id, revision_id),
        )
        return _revision(rows[0]) if rows else None

    def _require_same(self, existing: WorkspaceRevision, expected: WorkspaceRevision) -> None:
        compared = (
            "owner_id", "base_scene_id", "base_frame_id", "base_revision",
            "schema_version", "content_json", "content_sha256",
        )
        if any(getattr(existing, name) != getattr(expected, name) for name in compared):
            raise RevisionConsistencyError(f"revision {expected.workspace_id}/{expected.revision_id} conflicts with the stored snapshot")
        try:
            document = assert_snapshot(existing.content_json, existing.content_sha256)
        except PlanContentHashMismatch as exc:
            raise RevisionConsistencyError(
                f"revision {expected.workspace_id}/{expected.revision_id} failed its content check"
            ) from exc
        if document.schema_version != existing.schema_version:
            raise RevisionConsistencyError(f"revision {expected.workspace_id}/{expected.revision_id} failed its content check")

    def _lost_plan_update(self, workspace_id: str, owner_id: str) -> None:
        row = self.get(workspace_id)
        if row is None or row.owner_id != owner_id or row.deleted_at is not None:
            raise PlanNotWritable()
        raise PlanRevisionConflict()

    def _execute(self, sql: str, params: tuple) -> None:
        if self.dialect == "sqlite":
            with self._lock:
                self._connection.execute(sql, params)
            return
        import psycopg

        with self._lock, psycopg.connect(self.database_url) as connection:
            connection.execute(sql.replace("?", "%s"), params)

    def _query(self, sql: str, params: tuple = ()) -> list:
        if self.dialect == "sqlite":
            with self._lock:
                return list(self._connection.execute(sql, params).fetchall())
        import psycopg

        with self._lock, psycopg.connect(self.database_url) as connection:
            return list(connection.execute(sql.replace("?", "%s"), params).fetchall())
