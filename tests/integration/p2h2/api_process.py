"""One FastAPI process. It does not start the in-process worker when REDIS_URL is set."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[3]


def python_executable() -> str:
    return os.environ.get("P2H2_PYTHON") or sys.executable


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class ApiProcess:
    def __init__(self, root: Path, database_url: str, redis_url: str) -> None:
        self.root = root
        self.database_url = database_url
        self.redis_url = redis_url
        self.port = _free_port()
        self.process: subprocess.Popen[bytes] | None = None
        self.log = root / "api.log"

    def start(self, *, bootstrap: bool) -> None:
        env = os.environ.copy()
        for name in ("DATABASE_URL", "REDIS_URL", "TEST_ACCOUNT_DATABASE_URL", "TEST_JOB_DATABASE_URL"):
            env.pop(name, None)
        env.update({
            "DATABASE_URL": self.database_url,
            "REDIS_URL": self.redis_url,
            "SCENE_ROOT": str(self.root / "scenes"),
            "EXPERIMENT_OUTPUT_ROOT": str(self.root / "outputs"),
            "BASE_SNAPSHOT_ROOT": str(self.root / "snapshots"),
            "AGENT_MEMORY_ROOT": str(self.root / "memory"),
            "FAVORITES_DB_PATH": str(self.root / "favorites.sqlite3"),
            "BOOTSTRAP_ADMIN_USERNAME": "p2h2-admin" if bootstrap else "",
            "BOOTSTRAP_ADMIN_PASSWORD": "p2h2-admin-pass-9f3c" if bootstrap else "",
            "PYTHONUNBUFFERED": "1",
        })
        self.log.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log, "ab")
        self.process = subprocess.Popen(
            [python_executable(), "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=REPO, env=env, stdout=log, stderr=log,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(self._tail())
            try:
                response = httpx.get(self.health, timeout=1)
            except httpx.HTTPError:
                time.sleep(0.2)
                continue
            if response.status_code == 200:
                names = [path.read_text(encoding="utf-8").strip() for path in Path(f"/proc/{self.process.pid}/task").glob("*/comm")]
                if "v0-local-worker" in names:
                    raise RuntimeError("Redis 模式下 API 启动了进程内 Worker")
                return
            time.sleep(0.2)
        raise RuntimeError(self._tail() or "API 在 90 秒内没有就绪")

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    @property
    def health(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1/health"

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=f"http://127.0.0.1:{self.port}", timeout=30)

    def _tail(self) -> str:
        if not self.log.is_file():
            return ""
        return self.log.read_text(encoding="utf-8", errors="replace")[-2000:]
