from fastapi.testclient import TestClient
import time

from backend.app.main import create_app


def test_api_root_opens_the_frontend() -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "http://127.0.0.1:5176"


def test_api_exposes_health_and_plugins() -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    assert client.get("/api/v1/health").status_code == 200
    response = client.get("/api/v1/plugins")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "demo.algorithm"


def test_api_lists_default_scene_without_retired_preset_placeholders(monkeypatch) -> None:
    from experiments.scene_store import DEFAULT_SCENE
    frame = {
        "crs": "EPSG:32651",
        "transform": [1.0, 0.0, 100.0, 0.0, -1.0, 200.0],
        "width": 1800,
        "height": 1800,
    }
    monkeypatch.setattr("experiments.scene_store.source_scene_frame_info", lambda _name: frame)
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.get("/api/v1/scenes")
    assert response.status_code == 200
    scenes = {item["id"]: item for item in response.json()}
    assert set(scenes) == {DEFAULT_SCENE}
    assert scenes[DEFAULT_SCENE]["default"] is True
    assert scenes[DEFAULT_SCENE]["frame"]["crs"] == "EPSG:32651"
    assert scenes[DEFAULT_SCENE]["frame"]["width"] == 1800


def test_api_creates_job_and_returns_status() -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.post(
        "/api/v1/jobs",
        json={"plugin_id": "demo.algorithm", "config": {"values": [4, 6], "multiplier": 3}},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    status_response = client.get(f"/api/v1/jobs/{job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"


def test_api_rejects_unknown_plugin() -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.post("/api/v1/jobs", json={"plugin_id": "missing", "config": {}})
    assert response.status_code == 400


def test_dev_app_embeds_worker_without_redis() -> None:
    with TestClient(create_app("sqlite://:memory:", "")) as client:
        response = client.post(
            "/api/v1/jobs",
            json={"plugin_id": "demo.algorithm", "config": {"values": [2, 4]}},
        )
        job_id = response.json()["job_id"]
        for _ in range(20):
            current = client.get(f"/api/v1/jobs/{job_id}").json()
            if current["status"] == "succeeded":
                break
            time.sleep(0.02)
        assert current["status"] == "succeeded"
