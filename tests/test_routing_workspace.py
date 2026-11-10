from dataclasses import asdict
import hashlib
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from config.routing_task import RoutingRunConfig
from modeling.routing.types import RoutingFrame


@pytest.fixture
def routing_workspace(tmp_path, monkeypatch):
    scene_root = tmp_path / "scenes"
    scene = scene_root / "routing-test"
    scene.mkdir(parents=True)
    monkeypatch.setenv("SCENE_ROOT", str(scene_root))
    frame = RoutingFrame("EPSG:32651", (1, 0, 221000, 0, -1, 3046000), 32, 32)
    for name, array in {"dem_1m.npy": np.zeros((32, 32)), "landuse_1m.npy": np.zeros((32, 32), dtype=np.int32),
                        "road_segments_local.npy": np.empty((0, 4)), "road_segment_kind.npy": np.empty(0, dtype=np.int8)}.items():
        np.save(scene / name, array)
    (scene / "data_metadata.json").write_text(json.dumps({"dem": {"reference_crs": frame.crs,
        "target_transform": frame.transform, "shape": [32, 32]}}), encoding="utf-8")
    start, end = frame.to_wgs84([2, 8]), frame.to_wgs84([28, 8])
    task = RoutingRunConfig.model_validate({"scene_name": scene.name, "experiment_name": "original",
        "start": dict(zip(["lng", "lat"], start)), "end": dict(zip(["lng", "lat"], end)),
        "max_span_m": 30, "tower_radius_m": .4, "max_turn_deg": 90,
        "road_setback_m": 0, "highway_setback_m": 0}).model_dump()
    root = tmp_path / "outputs"
    source = root / "routing-check"
    source.mkdir(parents=True)
    original = {"schema_version": 1, "problem_type": "routing", "scene_name": scene.name, "frame": asdict(frame),
        "routes": [{"id": "route-1", "points": [{"x": 2, "y": 8}, {"x": 10, "y": 8}, {"x": 28, "y": 8}]}]}
    (source / "routes.json").write_text(json.dumps(original), encoding="utf-8")
    (source / "run_summary.json").write_text('{"problem_type":"routing"}', encoding="utf-8")
    (source / "data_metadata.json").write_text('{"input_hashes":{"dem_1m.npy":"old-source-hash"}}', encoding="utf-8")
    app = create_app("sqlite://:memory:", "", experiment_root=root, favorite_db_path=tmp_path / "favorites.sqlite3")
    with TestClient(app) as client:
        yield client, root, scene, source, task


def save(client, source, task, name="线路案例"):
    return client.post("/api/v1/routing-experiments", json={"name": name, "source_experiment_id": source, "task": task})


def test_case_rechecks_current_constraints_and_round_trips(routing_workspace):
    client, root, scene, source, task = routing_workspace
    source_bytes = (source / "routes.json").read_bytes()
    task["no_cross_zones"] = [[[14, 0], [16, 0], [16, 32], [14, 32]]]
    assert client.get("/api/v1/experiments?cases_only=true").json() == []
    result = save(client, source.name, task, "线路/案例")
    assert result.status_code == 201, result.text
    case = root / result.json()["id"]
    routes = json.loads((case / "routes.json").read_text(encoding="utf-8"))["routes"]
    assert len(routes) == 1 and not routes[0]["is_feasible"]
    summary = json.loads((case / "run_summary.json").read_text(encoding="utf-8"))
    config = json.loads((case / "resolved_config.json").read_text(encoding="utf-8"))
    metadata = json.loads((case / "data_metadata.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == 1 and summary["is_case"] is True
    assert config["experiment_name"] == summary["display_name"] == "线路/案例"
    assert summary["source_experiment_id"] == source.name
    assert metadata["input_hashes"]["dem_1m.npy"] == hashlib.sha256((scene / "dem_1m.npy").read_bytes()).hexdigest()
    assert metadata["source_input_hashes"]["dem_1m.npy"] == "old-source-hash"
    assert not (case / "scene_snapshot").exists()
    assert (source / "routes.json").read_bytes() == source_bytes
    assert [item["id"] for item in client.get("/api/v1/experiments?cases_only=true").json()] == [case.name]
    changed = dict(task, start=task["end"], end=task["start"])
    assert save(client, source.name, changed).status_code == 422
    assert client.delete(f"/api/v1/experiments/{source.name}").status_code == 200
    assert client.get(f"/api/v1/experiments/{case.name}/artifacts/routes.json").json()["routes"] == routes
    again = save(client, case.name, task, "再次另存")
    assert again.status_code == 201 and again.json()["id"] != case.name


@pytest.mark.parametrize("source_name", ["missing", "no-routes"])
def test_missing_source_is_rejected(routing_workspace, source_name):
    client, root, _, _, task = routing_workspace
    if source_name == "no-routes":
        directory = root / source_name
        directory.mkdir()
        (directory / "run_summary.json").write_text('{}', encoding="utf-8")
    assert save(client, source_name, task).status_code == 422
    assert client.get("/api/v1/experiments?cases_only=true").json() == []


def test_changed_grid_is_rejected(routing_workspace):
    client, _, scene, source, task = routing_workspace
    path = scene / "data_metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["dem"]["target_transform"][2] += 1
    path.write_text(json.dumps(metadata), encoding="utf-8")
    result = save(client, source.name, task)
    assert result.status_code == 422 and "坐标网格" in result.text


def test_zero_tower_route_is_valid(routing_workspace):
    client, root, _, source, task = routing_workspace
    path = source / "routes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["routes"][0]["points"] = [data["routes"][0]["points"][0], data["routes"][0]["points"][-1]]
    path.write_text(json.dumps(data), encoding="utf-8")
    result = save(client, source.name, task)
    assert result.status_code == 201, result.text
    route = json.loads((root / result.json()["id"] / "routes.json").read_text(encoding="utf-8"))["routes"][0]
    assert route["is_feasible"] and route["objectives"]["tower_count"] == 0


def test_legacy_and_explicit_cases_are_listed(routing_workspace):
    client, root, _, _, _ = routing_workspace
    for name, summary in [("legacy-site", {"algorithm": "workspace_snapshot"}),
                          ("legacy-routing", {"algorithm": "routing_workspace"}),
                          ("future-routing", {"algorithm": "routing_workspace_v2", "is_case": True})]:
        folder = root / name
        folder.mkdir()
        (folder / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        if name == "legacy-site":
            (folder / "workspace_solutions.json").write_text('{}', encoding="utf-8")
    assert {item["id"] for item in client.get("/api/v1/experiments?cases_only=true").json()} == {
        "legacy-site", "legacy-routing", "future-routing"}
