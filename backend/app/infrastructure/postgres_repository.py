from __future__ import annotations

import json
from typing import Any

from backend.app.domain.jobs import JobRecord, JobStatus
from backend.app.infrastructure.repository import JobRepository, utc_now


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
        return self._psycopg.connect(self.url)

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (_SCHEMA_ADVISORY_LOCK,))
            connection.execute(_SCHEMA)
            connection.execute("SELECT pg_advisory_unlock(%s)", (_SCHEMA_ADVISORY_LOCK,))

    @staticmethod
    def _record(row: tuple[Any, ...] | None) -> JobRecord | None:
        if row is None:
            return None
        return JobRecord(
            id=row[0], plugin_id=row[1], plugin_version=row[2], config=json.loads(row[3]),
            status=JobStatus(row[4]), progress=float(row[5]), stage=row[6], message=row[7],
            result=json.loads(row[8]) if row[8] else None,
            error=json.loads(row[9]) if row[9] else None, created_at=row[10], updated_at=row[11],
        )

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        return self._record(row)

    def create_job(self, job_id: str, plugin_id: str, plugin_version: str, config: dict[str, Any]) -> JobRecord:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs (id, plugin_id, plugin_version, config_json, status, progress, stage, message, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (job_id, plugin_id, plugin_version, json.dumps(config, sort_keys=True), JobStatus.QUEUED.value, 0.0, "queued", "Job queued", now, now),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def _update(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = %s" for key in fields)
        with self._connect() as connection:
            connection.execute(f"UPDATE jobs SET {assignments} WHERE id = %s", (*fields.values(), job_id))

    def update_progress(self, job_id: str, progress: float, stage: str, message: str) -> None:
        self._update(job_id, progress=max(0.0, min(1.0, progress)), stage=stage, message=message)

    def start_job(self, job_id: str) -> None:
        self._update(job_id, status=JobStatus.RUNNING.value, progress=0.0, stage="running", message="Job started")

    def cancel_job(self, job_id: str) -> None:
        self._update(job_id, status=JobStatus.CANCELLED.value, stage="cancelled", message="构建已终止")

    def succeed_job(self, job_id: str, result: dict[str, Any]) -> None:
        self._update(job_id, status=JobStatus.SUCCEEDED.value, progress=1.0, stage="completed", message="Job completed", result_json=json.dumps(result, sort_keys=True))

    def fail_job(self, job_id: str, error: dict[str, Any]) -> None:
        from backend.app.infrastructure.repository import _failure_stage

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = %s, stage = %s, message = %s, error_json = %s, updated_at = %s
                WHERE id = %s AND status NOT IN (%s, %s, %s)
                """,
                (
                    JobStatus.FAILED.value,
                    _failure_stage(error.get("stage")),
                    error.get("message", "Job failed"),
                    json.dumps(error, sort_keys=True),
                    utc_now(),
                    job_id,
                    JobStatus.SUCCEEDED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                ),
            )
