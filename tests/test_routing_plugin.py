import pytest

from backend.app.application.registry import build_registry
from backend.app.application.service import JobService
from backend.app.infrastructure.queue import InMemoryTaskQueue
from backend.app.infrastructure.repository import SQLiteJobRepository
from config.project_config import load_default_config
from plugins.routing_plugin import RoutingPlugin
from test_routing_output import routing_task


def test_schema_defaults_and_required_engineering_inputs():
    schema = RoutingPlugin().describe().config_schema
    assert schema["properties"]["algorithm"]["default"]["seed"] == load_default_config().routing.seed
    assert {"max_span_m", "tower_radius_m", "max_turn_deg", "start", "end"} <= set(schema["required"])
    with pytest.raises(ValueError):
        RoutingPlugin().validate_config({"scene_name": "missing"})


def test_registered_job_runs_through_existing_service(tmp_path, monkeypatch):
    task, _ = routing_task(tmp_path, monkeypatch)
    monkeypatch.setenv("EXPERIMENT_OUTPUT_ROOT", str(tmp_path / "runs"))
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), build_registry())
    created = service.create_job("routing.nsga2", task.model_dump())
    final = service.execute_job(created.id)
    assert final.status.value == "succeeded"
    assert final.result["data"]["problem_type"] == "routing"


def test_invalid_regions_and_unknown_cost_fields_rejected(tmp_path, monkeypatch):
    task, _ = routing_task(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        RoutingPlugin().validate_config({**task.model_dump(), "road_price": 99})
    with pytest.raises(ValueError):
        RoutingPlugin().validate_config({**task.model_dump(), "no_cross_zones": [[[0, 0], [1, 1]]]})


def test_queued_routing_job_blocks_scene_import_changes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    task, _ = routing_task(tmp_path, monkeypatch)
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.post("/api/v1/jobs", json={"plugin_id": "routing.nsga2", "config": task.model_dump()})
    assert response.status_code == 202
    assert client.delete(f"/api/v1/scenes/{task.scene_name}/protected-farmland").status_code == 409
