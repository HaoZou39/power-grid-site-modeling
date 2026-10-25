from fastapi.testclient import TestClient
import pytest

from backend.app.main import create_app


def test_generated_scene_favorites_support_crud_without_reading_arrays(tmp_path, monkeypatch):
    from experiments.scene_store import SCENE_ARRAYS, SCENE_METADATA
    import numpy as np

    root = tmp_path / "scenes"
    scene = root / "coordinate-generated-9000"
    scene.mkdir(parents=True)
    for name in (*SCENE_ARRAYS, SCENE_METADATA):
        (scene / name).touch()
    monkeypatch.setenv("SCENE_ROOT", str(root))
    def reject_array_load(*args, **kwargs):
        raise AssertionError("favorites must not load scene matrices")

    monkeypatch.setattr(np, "load", reject_array_load)
    client = TestClient(create_app("sqlite://:memory:", "", favorite_db_path=tmp_path / "favorites.sqlite3"))
    path = f"/api/v1/scenes/{scene.name}/favorites"
    payload = dict(longitude=120.194639, latitude=27.501662, width_m=77, height_m=51.5, bearing_deg=305.6)
    created = client.post(path, json=payload)
    assert created.status_code == 201
    saved = created.json()
    assert saved["scene_id"] == scene.name
    assert saved["bearing_deg"] == 305.6
    assert client.get(path).json() == [saved]
    updated = client.put(f"{path}/{saved['id']}", json={k: payload[k] for k in ("longitude", "latitude", "bearing_deg")})
    assert updated.status_code == 200
    assert client.delete(f"{path}/{saved['id']}").status_code == 204
    assert client.get(path).json() == []
    (scene / SCENE_METADATA).unlink()
    assert client.post(path, json=payload).status_code == 404


def test_favorite_scene_validation_rejects_path_escape(tmp_path, monkeypatch):
    import pytest
    from fastapi import HTTPException
    from backend.app.api.favorites_routes import _validate_scene

    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    for scene in ("../outside", "..", "nested/scene", "nested\\scene"):
        with pytest.raises(HTTPException) as error:
            _validate_scene(scene)
        assert error.value.status_code == 404


def test_favorites_are_persistent_and_isolated_by_scene(tmp_path):
    database = tmp_path / "user-state" / "favorites.sqlite3"
    client = TestClient(create_app("sqlite://:memory:", "", favorite_db_path=database))
    payload = {
        "longitude": 120.194639,
        "latitude": 27.501662,
        "width_m": 77,
        "height_m": 51.5,
        "bearing_deg": 0,
    }

    created = client.post("/api/v1/scenes/cangnan/favorites", json=payload)
    assert created.status_code == 201
    favorite = created.json()
    assert favorite["bearing_deg"] == 0
    assert client.get("/api/v1/scenes/cangnan/favorites").json() == [favorite]
    assert client.get("/api/v1/scenes/yongjia/favorites").json() == []

    reopened = TestClient(
        create_app("sqlite://:memory:", "", favorite_db_path=database)
    )
    assert reopened.get("/api/v1/scenes/cangnan/favorites").json() == [favorite]

    updated = reopened.put(
        f"/api/v1/scenes/cangnan/favorites/{favorite['id']}",
        json={
            "longitude": 120.1947,
            "latitude": 27.5017,
            "bearing_deg": 45,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["width_m"] == 77
    assert updated.json()["bearing_deg"] == 45
    deleted = reopened.delete(
        f"/api/v1/scenes/cangnan/favorites/{favorite['id']}"
    )
    assert deleted.status_code == 204
    assert reopened.get("/api/v1/scenes/cangnan/favorites").json() == []


def test_favorites_validate_scene_and_coordinates(tmp_path):
    client = TestClient(
        create_app(
            "sqlite://:memory:",
            "",
            favorite_db_path=tmp_path / "favorites.sqlite3",
        )
    )
    payload = {
        "longitude": 120.194639,
        "latitude": 27.501662,
        "width_m": 77,
        "height_m": 51.5,
        "bearing_deg": 0,
    }

    assert client.get("/api/v1/scenes/not-a-scene/favorites").status_code == 404
    assert client.post(
        "/api/v1/scenes/cangnan/favorites",
        json={**payload, "longitude": 181},
    ).status_code == 422
    assert client.post(
        "/api/v1/scenes/cangnan/favorites",
        json={**payload, "bearing_deg": 360},
    ).status_code == 422


def test_favorite_updates_and_deletes_are_scene_scoped(tmp_path):
    client = TestClient(
        create_app(
            "sqlite://:memory:",
            "",
            favorite_db_path=tmp_path / "favorites.sqlite3",
        )
    )
    created = client.post(
        "/api/v1/scenes/cangnan/favorites",
        json={
            "longitude": 120.194639,
            "latitude": 27.501662,
            "width_m": 77,
            "height_m": 51.5,
            "bearing_deg": 0,
        },
    ).json()
    favorite_id = created["id"]
    update = {
        "longitude": 120.194639,
        "latitude": 27.501662,
        "bearing_deg": 10,
    }

    assert client.put(
        f"/api/v1/scenes/yongjia/favorites/{favorite_id}", json=update
    ).status_code == 404
    assert client.delete(
        f"/api/v1/scenes/yongjia/favorites/{favorite_id}"
    ).status_code == 404
    assert client.put(
        f"/api/v1/scenes/cangnan/favorites/{favorite_id}", json=update
    ).status_code == 200


@pytest.mark.parametrize("configured", [None, "custom-user-state/favorites.sqlite3"])
def test_default_database_path_does_not_follow_the_working_directory(tmp_path, monkeypatch, configured):
    from pathlib import Path
    import backend.app.main as main

    if configured is None:
        monkeypatch.delenv("FAVORITES_DB_PATH", raising=False)
    else:
        monkeypatch.setenv("FAVORITES_DB_PATH", configured)
    monkeypatch.setattr(main, "FavoritePointRepository", lambda path: Path(path))
    expected = Path(main.__file__).resolve().parents[2] / (configured or "outputs/user-state/favorites.sqlite3")
    first = create_app("sqlite://:memory:", "").state.favorite_point_repository
    monkeypatch.chdir(tmp_path)
    reopened = create_app("sqlite://:memory:", "").state.favorite_point_repository
    assert first == reopened == expected


def test_both_favorite_entries_use_search_objectives_without_running_a_search(tmp_path, monkeypatch):
    import json
    import math
    from dataclasses import replace

    import numpy as np
    import torch

    from algorithms.cma_es.cma_es import evaluate_pose_batch
    from config.project_config import load_default_config
    import experiments.launch_site_run as launch
    from modeling.context import building_hard_mask
    from modeling.evaluator import compute_hard_constraints

    scene = tmp_path / "scenes" / "favorites-test"
    scene.mkdir(parents=True)
    yy, xx = np.mgrid[:32, :32]
    arrays = {
        "dem_1m": (0.2 * yy + 0.03 * xx).astype(np.float64),
        "landuse_1m": np.zeros((32, 32), dtype=np.uint8),
        "obstacle_mask_1m": np.zeros((32, 32), dtype=np.float32),
        "road_segments_local": np.array([[0.0, 4.5, 31.0, 4.5]], dtype=np.float64),
        "road_segment_kind": np.zeros(1, np.int8),
        "road_voronoi_1m": np.zeros((32, 32), dtype=np.int64),
        "demand_points": np.array([[8.0, 16.0], [24.0, 20.0]], dtype=np.float32),
    }
    for name, array in arrays.items():
        np.save(scene / f"{name}.npy", array)
    (scene / "data_metadata.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    project = load_default_config()
    project = replace(project, modeling=replace(project.modeling, device="cpu", rect_w_m=4, rect_h_m=3))
    monkeypatch.setattr(launch, "load_project_config", lambda _path: project)
    launch._scored_scene.cache_clear()
    body = {
        "rect_w_m": 4, "rect_h_m": 3, "mountain_policy": "allowed", "field_policy": "allowed", "field_cost": 0.5,
        "exclusion_zones": [], "feasible_zones": [{"points": [[1, 1], [18, 1], [18, 31], [1, 31]]}],
        "include_demand": True, "diagonal_access": True, "road_setback_m": 0, "water_setback_m": 0,
    }
    poses = np.array([[12.0, 20.0, -math.pi / 2], [24.0, 20.0, 0.73]])
    client = TestClient(create_app("sqlite://:memory:", "", favorite_db_path=tmp_path / "favorites.sqlite3"))
    path = f"/api/v1/scenes/{scene.name}"
    for x, y, theta in poses:
        saved = client.post(f"{path}/favorites", json={
            "longitude": 120 + x / 100000, "latitude": 27 - y / 100000,
            "width_m": 4, "height_m": 3, "bearing_deg": (theta * 180 / math.pi + 90) % 360,
        })
        assert saved.status_code == 201
    assert len(client.get(f"{path}/favorites").json()) == 2
    response = client.post(f"{path}/pose-objectives", json={
        **body, "poses": [dict(x=float(x), y=float(y), theta=float(theta)) for x, y, theta in poses],
    })
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    problem, _metadata = launch.constrained_problem({**body, "scene_name": scene.name}, torch.device("cpu"))
    _, expected = evaluate_pose_batch(problem, project.modeling, poses)
    hard = compute_hard_constraints(problem.dem, building_hard_mask(problem), torch.tensor(poses, dtype=torch.float32), 4, 3, "cpu")
    for index, row in enumerate(rows):
        for key in ("dem_soft", "obstacle_soft", "road_distance", "demand_distance"):
            assert row[key] == pytest.approx(float(expected[key][index]), rel=1e-6, abs=1e-6)
        assert row["obstacle_hard_count"] == float(hard["obstacle_hard_count"][index])
    assert rows[1]["is_feasible"] is False, "an out-of-optimization-region favorite is saved and evaluated as infeasible"
    # The same scorer produces the algorithm's exported solution rows.
    expected_rows = launch.evaluate_form_poses({**body, "scene_name": scene.name}, poses.tolist())
    assert json.dumps(rows, sort_keys=True) == json.dumps(expected_rows, sort_keys=True)
    launch._scored_scene.cache_clear()
