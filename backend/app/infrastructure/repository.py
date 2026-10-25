from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from backend.app.domain.jobs import JobRecord, JobStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def scene_names_from_job_configs(configs: list[str]) -> set[str]:
    """Scene ids named by queued or running jobs. Other config fields are ignored."""

    names: set[str] = set()
    for raw in configs:
        try:
            config = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(config, dict):
            continue
        for key in ("scene_name", "scene_id"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
    return names


def _failure_stage(stage: object) -> str:
    if isinstance(stage, str) and stage not in {"", "queued", "running"}:
        return stage
    return "failed"


def successful_job_fields(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    terminal = data.get("terminal_stage")
    custom = isinstance(terminal, str) and bool(terminal)
    return {"status":JobStatus.SUCCEEDED.value, "progress":1.0,
            "stage":terminal if custom else "completed",
            "message":str(data.get("message") or "Job completed") if custom else "Job completed",
            "result_json":json.dumps(result, sort_keys=True)}


class JobRepository(Protocol):
    def create_job(
        self,
        job_id: str,
        plugin_id: str,
        plugin_version: str,
        config: dict[str, Any],
    ) -> JobRecord: ...

    def get_job(self, job_id: str) -> JobRecord | None: ...

    def update_progress(
        self, job_id: str, progress: float, stage: str, message: str
    ) -> bool: ...

    def cancel_job(self, job_id: str) -> None: ...

    def start_job(self, job_id: str) -> bool: ...

    def finish_cancel(self, job_id: str) -> bool: ...

    def list_active_jobs(self) -> list[JobRecord]: ...

    def active_scene_names(self) -> set[str]: ...

    def succeed_job(self, job_id: str, result: dict[str, Any]) -> bool: ...

    def fail_job(self, job_id: str, error: dict[str, Any]) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    plugin_id TEXT NOT NULL,
    plugin_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    result_json TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class SQLiteJobRepository:
    """Small local adapter used by tests and the no-dependency dev server."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._connection.execute(_SCHEMA)

    def _row(self, job_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()

    @staticmethod
    def _record(row: sqlite3.Row | None) -> JobRecord | None:
        if row is None:
            return None
        return JobRecord(
            id=row["id"],
            plugin_id=row["plugin_id"],
            plugin_version=row["plugin_version"],
            config=json.loads(row["config_json"]),
            status=JobStatus(row["status"]),
            progress=float(row["progress"]),
            stage=row["stage"],
            message=row["message"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=json.loads(row["error_json"]) if row["error_json"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_job(self, job_id: str, plugin_id: str, plugin_version: str, config: dict[str, Any]) -> JobRecord:
        now = utc_now()
        with self._lock:
            self._connection.execute(
                """INSERT INTO jobs
                (id, plugin_id, plugin_version, config_json, status, progress,
                 stage, message, result_json, error_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
                (
                    job_id,
                    plugin_id,
                    plugin_version,
                    json.dumps(config, sort_keys=True),
                    JobStatus.QUEUED.value,
                    0.0,
                    "queued",
                    "Job queued",
                    now,
                    now,
                ),
            )
            return self._record(self._row(job_id))  # type: ignore[return-value]

    def list_active_jobs(self) -> list[JobRecord]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM jobs WHERE status IN (?, ?, ?)",
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.CANCELLING.value)).fetchall()
        return [self._record(row) for row in rows]

    def active_scene_names(self) -> set[str]:
        return scene_names_from_job_configs([json.dumps(record.config) for record in self.list_active_jobs()])

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._record(self._row(job_id))

    def _update(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [job_id]
        with self._lock:
            self._connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?", values
            )

    def update_progress(self, job_id: str, progress: float, stage: str, message: str) -> bool:
        return self._transition(job_id, (JobStatus.RUNNING,), progress=max(0.0, min(1.0, progress)), stage=stage, message=message)

    def _transition(self, job_id: str, expected: tuple[JobStatus, ...], **fields: Any) -> bool:
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        statuses = ", ".join("?" for _ in expected)
        sql = f"UPDATE jobs SET {assignments} WHERE id = ? AND status IN ({statuses})"
        values = [*fields.values(), job_id, *(status.value for status in expected)]
        with self._lock:
            return self._connection.execute(sql, values).rowcount == 1
    def start_job(self, job_id: str) -> bool:
        return self._transition(job_id, (JobStatus.QUEUED,), status=JobStatus.RUNNING.value,
                                progress=0.0, stage="running", message="Job started")

    def cancel_job(self, job_id: str) -> None:
        if not self._transition(job_id, (JobStatus.QUEUED,), status=JobStatus.CANCELLED.value,
                                stage="cancelled", message="构建已终止"):
            self._transition(job_id, (JobStatus.RUNNING,), status=JobStatus.CANCELLING.value,
                             stage="cancelling", message="正在取消，等待当前步骤退出")

    def finish_cancel(self, job_id: str) -> bool:
        return self._transition(job_id, (JobStatus.CANCELLING,), status=JobStatus.CANCELLED.value,
                                stage="cancelled", message="构建已终止")

    def succeed_job(self, job_id: str, result: dict[str, Any]) -> bool:
        return self._transition(job_id, (JobStatus.RUNNING,), **successful_job_fields(result))

    def fail_job(self, job_id: str, error: dict[str, Any]) -> None:
        self._transition(job_id, (JobStatus.QUEUED, JobStatus.RUNNING), status=JobStatus.FAILED.value,
                         stage=_failure_stage(error.get("stage")), message=error.get("message", "Job failed"),
                         error_json=json.dumps(error, sort_keys=True))


def create_job_repository(database_url: str) -> JobRepository:
    """Create a repository without hiding unavailable production dependencies."""
    if database_url.startswith("sqlite:///"):
        return SQLiteJobRepository(database_url.removeprefix("sqlite:///"))
    if database_url == "sqlite://:memory:":
        return SQLiteJobRepository(":memory:")
    if database_url.startswith("postgresql"):
        try:
            from .postgres_repository import PostgresJobRepository
        except ImportError as exc:  # pragma: no cover - exercised in deployment only
            raise RuntimeError(
                "PostgreSQL requires psycopg; install backend/requirements.txt"
            ) from exc
        return PostgresJobRepository(database_url)
    raise ValueError(f"unsupported DATABASE_URL: {database_url!r}")
