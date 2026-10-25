"""Single-executor ownership and recovery for local and Compose workers."""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.app.application.service import JobService
from experiments.scene_lock import file_lock


@contextmanager
def worker_session(service: JobService, output_root: Path) -> Iterator[None]:
    with file_lock(output_root / "user-state/worker.lock"):
        service.recover_jobs()
        yield
