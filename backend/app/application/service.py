"""Task use cases: validate, enqueue, execute, and read plugin jobs."""

from __future__ import annotations

import sys
import uuid
import os
from pathlib import Path
from contextlib import nullcontext
from experiments.scene_lock import scene_write_lock
import logging
from typing import Any

from backend.app.domain.jobs import TERMINAL_JOB_STATUSES, JobCancelled, JobRecord, JobStatus
from backend.app.domain.plugins import PluginError, PluginRegistry, PluginResult
from backend.app.infrastructure.queue import TaskQueue
from backend.app.infrastructure.repository import JobRepository


logger = logging.getLogger("site-modeling-job-service")


def release_cuda_cache() -> None:
    """Return unused CUDA blocks. Tensors that are still referenced stay."""

    # 调用返回后临时张量已无引用，缓存分配器仍占着峰值。方案重算的场景缓存另有引用，不会被清掉。
    torch = sys.modules.get("torch")
    if torch is None or not torch.cuda.is_initialized():
        return
    reserved_before = torch.cuda.memory_reserved()
    torch.cuda.empty_cache()
    reserved_after = torch.cuda.memory_reserved()
    if reserved_after < reserved_before:
        logger.info(
            "released unused CUDA cache reserved_mib %.0f -> %.0f",
            reserved_before / 2**20,
            reserved_after / 2**20,
        )


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
        defaults = plugin.describe().config_schema.get("properties", {})
        if "scene_name" not in config and defaults.get("scene_name", {}).get("default"):
            config = {**config, "scene_name": defaults["scene_name"]["default"]}
        scene_name = config.get("scene_name") or config.get("scene_id")
        lock = scene_write_lock(str(scene_name), Path(os.getenv("SCENE_ROOT", "scenes"))) if scene_name else nullcontext()
        with lock:
            if scene_name:
                from experiments.scene_store import ensure_scene_writable, scene_directory, scenes_root
                ensure_scene_writable(scene_directory(scenes_root(), str(scene_name)))
            record = self.repository.create_job(job_id, plugin.id, plugin.version, config)
            self.queue.enqueue(job_id)
        return record

    def recover_jobs(self) -> None:
        """Called only after acquiring the deployment's exclusive worker lock."""
        for record in self.repository.list_active_jobs():
            if record.status == JobStatus.QUEUED:
                self.queue.enqueue(record.id)
            elif record.status == JobStatus.CANCELLING:
                self.repository.finish_cancel(record.id)
            else:
                self.repository.fail_job(record.id, {"type": "WorkerInterrupted", "job_id": record.id,
                    "stage": record.stage, "message": "Worker 已中断；未自动重跑，请检查后重新提交。"})

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
        if not self.repository.start_job(job_id):
            return self.repository.get_job(job_id)
        try:
            plugin = self.registry.get(record.plugin_id)

            def report(progress: float, stage: str, message: str) -> None:
                current = self.repository.get_job(job_id)
                if current is not None and current.status in {JobStatus.CANCELLING, JobStatus.CANCELLED}:
                    raise JobCancelled("构建已终止")
                if not self.repository.update_progress(job_id, progress, stage, message):
                    current = self.repository.get_job(job_id)
                    if current and current.status in {JobStatus.CANCELLING, JobStatus.CANCELLED}:
                        raise JobCancelled("构建已终止")

            result: PluginResult = plugin.run(record.config, report)
            if result.status != JobStatus.SUCCEEDED.value:
                raise PluginError(
                    f"plugin returned non-success status: {result.status!r}"
                )
            finished = self.repository.get_job(job_id)
            if finished is not None and finished.status in {JobStatus.CANCELLING, JobStatus.CANCELLED}:
                self.repository.finish_cancel(job_id)
                return self.repository.get_job(job_id)
            payload = result.to_dict()
            if not self.repository.succeed_job(job_id, payload):
                self.repository.finish_cancel(job_id)
                return self.repository.get_job(job_id)
        except JobCancelled:
            self.repository.finish_cancel(job_id)
            cancelled = self.repository.get_job(job_id)
            if cancelled is None:
                raise PluginError(f"unknown job: {job_id}")
            return cancelled
        except Exception as exc:  # task boundary: preserve failure for the UI
            current = self.repository.get_job(job_id)
            if current is not None and current.status == JobStatus.CANCELLING:
                self.repository.finish_cancel(job_id)
                return self.repository.get_job(job_id)
            if current is not None and current.status in TERMINAL_JOB_STATUSES:
                return current
            stage = current.stage if current is not None else "failed"
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "stage": stage,
                "job_id": job_id,
            }
            logger.exception("job %s failed during stage %s", job_id, stage)
            try:
                self.repository.fail_job(job_id, error)
            except Exception:
                logger.exception("could not persist failure for job %s", job_id)
                raise
        finally:
            try:
                release_cuda_cache()
            except Exception:
                logger.exception("could not release CUDA cache after job %s", job_id)
        final = self.repository.get_job(job_id)
        if final is None:  # pragma: no cover - protects a broken repository adapter
            raise RuntimeError(f"job disappeared after execution: {job_id}")
        return final
