from backend.app.application.registry import build_registry
from backend.app.application.service import JobService
from backend.app.main import create_app
from backend.app.infrastructure.queue import InMemoryTaskQueue
from backend.app.infrastructure.repository import SQLiteJobRepository


def test_registry_lists_demo_plugin() -> None:
    registry = build_registry()
    specs = registry.list_specs()
    assert [spec.id for spec in specs] == [
        "demo.algorithm",
        "site.cma_es",
        "site.guided_search",
        "site.multistart_adam",
        "site.prepare_scene",
    ]
    assert specs[0].kind == "algorithm"


def test_plugin_schema_exposes_demo_defaults_for_schema_driven_ui() -> None:
    spec = build_registry().list_specs()[0]
    properties = spec.config_schema["properties"]

    assert properties["values"]["default"] == [1.0, 2.0, 3.0]
    assert properties["multiplier"]["default"] == 1.0


def test_demo_job_executes_and_persists_result() -> None:
    repository = SQLiteJobRepository(":memory:")
    queue = InMemoryTaskQueue()
    service = JobService(repository, queue, build_registry())

    record = service.create_job("demo.algorithm", {"values": [1, 2, 3], "multiplier": 2})
    assert record.status.value == "queued"
    message = queue.dequeue(timeout=0)
    assert message is not None and message.job_id == record.id

    final = service.execute_job(record.id)
    assert final.status.value == "succeeded"
    assert final.result is not None
    assert final.result["metrics"]["sum"] == 6
    assert final.result["metrics"]["weighted_sum"] == 12


def test_cancel_before_execution_is_not_overwritten() -> None:
    repository = SQLiteJobRepository(":memory:")
    service = JobService(repository, InMemoryTaskQueue(), build_registry())
    record = service.create_job("demo.algorithm", {"values": [1, 2, 3], "multiplier": 2})
    cancelled = service.cancel_job(record.id)
    assert cancelled.status.value == "cancelled"
    final = service.execute_job(record.id)
    assert final.status.value == "cancelled"
    assert final.result is None


def test_invalid_demo_config_fails_before_creating_job() -> None:
    repository = SQLiteJobRepository(":memory:")
    service = JobService(repository, InMemoryTaskQueue(), build_registry())

    try:
        service.create_job("demo.algorithm", {"values": []})
    except ValueError as exc:
        assert "values" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid configuration was accepted")


def test_second_plugin_can_be_added_without_changing_job_service() -> None:
    from backend.app.domain.plugins import PluginRegistry, PluginResult, PluginSpec

    class SecondPlugin:
        id = "test.second"
        version = "0.1.0"

        def describe(self):
            return PluginSpec(self.id, self.version, "metric", "Second", "test")

        def validate_config(self, config):
            if config != {}:
                raise ValueError("expected empty config")

        def run(self, config, reporter):
            reporter(1.0, "done", "done")
            return PluginResult("succeeded", {"value": 1.0})

    registry = PluginRegistry()
    registry.register(SecondPlugin())
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), registry)
    final = service.execute_job(service.create_job("test.second", {}).id)
    assert final.result["metrics"]["value"] == 1.0


def test_unregistered_plugin_is_recorded_as_failed_and_does_not_raise() -> None:
    registry = build_registry()
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), registry)
    job = service.create_job("demo.algorithm", {"values": [1]})
    registry._plugins.pop("demo.algorithm")

    final = service.execute_job(job.id)

    assert final.status.value == "failed"
    assert final.error is not None
    assert final.error["type"] == "PluginError"


def test_non_success_plugin_result_is_recorded_as_failed() -> None:
    from backend.app.domain.plugins import PluginRegistry, PluginResult, PluginSpec

    class UnsuccessfulPlugin:
        id = "test.unsuccessful"
        version = "0.1.0"

        def describe(self):
            return PluginSpec(self.id, self.version, "algorithm", "Unsuccessful", "test")

        def validate_config(self, config):
            if config != {}:
                raise ValueError("expected empty config")

        def run(self, config, reporter):
            return PluginResult("failed", {}, data={"reason": "known failure"})

    registry = PluginRegistry()
    registry.register(UnsuccessfulPlugin())
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), registry)

    final = service.execute_job(service.create_job("test.unsuccessful", {}).id)

    assert final.status.value == "failed"
    assert final.error is not None
    assert "non-success status" in final.error["message"]


def test_app_accepts_an_explicit_plugin_registry() -> None:
    from backend.app.domain.plugins import PluginRegistry

    registry = PluginRegistry()

    app = create_app("sqlite://:memory:", "", registry=registry)

    assert app.state.job_service.registry is registry
