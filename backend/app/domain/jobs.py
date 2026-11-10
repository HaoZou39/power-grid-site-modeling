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
class JobBinding:
    """Server-derived identity of one workspace job. Clients cannot supply these fields."""

    workspace_id: str
    workspace_revision: str
    base_scene_id: str
    base_frame_id: str
    base_revision: str
    base_snapshot_id: str
    planning_content_hash: str
    effective_config_hash: str
    resolved_config_json: str
    snapshot_manifest_sha256: str


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
    owner_id: str | None = None
    workspace_id: str | None = None
    workspace_revision: str | None = None
    base_scene_id: str | None = None
    base_frame_id: str | None = None
    base_revision: str | None = None
    base_snapshot_id: str | None = None
    planning_content_hash: str | None = None
    effective_config_hash: str | None = None
    resolved_config_json: str | None = None
    snapshot_manifest_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        # resolved_config_json stays in the database. The public record keeps the hashes, not a second copy.
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
            "workspace_id": self.workspace_id,
            "workspace_revision": self.workspace_revision,
            "base_scene_id": self.base_scene_id,
            "base_frame_id": self.base_frame_id,
            "base_revision": self.base_revision,
            "base_snapshot_id": self.base_snapshot_id,
            "planning_content_hash": self.planning_content_hash,
            "effective_config_hash": self.effective_config_hash,
            "snapshot_manifest_sha256": self.snapshot_manifest_sha256,
        }
