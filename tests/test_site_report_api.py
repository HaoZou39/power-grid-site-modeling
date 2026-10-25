import numpy as np
from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_site_report_uses_complete_constraint_set_and_preserves_legacy_mode(tmp_path, monkeypatch) -> None:
    scene = tmp_path / "case"
    scene.mkdir()
    shape = (12, 12)
    np.save(scene / "dem_1m.npy", np.zeros(shape, dtype=np.float32))
    static_mask = np.zeros(shape, dtype=np.float32)
    static_mask[6, 6] = 1
    np.save(scene / "obstacle_mask_1m.npy", static_mask)
    landuse = np.zeros(shape, dtype=np.int32)
    landuse[6, 6] = 1
    np.save(scene / "landuse_1m.npy", landuse)
    np.save(scene / "road_segments_local.npy", np.array([[0.5, 0.5, 11.5, 0.5]], dtype=np.float32))
    np.save(scene / "road_segment_kind.npy", np.zeros(len(np.load(scene / "road_segments_local.npy")), np.int8))
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path))
    client = TestClient(create_app("sqlite://:memory:", ""))
    pose = {"x": 6.5, "y": 6.5, "theta": 0, "rect_w_m": 2, "rect_h_m": 2}

    legacy = client.post("/api/v1/scenes/case/site-report", json=pose)
    assert legacy.status_code == 422
    assert legacy.json()["detail"]["message"] == "site cell is not buildable"

    current = client.post(
        "/api/v1/scenes/case/site-report",
        json={
            **pose,
            "mountain_policy": "allowed",
            "field_policy": "allowed",
            "field_cost": 0.5,
            "exclusion_zones": [],
            "feasible_zones": [],
        },
    )
    assert current.status_code == 200
    assert current.json()["offroad_haul_m"] >= 0
    diagonal = client.post(
        "/api/v1/scenes/case/site-report",
        json={
            **pose,
            "mountain_policy": "allowed",
            "field_policy": "allowed",
            "field_cost": 0.5,
            "exclusion_zones": [],
            "feasible_zones": [],
            "diagonal_access": True,
        },
    )
    assert diagonal.status_code == 200
    assert diagonal.json()["offroad_haul_m"] >= 0


def test_site_report_rejects_partial_constraint_set() -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.post(
        "/api/v1/scenes/missing/site-report",
        json={"x": 1, "y": 1, "field_policy": "allowed"},
    )
    assert response.status_code == 422
    assert "constraint fields must be supplied together" in str(response.json())


def test_site_report_rejects_unknown_policy_value() -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.post(
        "/api/v1/scenes/missing/site-report",
        json={
            "x": 1,
            "y": 1,
            "mountain_policy": "allowed",
            "field_policy": "sometimes",
            "field_cost": 0.5,
            "exclusion_zones": [],
            "feasible_zones": [],
        },
    )
    assert response.status_code == 422
