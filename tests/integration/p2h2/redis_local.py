"""A private Redis process for one test run. It is not a system service."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path


def redis_binary() -> Path | None:
    named = os.environ.get("P2H2_REDIS_SERVER", "")
    if named and Path(named).is_file():
        return Path(named)
    found = shutil.which("redis-server")
    if found:
        return Path(found)
    candidate = Path.home() / "miniconda3/envs/p2h2-redis/bin/redis-server"
    return candidate if candidate.is_file() else None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class LocalRedis:
    def __init__(self, root: Path, binary: Path) -> None:
        self.root = root
        self.binary = binary
        self.port = _free_port()
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        log = open(self.root / "redis.log", "ab")
        self.process = subprocess.Popen(
            [
                str(self.binary),
                "--bind", "127.0.0.1",
                "--port", str(self.port),
                "--dir", str(self.root),
                "--dbfilename", "dump.rdb",
                "--save", "",
                "--appendonly", "no",
                "--daemonize", "no",
                "--protected-mode", "yes",
                "--databases", "1",
            ],
            stdout=log, stderr=log,
        )
        cli = self.binary.with_name("redis-cli")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError((self.root / "redis.log").read_text(encoding="utf-8", errors="replace")[-2000:])
            ping = subprocess.run(
                [str(cli), "-h", "127.0.0.1", "-p", str(self.port), "PING"],
                capture_output=True, text=True,
            )
            if ping.stdout.strip() == "PONG":
                return
            time.sleep(0.1)
        raise RuntimeError("Redis 在 15 秒内没有响应 PING")

    def url(self) -> str:
        return f"redis://127.0.0.1:{self.port}/0"

    def version(self) -> str:
        result = subprocess.run(
            [str(self.binary.with_name("redis-cli")), "-h", "127.0.0.1", "-p", str(self.port), "INFO", "server"],
            check=True, capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("redis_version:"):
                return line.split(":", 1)[1].strip()
        return "unknown"

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
