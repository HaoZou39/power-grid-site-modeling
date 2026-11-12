"""Start isolated PostgreSQL and Redis, then the real single-GPU site and routing test."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.integration.p2h2.api_process import python_executable
from tests.integration.p2h2.postgres_local import LocalPostgres, binaries_available
from tests.integration.p2h2.redis_local import LocalRedis, redis_binary

REPO = Path(__file__).resolve().parents[3]


def select_gpu() -> dict | None:
    text = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
        text=True,
    )
    idle = []
    for line in text.splitlines():
        index, uuid, name, total, free, util = [item.strip() for item in line.split(",")]
        row = {"index": index, "uuid": uuid, "name": name, "total_mib": int(total), "free_mib": int(free), "util": int(util)}
        if row["util"] == 0 and row["free_mib"] >= 20000:
            idle.append(row)
    if not idle:
        return None
    return sorted(idle, key=lambda row: (-row["free_mib"], int(row["index"])))[0]


def main() -> int:
    chosen = select_gpu()
    if chosen is None:
        print("gpu: every device is busy or has under 20000 MiB free", flush=True)
        return 2
    if not binaries_available():
        print("postgres: no local PostgreSQL 16 binaries", flush=True)
        return 2
    binary = redis_binary()
    if binary is None:
        print("redis: no redis-server binary", flush=True)
        return 2
    driver = subprocess.check_output(
        ["nvidia-smi", f"--id={chosen['index']}", "--query-gpu=driver_version", "--format=csv,noheader"],
        text=True,
    ).strip()
    print(
        f"gpu: physical {chosen['index']} {chosen['name']} {chosen['uuid']} free={chosen['free_mib']} MiB driver={driver}",
        flush=True,
    )
    root = Path(tempfile.mkdtemp(prefix="p2i-"))
    password = "p2i-" + os.urandom(9).hex()
    postgres = LocalPostgres(root, password)
    redis = LocalRedis(root / "redis", binary)
    report = root / "report.json"
    try:
        postgres.start()
        redis.start()
        ping = subprocess.run(
            [str(binary.with_name("redis-cli")), "-h", "127.0.0.1", "-p", str(redis.port), "PING"],
            check=True, capture_output=True, text=True,
        )
        if ping.stdout.strip() != "PONG":
            print("redis: PING did not return PONG", flush=True)
            return 2
        print(f"postgres: {postgres.version()} on 127.0.0.1:{postgres.port}", flush=True)
        print(f"redis: {redis.version()} on 127.0.0.1:{redis.port}", flush=True)
        env = os.environ.copy()
        env.pop("REDIS_URL", None)
        env.update({
            "P2I_REQUIRED": "1",
            "P2I_DATABASE_URL": postgres.url("p2h2"),
            "P2I_REDIS_URL": redis.url(),
            "P2I_GPU_INDEX": chosen["index"],
            "P2I_GPU_UUID": chosen["uuid"],
            "P2I_GPU_NAME": chosen["name"],
            "P2I_DRIVER": driver,
            "P2I_REPORT": str(report),
            "P2H2_PYTHON": python_executable(),
        })
        code = subprocess.run(
            [python_executable(), "-m", "pytest", "-q", "tests/integration/p2i/test_real_gpu.py", "--tb=short"],
            cwd=REPO, env=env,
        ).returncode
        if report.is_file():
            print(report.read_text(encoding="utf-8"), flush=True)
        return code
    finally:
        redis.stop()
        postgres.stop()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
