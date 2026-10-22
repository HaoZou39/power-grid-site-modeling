"""Production-shaped worker process entry point."""

from __future__ import annotations

import logging
import os

os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")

from backend.app.application.registry import build_registry
from backend.app.application.service import JobService
from backend.app.infrastructure.queue import create_task_queue
from backend.app.infrastructure.repository import create_job_repository


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("site-modeling-worker")


def run_forever() -> None:
    repository = create_job_repository(os.getenv("DATABASE_URL", "sqlite://:memory:"))
    queue = create_task_queue(os.getenv("REDIS_URL", ""))
    service = JobService(repository=repository, queue=queue, registry=build_registry())
    logger.info("worker started")
    while True:
        message = queue.dequeue(timeout=5)
        if message is None:
            continue
        logger.info("executing job %s", message.job_id)
        try:
            service.execute_job(message.job_id)
        except Exception:
            logger.exception("worker boundary failed while processing job %s", message.job_id)


if __name__ == "__main__":
    run_forever()
