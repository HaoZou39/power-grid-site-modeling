from fastapi.testclient import TestClient

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
