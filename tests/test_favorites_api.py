from fastapi.testclient import TestClient

from backend.app.main import create_app


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
