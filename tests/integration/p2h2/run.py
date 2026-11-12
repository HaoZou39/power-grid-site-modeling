"""Start an isolated PostgreSQL, then the P2-H2 tests. Redis is used only when a server is already reachable."""

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


def _docker_ready() -> bool:
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main() -> int:
    redis_only = "--redis-only" in sys.argv
    print("docker: available" if _docker_ready() else "docker: unavailable to this user", flush=True)
    if not binaries_available():
        print("postgres: no local PostgreSQL 16 binaries", flush=True)
        return 2
    binary = redis_binary()
    if binary is None:
        print("redis: no redis-server binary", flush=True)
        if redis_only:
            return 2
    root = Path(tempfile.mkdtemp(prefix="p2h2-"))
    password = "p2h2-" + os.urandom(9).hex()
    postgres = LocalPostgres(root, password)
    redis = LocalRedis(root / "redis", binary) if binary is not None else None
    try:
        postgres.start()
        print(f"postgres: {postgres.version()} on 127.0.0.1:{postgres.port}", flush=True)
        env = os.environ.copy()
        env["P2H2_DATABASE_URL"] = postgres.url("p2h2")
        env["TEST_ACCOUNT_DATABASE_URL"] = postgres.url("p1_account_repair")
        env["TEST_JOB_DATABASE_URL"] = postgres.url("p1_account_repair")
        env["DATABASE_URL"] = postgres.url("p2h2")
        env["P2H2_PYTHON"] = python_executable()
        env.pop("REDIS_URL", None)
        if redis is not None:
            redis.start()
            env["P2H2_REDIS_URL"] = redis.url()
            print(f"redis: {redis.version()} on 127.0.0.1:{redis.port}", flush=True)
        python = python_executable()
        if redis_only:
            return subprocess.run(
                [python, "-m", "pytest", "-q", "tests/integration/p2h2/test_redis_worker.py", "--tb=short"],
                cwd=REPO, env=env,
            ).returncode
        integration = subprocess.run(
            [python, "-m", "pytest", "-q", "tests/integration/p2h2", "--tb=short"],
            cwd=REPO, env=env,
        )
        existing = subprocess.run(
            [
                python, "-m", "pytest", "-q", "--tb=line",
                "tests/test_workspace_bound_jobs.py::test_postgres_job_row_stores_the_same_frozen_binding",
                "tests/test_planning_workspaces.py::test_postgres_workspace_semantics_match_sqlite",
                "tests/test_workspace_revisions.py::test_postgres_revisions_match_sqlite",
                "tests/test_account_postgres.py",
            ],
            cwd=REPO, env=env,
        )
        return integration.returncode or existing.returncode
    finally:
        if redis is not None:
            redis.stop()
        postgres.stop()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
