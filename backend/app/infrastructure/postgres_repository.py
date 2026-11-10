from __future__ import annotations

import json
from typing import Any

from backend.app.domain.jobs import JobBinding, JobRecord, JobStatus
from backend.app.infrastructure.repository import (
    BINDING_COLUMNS,
    JobRepository,
    binding_values,
    scene_names_from_job_configs,
    utc_now,
    _failure_stage,
    successful_job_fields,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    plugin_id TEXT NOT NULL,
    plugin_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    progress DOUBLE PRECISION NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    result_json TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_SCHEMA_ADVISORY_LOCK = 918273645


class PostgresJobRepository(JobRepository):
    def __init__(self, url: str) -> None:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for PostgreSQL") from exc
        self._psycopg = psycopg
        self.url = url
        self._init_schema()

    def _connect(self):
        from psycopg.rows import dict_row

        return self._psycopg.connect(self.url, row_factory=dict_row)

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (_SCHEMA_ADVISORY_LOCK,))
            connection.execute(_SCHEMA)
            connection.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS owner_id TEXT")
            for name in BINDING_COLUMNS:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {name} TEXT")
            connection.execute("SELECT pg_advisory_unlock(%s)", (_SCHEMA_ADVISORY_LOCK,))

    @staticmethod
    def _record(row: dict[str, Any] | None) -> JobRecord | None:
        if row is None:
            return None
        return JobRecord(
            id=row["id"], plugin_id=row["plugin_id"], plugin_version=row["plugin_version"],
            config=json.loads(row["config_json"]), status=JobStatus(row["status"]),
            progress=float(row["progress"]), stage=row["stage"], message=row["message"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=json.loads(row["error_json"]) if row["error_json"] else None,
            created_at=row["created_at"], updated_at=row["updated_at"], owner_id=row.get("owner_id"),
            **{name: row.get(name) for name in BINDING_COLUMNS},
        )

    def list_active_jobs(self) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs WHERE status IN (%s, %s, %s)",
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.CANCELLING.value)).fetchall()
        return [self._record(row) for row in rows]

    def active_scene_names(self) -> set[str]:
        return scene_names_from_job_configs([json.dumps(record.config) for record in self.list_active_jobs()])

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        return self._record(row)

    def create_job(
        self,
        job_id: str,
        plugin_id: str,
        plugin_version: str,
        config: dict[str, Any],
        owner_id: str | None = None,
        *,
        binding: JobBinding | None = None,
    ) -> JobRecord:
        now = utc_now()
        stored = {key: value for key, value in config.items() if key != "owner_id"}
        columns = ", ".join(BINDING_COLUMNS)
        placeholders = ", ".join("%s" for _ in BINDING_COLUMNS)
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO jobs (id, plugin_id, plugin_version, config_json, status, progress, stage, message, created_at, updated_at, owner_id, {columns}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {placeholders})",
                (job_id, plugin_id, plugin_version, json.dumps(stored, sort_keys=True), JobStatus.QUEUED.value, 0.0, "queued", "Job queued", now, now, owner_id, *binding_values(binding)),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def _update(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = %s" for key in fields)
        with self._connect() as connection:
            connection.execute(f"UPDATE jobs SET {assignments} WHERE id = %s", (*fields.values(), job_id))

    def update_progress(self, job_id: str, progress: float, stage: str, message: str) -> bool:
        return self._transition(job_id, (JobStatus.RUNNING,), progress=max(0.0, min(1.0, progress)), stage=stage, message=message)

    def _transition(self, job_id: str, expected: tuple[JobStatus, ...], **fields: Any) -> bool:
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = %s" for key in fields)
        statuses = ", ".join("%s" for _ in expected)
        sql = f"UPDATE jobs SET {assignments} WHERE id = %s AND status IN ({statuses})"
        values = [*fields.values(), job_id, *(status.value for status in expected)]
        with self._connect() as connection:
            cursor = connection.execute(sql, values)
            return cursor.rowcount == 1
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
