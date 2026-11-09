"""Personal planning workspace metadata and its current plan. Rows do not copy scene rasters."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.app.domain.planning_content import (
    PLAN_BYTE_LIMIT,
    PlanNotWritable,
    PlanRevisionConflict,
    PlanTooLarge,
    canonical_plan,
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


def _record(row: object) -> PlanningWorkspace:
    values = tuple(row[name] if hasattr(row, "keys") else row[index] for index, name in enumerate(_FIELDS))
    return PlanningWorkspace(*values)


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
        if self.dialect == "sqlite":
            with self._lock:
                for statement in statements:
                    self._connection.execute(statement)
                present = {row[1] for row in self._connection.execute("PRAGMA table_info(planning_workspaces)")}
                for column, statement in zip(("content_schema_version", "content_json"), alters, strict=True):
                    if column not in present:
                        self._connection.execute(statement)
            return
        import psycopg

        with psycopg.connect(self.database_url) as connection:
            for statement in statements:
                connection.execute(statement)
            for statement in alters:
                connection.execute(statement.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS", 1))

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
        self._execute(
            f"""INSERT INTO planning_workspaces ({", ".join(_FIELDS)})
                VALUES ({", ".join("?" for _ in _FIELDS)})""",
            tuple(getattr(record, name) for name in _FIELDS),
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
        current = self._query(
            """SELECT workspace_revision, content_json FROM planning_workspaces
               WHERE workspace_id = ? AND owner_id = ? AND deleted_at IS NULL""",
            (workspace_id, owner_id),
        )
        if not current:
            raise PlanNotWritable()
        revision, raw = current[0][0], current[0][1]
        if revision != expected_revision:
            raise PlanRevisionConflict()
        document = parse_stored_plan(raw)
        replacement = document.model_dump(mode="json")
        replacement[side] = value
        encoded = canonical_plan(replacement)
        if len(encoded.encode()) > PLAN_BYTE_LIMIT:
            raise PlanTooLarge()
        previous = canonical_plan(document.model_dump(mode="json"))
        if encoded == previous:
            rows = self._query(
                f"""UPDATE planning_workspaces SET content_schema_version = content_schema_version
                    WHERE workspace_id = ? AND owner_id = ? AND deleted_at IS NULL AND workspace_revision = ?
                    RETURNING {", ".join(_FIELDS)}""",
                (workspace_id, owner_id, expected_revision),
            )
        else:
            rows = self._query(
                f"""UPDATE planning_workspaces
                    SET content_json = ?, content_schema_version = 1, workspace_revision = ?, updated_at = ?
                    WHERE workspace_id = ? AND owner_id = ? AND deleted_at IS NULL AND workspace_revision = ?
                    RETURNING {", ".join(_FIELDS)}""",
                (encoded, str(uuid.uuid4()), _now(), workspace_id, owner_id, expected_revision),
            )
        if not rows:
            self._lost_plan_update(workspace_id, owner_id)
        return _record(rows[0]), encoded != previous

    def count_active_for_scene(self, base_scene_id: str) -> int:
        rows = self._query(
            "SELECT COUNT(*) FROM planning_workspaces WHERE base_scene_id = ? AND deleted_at IS NULL",
            (base_scene_id,),
        )
        return int(rows[0][0])

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
