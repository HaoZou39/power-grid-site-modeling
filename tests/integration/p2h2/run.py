"""Start an isolated PostgreSQL, then the P2-H2 tests. Redis is used only when a server is already reachable."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.integration.p2h2.postgres_local import LocalPostgres, binaries_available

REPO = Path(__file__).resolve().parents[3]
PYTHON = "/home/haozou/miniconda3/envs/torch311/bin/python"


def _docker_ready() -> bool:
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _redis_on_path() -> str:
    return shutil.which("redis-server") or ""


def main() -> int:
    print("docker: available" if _docker_ready() else "docker: unavailable to this user", flush=True)
    if not binaries_available():
        print("postgres: no local PostgreSQL 16 binaries", flush=True)
        return 2
    if not _redis_on_path():
        print("redis: no redis-server on PATH", flush=True)
    root = Path(tempfile.mkdtemp(prefix="p2h2-"))
    password = "p2h2-" + os.urandom(9).hex()
    postgres = LocalPostgres(root, password)
    try:
        postgres.start()
        print(f"postgres: {postgres.version()} on 127.0.0.1:{postgres.port}", flush=True)
        env = os.environ.copy()
        env["P2H2_DATABASE_URL"] = postgres.url("p2h2")
        env["TEST_ACCOUNT_DATABASE_URL"] = postgres.url("p1_account_repair")
        env["TEST_JOB_DATABASE_URL"] = postgres.url("p1_account_repair")
        env["DATABASE_URL"] = postgres.url("p2h2")
        env.pop("REDIS_URL", None)
        integration = subprocess.run(
            [PYTHON, "-m", "pytest", "-q", "tests/integration/p2h2", "--tb=short"],
            cwd=REPO, env=env,
        )
        existing = subprocess.run(
            [
                PYTHON, "-m", "pytest", "-q", "--tb=line",
                "tests/test_workspace_bound_jobs.py::test_postgres_job_row_stores_the_same_frozen_binding",
                "tests/test_planning_workspaces.py::test_postgres_workspace_semantics_match_sqlite",
                "tests/test_workspace_revisions.py::test_postgres_revisions_match_sqlite",
                "tests/test_account_postgres.py",
            ],
            cwd=REPO, env=env,
        )
        return integration.returncode or existing.returncode
    finally:
        postgres.stop()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
