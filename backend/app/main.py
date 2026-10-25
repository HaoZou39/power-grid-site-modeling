"""FastAPI application factory for local and Compose deployments."""

from __future__ import annotations

import os

os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")

import threading
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from backend.app.api.agent_routes import router as agent_router
from backend.app.api.favorites_routes import router as favorites_router
from backend.app.api.routes import router
from backend.app.application.registry import build_registry
from backend.app.application.service import JobService
from backend.app.domain.plugins import PluginRegistry
from backend.app.infrastructure.queue import create_task_queue
from backend.app.infrastructure.queue import InMemoryTaskQueue
from backend.app.infrastructure.worker_session import worker_session
from backend.app.infrastructure.repository import create_job_repository
from backend.app.infrastructure.experiment_catalog import ExperimentCatalog
from backend.app.infrastructure.favorite_repository import FavoritePointRepository


logger = logging.getLogger("site-modeling-api")


def create_app(
    database_url: str | None = None,
    redis_url: str | None = None,
    registry: PluginRegistry | None = None,
    experiment_root: str | Path | None = None,
    favorite_db_path: str | Path | None = None,
) -> FastAPI:
    """Assemble the application from explicit domain and infrastructure parts."""
    database_url = database_url or os.getenv("DATABASE_URL", "sqlite://:memory:")
    redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
    service = JobService(
        repository=create_job_repository(database_url),
        queue=create_task_queue(redis_url),
        registry=registry if registry is not None else build_registry(),
    )

    stop = threading.Event()
    ready = threading.Event()
    startup_errors: list[Exception] = []

    def run_local_worker() -> None:
        try:
            with worker_session(service, Path(experiment_root or os.getenv("EXPERIMENT_OUTPUT_ROOT", "outputs"))):
                ready.set()
                while not stop.is_set():
                    message = service.queue.dequeue(timeout=1)
                    if message is not None:
                        try:
                            service.execute_job(message.job_id)
                        except Exception:
                            logger.exception("local worker failed while processing job %s", message.job_id)
        except Exception as exc:
            startup_errors.append(exc)
            ready.set()
            logger.exception("local worker stopped")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        thread = None
        if isinstance(service.queue, InMemoryTaskQueue):
            thread = threading.Thread(target=run_local_worker, name="v0-local-worker", daemon=True)
            thread.start()
            ready.wait()
            if startup_errors:
                raise startup_errors[0]
            _app.state.local_worker = thread
        try:
            yield
        finally:
            stop.set()
            if thread is not None:
                import asyncio
                await asyncio.to_thread(thread.join)

    app = FastAPI(title="Power Grid Site Modeling API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.job_service = service
    app.state.experiment_catalog = ExperimentCatalog(
        experiment_root or os.getenv("EXPERIMENT_OUTPUT_ROOT", "outputs")
    )
    if favorite_db_path is None:
        favorite_db_path = Path(os.getenv("FAVORITES_DB_PATH", "outputs/user-state/favorites.sqlite3")).expanduser()
        if not favorite_db_path.is_absolute():
            favorite_db_path = Path(__file__).resolve().parents[2] / favorite_db_path
    app.state.favorite_point_repository = FavoritePointRepository(favorite_db_path)
    app.include_router(router())
    app.include_router(agent_router())
    app.include_router(favorites_router)
    frontend_url = os.getenv("FRONTEND_URL", "http://127.0.0.1:5176").rstrip("/")

    @app.get("/", include_in_schema=False)
    async def open_ui() -> RedirectResponse:
        return RedirectResponse(frontend_url, status_code=307)

    return app


app = create_app()
