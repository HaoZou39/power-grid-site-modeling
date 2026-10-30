"""Deleting a scene removes its directory and favorites, keeps experiment outputs, rejects busy scenes."""

from fastapi.testclient import TestClient

from backend.app.main import create_app


def _scene(root, name, *files):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    for file_name in files:
        (directory / file_name).write_bytes(b"x")
    return directory


def _app(tmp_path):
    return create_app("sqlite://:memory:", "", favorite_db_path=tmp_path / "favorites.sqlite3")


def test_delete_scene_removes_directory_and_favorites_and_keeps_outputs(tmp_path, monkeypatch):
    scenes = tmp_path / "scenes"
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setenv("SCENE_ROOT", str(scenes))
    monkeypatch.setenv("EXPERIMENT_OUTPUT_ROOT", str(outputs))
    _scene(scenes, "doomed", "dem_1m.npy", "data_metadata.json")
    experiment = outputs / "site-1"
    experiment.mkdir()
    (experiment / "run_summary.json").write_text("{}", encoding="utf-8")

    with TestClient(_app(tmp_path)) as client:
        repository = client.app.state.favorite_point_repository
        repository.create("doomed", longitude=120.1, latitude=27.5, width_m=10, height_m=10, bearing_deg=0)
        repository.create("doomed", longitude=120.2, latitude=27.6, width_m=10, height_m=10, bearing_deg=0)
        assert len(repository.list_for_scene("doomed")) == 2

        response = client.delete("/api/v1/scenes/doomed")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deleted"] is True and body["favorites_removed"] == 2

        assert not (scenes / "doomed").exists()
        assert repository.list_for_scene("doomed") == []
        # 历史实验产物保留。
        assert (experiment / "run_summary.json").is_file()
        assert "doomed" not in [s["id"] for s in client.get("/api/v1/scenes").json()]


def test_delete_missing_scene_returns_404(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    with TestClient(_app(tmp_path)) as client:
        assert client.delete("/api/v1/scenes/ghost").status_code == 404


def test_delete_scene_rejected_while_a_job_is_active(tmp_path, monkeypatch):
    scenes = tmp_path / "scenes"
    _scene(scenes, "busy", "dem_1m.npy")
    monkeypatch.setenv("SCENE_ROOT", str(scenes))

    with TestClient(_app(tmp_path)) as client:
        repository = client.app.state.job_service.repository
        monkeypatch.setattr(type(repository), "active_scene_names", lambda self: {"busy"})
        monkeypatch.setattr(type(repository), "list_active_jobs", lambda self: [])
        response = client.delete("/api/v1/scenes/busy")
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "farmland_scene_busy"
    assert (scenes / "busy").is_dir()


def test_concurrent_delete_serializes_and_returns_missing_for_second_request(tmp_path, monkeypatch):
    import shutil
    import threading
    from concurrent.futures import ThreadPoolExecutor

    scenes = tmp_path / "scenes"
    directory = _scene(scenes, "shared", "dem_1m.npy")
    monkeypatch.setenv("SCENE_ROOT", str(scenes))
    entered = threading.Event()
    release = threading.Event()
    real_rmtree = shutil.rmtree

    def slow_delete(path, *args, **kwargs):
        if path == directory:
            entered.set()
            assert release.wait(5)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", slow_delete)
    with TestClient(_app(tmp_path), raise_server_exceptions=False) as client, ThreadPoolExecutor(2) as pool:
        first = pool.submit(client.delete, "/api/v1/scenes/shared")
        assert entered.wait(5)
        second = pool.submit(client.delete, "/api/v1/scenes/shared")
        try:
            # Both requests must reach the same API loop while the first deletion is blocked.
            assert client.get("/api/v1/health").status_code == 200
        finally:
            release.set()
        assert sorted([first.result(timeout=5).status_code, second.result(timeout=5).status_code]) == [200, 404]
