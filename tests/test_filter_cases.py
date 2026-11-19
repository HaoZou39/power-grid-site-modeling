"""Decision snapshots must survive source cleanup and preserve the complete selection."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


def snapshot(problem_type="routing"):
    return {
        "schema_version": 1, "problem_type": problem_type, "scene_name": "scene-a",
        "source_experiment_id": "already-cleaned-auto-run", "scene_version": {"scene_revision": "v1"},
        "captured_at": "2026-11-19T04:00:00Z", "scope": {"display_mode": "all"},
        "context": {"frame": {"crs": "EPSG:32651"}},
        "candidates": [{"id": f"s-{i}", "original_number": i + 1,
                        "metrics": {"length": i + 0.123456789012345},
                        "geometry": {"points": [[i, i + 0.123456789012345]]},
                        "data": {"id": f"s-{i}", "original": i}} for i in range(75)],
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
        assert len(list(tmp_path.glob("filter-*"))) == 2
        assert json.loads((tmp_path / case_id / "filter_snapshot.json").read_text(encoding="utf-8"))["retained_ids"] == reopened["retained_ids"]


@pytest.mark.parametrize("bad", ["count", "order", "duplicate", "bounds", "empty"])
def test_inconsistent_snapshot_is_rejected_without_partial_case(tmp_path, bad):
    value = snapshot()
    if bad == "count": value["stages"][0]["retained_count"] = 10
    if bad == "order": value["retained_ids"].reverse()
    if bad == "duplicate": value["candidates"][1]["id"] = "s-0"
    if bad == "bounds": value["stages"][0]["lower"] = 100
    if bad == "empty": value.update(stages=[], candidates=[], retained_ids=[])
    with TestClient(create_app("sqlite://:memory:", "", experiment_root=tmp_path)) as client:
        response = client.post("/api/v1/filter-cases", json={"name": "invalid", "snapshot": value})
        assert response.status_code == 422
    assert not list(tmp_path.glob("filter-*"))
