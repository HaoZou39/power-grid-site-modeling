"""Decision snapshots must survive source cleanup and preserve the complete selection."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_snapshot_writer_does_not_load_modeling_or_tensor_runtime():
    result = subprocess.run([sys.executable, "-c", "import sys; import experiments.filter_case_artifacts; "
        "assert 'modeling.context' not in sys.modules; assert 'torch' not in sys.modules"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def snapshot(problem_type="routing"):
    def data(i):
        if problem_type == "site":
            return {"id": f"s-{i}", "x": i, "y": i, "theta": 0, "feasible": "可行", "paretoLayer": 1,
                    "rawMetrics": {"demSoft": i + 0.123456789012345, "offroadHaul": 10, "haulRise": 1}}
        return {"id": f"s-{i}", "objectives": {"tower_count": 1, "length_3d_m": i + 0.123456789012345,
                "bend_sum_rad": 0, "crossing_3d_m": 2}, "points": [{"x": 0, "y": 0}, {"x": i, "y": 10}],
                "is_feasible": True, "is_pareto": True, "violations": {}}
    return {
        "schema_version": 1, "problem_type": problem_type, "scene_name": "scene-a",
        "source_experiment_id": "already-cleaned-auto-run", "scene_version": {"scene_revision": "v1"},
        "captured_at": "2026-11-19T04:00:00Z", "scope": {"display_mode": "all"},
        "context": {"frame": {"crs": "EPSG:32651", "transform": [1, 0, 0, 0, -1, 100], "width": 50, "height": 50, "frame_id": "frame-a"},
                    "task": {"scene_name": "scene-a"}, "widthM": 10, "heightM": 20, "form": {}},
        "candidates": [{"id": f"s-{i}", "original_number": i + 1,
                        "metrics": {"length": i + 0.123456789012345},
                        "geometry": {"points": [[i, i + 0.123456789012345]]},
                        "data": data(i)} for i in range(75)],
        "retained_ids": [f"s-{i}" for i in reversed(range(61))],
        "stages": [{"key": "length", "direction": "descending", "lower": 0, "upper": 61, "retained_count": 61}],
        "display_sort": {"key": "length", "direction": "descending"},
    }


@pytest.mark.parametrize("problem_type", ["site", "routing"])
def test_save_reopen_and_version_without_source(tmp_path, problem_type):
    payload = {"name": "筛选案例", "snapshot": snapshot(problem_type)}
    with TestClient(create_app("sqlite://:memory:", "", experiment_root=tmp_path)) as client:
        result = client.post("/api/v1/filter-cases", json=payload)
        assert result.status_code == 201, result.text
        case_id = result.json()["id"]
        assert result.json()["solution_count"] == 61  # All pages, not ten or fifty.
        records = client.get("/api/v1/experiments?cases_only=true").json()
        assert records[0]["summary"]["case_kind"] == "filter_result"
        artifact = next(item for item in records[0]["artifacts"] if item["name"] == "filter_snapshot.json")
        reopened = client.get(artifact["url"]).json()
        assert reopened["candidates"] == payload["snapshot"]["candidates"]
        assert reopened["retained_ids"] == payload["snapshot"]["retained_ids"]
        assert reopened["stages"] == payload["snapshot"]["stages"]
        second = client.post("/api/v1/filter-cases", json=payload)
        assert second.status_code == 201 and second.json()["id"] != case_id
        assert len(list(tmp_path.glob("saved-*"))) == 2
        names = {item["name"] for item in records[0]["artifacts"]}
        assert {"solutions.csv", "pareto_solutions.csv", "resolved_config.json", "data_metadata.json", "filter_snapshot.json"} <= names
        metadata = json.loads((tmp_path / case_id / "data_metadata.json").read_text(encoding="utf-8"))
        assert metadata["frame"] == payload["snapshot"]["context"]["frame"]
        assert metadata["coordinate_context"]["scene_id"] == payload["snapshot"]["scene_name"]
        assert metadata["coordinate_context"]["frame"] == payload["snapshot"]["context"]["frame"]
        artifact_name = "workspace_solutions.json" if problem_type == "site" else "routes.json"
        domain = json.loads((tmp_path / case_id / artifact_name).read_text(encoding="utf-8"))
        rows = domain["solutions" if problem_type == "site" else "routes"]
        assert [item["id"] for item in rows] == reopened["retained_ids"]
        assert len(rows) == 61
        if problem_type == "routing":
            assert [row["number"] for row in rows] == list(reversed(range(1, 62)))
        metric = rows[0]["dem_soft"] if problem_type == "site" else rows[0]["objectives"]["length_3d_m"]
        assert metric == 60 + 0.123456789012345
        assert json.loads((tmp_path / case_id / "filter_snapshot.json").read_text(encoding="utf-8"))["retained_ids"] == reopened["retained_ids"]


@pytest.mark.parametrize("bad", ["count", "order", "duplicate", "bounds", "empty", "data_id", "duplicate_number", "data_number"])
def test_inconsistent_snapshot_is_rejected_without_partial_case(tmp_path, bad):
    value = snapshot()
    if bad == "count": value["stages"][0]["retained_count"] = 10
    if bad == "order": value["retained_ids"].reverse()
    if bad == "duplicate": value["candidates"][1]["id"] = "s-0"
    if bad == "bounds": value["stages"][0]["lower"] = 100
    if bad == "empty": value.update(stages=[], candidates=[], retained_ids=[])
    if bad == "data_id": value["candidates"][0]["data"]["id"] = "other"
    if bad == "duplicate_number": value["candidates"][1]["original_number"] = 1
    if bad == "data_number": value["candidates"][0]["data"]["number"] = 99
    with TestClient(create_app("sqlite://:memory:", "", experiment_root=tmp_path)) as client:
        response = client.post("/api/v1/filter-cases", json={"name": "invalid", "snapshot": value})
        assert response.status_code == 422
    assert not list(tmp_path.glob("saved-*"))
