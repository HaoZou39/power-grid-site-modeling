import threading

from backend.app.application.registry import build_registry
from backend.app.application.service import JobService
from backend.app.domain.plugins import PluginRegistry, PluginSpec
from backend.app.infrastructure.queue import InMemoryTaskQueue
from backend.app.infrastructure.repository import SQLiteJobRepository


def test_running_cancellation_keeps_scene_busy_until_executor_stops():
    entered, release = threading.Event(), threading.Event()

    class Pausing:
        id, version = "test.pausing", "0"
        def describe(self):
            return PluginSpec(self.id, self.version, "algorithm", "Pause", "test")
        def validate_config(self, config):
            pass
        def run(self, config, report):
            entered.set()
            assert release.wait(3)
            report(.5, "working", "checkpoint")

    registry = PluginRegistry()
    registry.register(Pausing())
    repository = SQLiteJobRepository(":memory:")
    service = JobService(repository, InMemoryTaskQueue(), registry)
    record = service.create_job(Pausing.id, {"scene_name": "demo"})
    worker = threading.Thread(target=service.execute_job, args=(record.id,))
    worker.start()
    try:
        assert entered.wait(3)
        assert service.cancel_job(record.id).status.value == "cancelling"
        assert "demo" in repository.active_scene_names()
    finally:
        release.set()
        worker.join(3)
    assert repository.get_job(record.id).status.value == "cancelled"
    assert not repository.active_scene_names()


def test_duplicate_delivery_never_reexecutes_completed_job():
    repository = SQLiteJobRepository(":memory:")
    service = JobService(repository, InMemoryTaskQueue(), build_registry())
    record = service.create_job("demo.algorithm", {"values": [1], "multiplier": 2})
    first = service.execute_job(record.id)
    second = service.execute_job(record.id)
    assert first == second


def test_startup_recovery_fails_running_and_requeues_queued(tmp_path):
    repository = SQLiteJobRepository(tmp_path / "jobs.db")
    service = JobService(repository, InMemoryTaskQueue(), build_registry())
    running = service.create_job("demo.algorithm", {"values": [1]})
    cancelling = service.create_job("demo.algorithm", {"values": [2]})
    queued = service.create_job("demo.algorithm", {"values": [3]})
    repository.start_job(running.id)
    repository.start_job(cancelling.id)
    service.cancel_job(cancelling.id)
    restarted = JobService(SQLiteJobRepository(tmp_path / "jobs.db"), InMemoryTaskQueue(), build_registry())
    restarted.recover_jobs()
    assert restarted.get_job(running.id).status.value == "failed"
    assert restarted.get_job(cancelling.id).status.value == "cancelled"
    assert restarted.queue.dequeue(0).job_id == queued.id
    assert restarted.queue.dequeue(0) is None


def test_two_repository_connections_cannot_claim_the_same_job(tmp_path):
    path = tmp_path / "jobs.db"
    left, right = SQLiteJobRepository(path), SQLiteJobRepository(path)
    service = JobService(left, InMemoryTaskQueue(), build_registry())
    record = service.create_job("demo.algorithm", {"values": [1]})
    barrier = threading.Barrier(2)
    claims = []

    def claim(repository):
        barrier.wait()
        claims.append(repository.start_job(record.id))

    threads = [threading.Thread(target=claim, args=(repository,)) for repository in (left, right)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
    assert sorted(claims) == [False, True]


def test_public_job_response_does_not_expose_old_tracebacks():
    repository = SQLiteJobRepository(":memory:")
    service = JobService(repository, InMemoryTaskQueue(), build_registry())
    record = service.create_job("demo.algorithm", {"values": [1]})
    repository.fail_job(record.id, {"message": "failure", "traceback": "/private/path"})
    assert "traceback" not in repository.get_job(record.id).to_dict()["error"]
