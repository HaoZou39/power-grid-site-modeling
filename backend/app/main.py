from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router
from backend.app.application.registry import build_registry
from backend.app.application.service import JobService
from backend.app.infrastructure.queue import create_task_queue
from backend.app.infrastructure.queue import InMemoryTaskQueue
from backend.app.infrastructure.repository import create_job_repository


def create_app(
    database_url: str | None = None,
    redis_url: str | None = None,
) -> FastAPI:
    database_url = database_url or os.getenv("DATABASE_URL", "sqlite:///outputs/v0/jobs.db")
    redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
    service = JobService(
        repository=create_job_repository(database_url),
        queue=create_task_queue(redis_url),
        registry=build_registry(),
    )

    def run_local_worker() -> None:
        while True:
            message = service.queue.dequeue(timeout=1)
            if message is not None:
                service.execute_job(message.job_id)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if isinstance(service.queue, InMemoryTaskQueue):
            thread = threading.Thread(
                target=run_local_worker,
                name="v0-local-worker",
                daemon=True,
            )
            thread.start()
            _app.state.local_worker = thread
        yield

    app = FastAPI(title="Power Grid Site Modeling API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.job_service = service
    app.include_router(router())
    return app


app = create_app()
