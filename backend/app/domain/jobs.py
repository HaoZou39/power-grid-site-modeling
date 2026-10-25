from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


class JobCancelled(Exception):
    """The caller asked this job to stop before the next step."""


TERMINAL_JOB_STATUSES = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


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
            "error": {key: value for key, value in self.error.items() if key != "traceback"} if self.error else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
