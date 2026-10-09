from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


TERMINAL_JOB_STATUSES = {JobStatus.SUCCEEDED, JobStatus.FAILED}


@dataclass(frozen=True)
class JobRecord:
    id: str
    plugin_id: str
    plugin_version: str
    config: dict[str, Any]
    status: JobStatus
    progress: float
    stage: str
    message: str
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "config": self.config,
            "status": self.status.value,
            "progress": self.progress,
            "stage": self.stage,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
