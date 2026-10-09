from __future__ import annotations

import traceback
import uuid
from typing import Any

from backend.app.domain.jobs import JobRecord
from backend.app.domain.plugins import PluginError, PluginRegistry, PluginResult
from backend.app.infrastructure.queue import TaskQueue
from backend.app.infrastructure.repository import JobRepository


class JobService:
    def __init__(self, repository: JobRepository, queue: TaskQueue, registry: PluginRegistry) -> None:
        self.repository = repository
        self.queue = queue
        self.registry = registry

    def list_plugins(self) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self.registry.list_specs()]

    def create_job(self, plugin_id: str, config: dict[str, Any]) -> JobRecord:
        plugin = self.registry.get(plugin_id)
        plugin.validate_config(config)
        job_id = str(uuid.uuid4())
        record = self.repository.create_job(job_id, plugin.id, plugin.version, config)
        self.queue.enqueue(job_id)
        return record

    def get_job(self, job_id: str) -> JobRecord | None:
        return self.repository.get_job(job_id)

    def execute_job(self, job_id: str) -> JobRecord:
        record = self.repository.get_job(job_id)
        if record is None:
            raise PluginError(f"unknown job: {job_id}")
        plugin = self.registry.get(record.plugin_id)
        self.repository.start_job(job_id)

        def report(progress: float, stage: str, message: str) -> None:
            self.repository.update_progress(job_id, progress, stage, message)

        try:
            result: PluginResult = plugin.run(record.config, report)
            self.repository.succeed_job(job_id, result.to_dict())
        except Exception as exc:  # task boundary: preserve failure for the UI
            self.repository.fail_job(
                job_id,
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=10),
                },
            )
        final = self.repository.get_job(job_id)
        if final is None:  # pragma: no cover - protects a broken repository adapter
            raise RuntimeError(f"job disappeared after execution: {job_id}")
        return final
