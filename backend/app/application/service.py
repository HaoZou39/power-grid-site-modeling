"""Task use cases: validate, enqueue, execute, and read plugin jobs."""

from __future__ import annotations

import traceback
import uuid
import logging
from typing import Any

from backend.app.domain.jobs import JobCancelled, JobRecord, JobStatus
from backend.app.domain.plugins import PluginError, PluginRegistry, PluginResult
from backend.app.infrastructure.queue import TaskQueue
from backend.app.infrastructure.repository import JobRepository


logger = logging.getLogger("site-modeling-job-service")


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

    def cancel_job(self, job_id: str) -> JobRecord:
        record = self.repository.get_job(job_id)
        if record is None:
            raise PluginError(f"unknown job: {job_id}")
        if record.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return record
        self.repository.cancel_job(job_id)
        cancelled = self.repository.get_job(job_id)
        if cancelled is None:
            raise PluginError(f"unknown job: {job_id}")
        return cancelled

    def execute_job(self, job_id: str) -> JobRecord:
        record = self.repository.get_job(job_id)
        if record is None:
            raise PluginError(f"unknown job: {job_id}")
        if record.status == JobStatus.CANCELLED:
            return record
        try:
            plugin = self.registry.get(record.plugin_id)
            self.repository.start_job(job_id)

            def report(progress: float, stage: str, message: str) -> None:
                current = self.repository.get_job(job_id)
                if current is not None and current.status == JobStatus.CANCELLED:
                    raise JobCancelled("构建已终止")
                self.repository.update_progress(job_id, progress, stage, message)

            result: PluginResult = plugin.run(record.config, report)
            if result.status != JobStatus.SUCCEEDED.value:
                raise PluginError(
                    f"plugin returned non-success status: {result.status!r}"
                )
            finished = self.repository.get_job(job_id)
            if finished is not None and finished.status == JobStatus.CANCELLED:
                return finished
            payload = result.to_dict()
            self.repository.succeed_job(job_id, payload)
            terminal = result.data.get("terminal_stage") if isinstance(result.data, dict) else None
            if isinstance(terminal, str) and terminal:
                message = str(result.data.get("message") or "Job completed")
                self.repository.update_progress(job_id, 1.0, terminal, message)
        except JobCancelled:
            cancelled = self.repository.get_job(job_id)
            if cancelled is None:
                raise PluginError(f"unknown job: {job_id}")
            return cancelled
        except Exception as exc:  # task boundary: preserve failure for the UI
            current = self.repository.get_job(job_id)
            stage = current.stage if current is not None else "failed"
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "stage": stage,
                "traceback": traceback.format_exc(limit=10),
            }
            logger.exception("job %s failed during stage %s", job_id, stage)
            try:
                self.repository.fail_job(job_id, error)
            except Exception:
                logger.exception("could not persist failure for job %s", job_id)
                raise
        final = self.repository.get_job(job_id)
        if final is None:  # pragma: no cover - protects a broken repository adapter
            raise RuntimeError(f"job disappeared after execution: {job_id}")
        return final
