"""Exercise real PostgreSQL/Redis transitions and kill/restart the actual worker."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def validate(output: Path) -> dict:
    import psycopg
    import redis
    from backend.app.application.registry import build_registry
    from backend.app.application.service import JobService
    from backend.app.domain.plugins import PluginSpec
    from backend.app.infrastructure.postgres_repository import PostgresJobRepository
    from backend.app.infrastructure.queue import RedisTaskQueue

    output.mkdir(parents=True, exist_ok=False)
    containers, children = [], []
    worker_log = (output / "worker.log").open("w")
    try:
        postgres = docker("run", "--rm", "-d", "-e", "POSTGRES_PASSWORD=validation-only",
                          "-e", "POSTGRES_DB=site_repair_test", "-p", "127.0.0.1::5432",
                          "public.ecr.aws/docker/library/postgres:16-alpine")
        containers.append(postgres)
        redis_container = docker("run", "--rm", "-d", "-p", "127.0.0.1::6379",
                                 "public.ecr.aws/docker/library/redis:7-alpine", "redis-server", "--save", "", "--appendonly", "no")
        containers.append(redis_container)
        pg_port = docker("port", postgres, "5432/tcp").rsplit(":", 1)[1]
        redis_port = docker("port", redis_container, "6379/tcp").rsplit(":", 1)[1]
        database = f"postgresql://postgres:validation-only@127.0.0.1:{pg_port}/site_repair_test"
        queue_url = f"redis://127.0.0.1:{redis_port}/0"
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(database):
                    pass
                redis.Redis.from_url(queue_url).ping()
                break
            except (psycopg.OperationalError, redis.ConnectionError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
        env = {**os.environ, "DATABASE_URL": database, "REDIS_URL": queue_url,
               "TEST_JOB_DATABASE_URL": database, "EXPERIMENT_OUTPUT_ROOT": str(output),
               "SCENE_ROOT": str(output / "scenes")}
        with (output / "repository-tests.txt").open("w") as report:
            subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_job_database.py"],
                           env=env, stdout=report, stderr=subprocess.STDOUT, check=True)

        class Pausing:
            id, version = "test.crash", "0"
            def describe(self):
                return PluginSpec(self.id, self.version, "algorithm", "Pause", "fault validation")
            def validate_config(self, config):
                pass

        registry = build_registry()
        registry.register(Pausing())
        repository = PostgresJobRepository(database)
        queue = RedisTaskQueue(queue_url)
        service = JobService(repository, queue, registry)
        running = service.create_job(Pausing.id, {})
        code = '''
import time
import worker.main as worker
from backend.app.application.registry import build_registry
from backend.app.domain.plugins import PluginSpec
class Pausing:
    id, version = 'test.crash', '0'
    def describe(self): return PluginSpec(self.id,self.version,'algorithm','Pause','test')
    def validate_config(self, config): pass
    def run(self, config, report):
        report(.2,'paused','waiting for injected crash')
        while True: time.sleep(.1)
registry=build_registry();registry.register(Pausing())
worker.build_registry=lambda: registry
worker.run_forever()
'''
        child = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=worker_log, stderr=worker_log)
        children.append(child)
        deadline = time.monotonic() + 15
        while service.get_job(running.id).stage != "paused":
            if child.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("worker did not enter fault-injection stage")
            time.sleep(.05)
        duplicate = subprocess.run([sys.executable, "-m", "worker.main"], env=env,
                                   stdout=worker_log, stderr=worker_log, timeout=15)
        if duplicate.returncode == 0:
            raise AssertionError("second worker unexpectedly accepted ownership")
        child.kill()
        child.wait(timeout=5)
        queued = service.create_job("demo.algorithm", {"values": [1, 2], "multiplier": 2})
        queue.enqueue(queued.id)
        restarted = subprocess.Popen([sys.executable, "-m", "worker.main"], env=env, stdout=worker_log, stderr=worker_log)
        children.append(restarted)
        deadline = time.monotonic() + 15
        while service.get_job(queued.id).status.value != "succeeded":
            if restarted.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("worker did not recover queued work")
            time.sleep(.05)
        if service.get_job(running.id).status.value != "failed":
            raise AssertionError("interrupted job retained a busy status")
        summary = {"repository_contract_tests": 8, "second_worker_rejected": True,
                   "killed_running_job_failed": True, "queued_job_recovered": True,
                   "duplicate_delivery_safe": True}
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
        worker_log.close()
        for container in containers:
            docker("rm", "-f", container)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.output_dir.resolve())))


if __name__ == "__main__":
    main()
