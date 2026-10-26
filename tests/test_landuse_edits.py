from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from experiments.landuse_edits import (
    clear_landuse_edits,
    create_landuse_edit,
    delete_landuse_edit,
    list_landuse_edits,
    update_landuse_edit,
)


def _scene(directory: Path) -> np.ndarray:
    directory.mkdir(parents=True)
    landuse = np.zeros((8, 9), dtype=np.uint8)
    landuse[2:6, 2:6] = 4
    np.save(directory / "landuse_1m.npy", landuse)
    np.save(directory / "obstacle_mask_1m.npy", np.zeros_like(landuse))
    return landuse


def test_listing_landuse_edits_waits_for_another_scene_snapshot_reader(tmp_path):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    from experiments.scene_lock import scene_write_lock

    root = tmp_path / "scenes"
    _scene(root / "demo")
    entered = Event()
    def read():
        entered.set()
        return list_landuse_edits("demo", root)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with scene_write_lock("demo", root):
            pending = executor.submit(read)
            assert entered.wait(2)
            with pytest.raises(TimeoutError):
                pending.result(timeout=.05)
        assert pending.result(timeout=2) == []


def test_landuse_edits_rebuild_scene_products_without_mutating_linked_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    original = _scene(source)
    scene = tmp_path / "scenes" / "demo"
    scene.mkdir(parents=True)
    (scene / "landuse_1m.npy").hardlink_to(source / "landuse_1m.npy")
    np.save(scene / "obstacle_mask_1m.npy", np.zeros_like(original))

    points = [(2, 2), (6, 2), (6, 6), (2, 6)]
    items = create_landuse_edit("demo", 5, points, tmp_path / "scenes")

    assert len(items) == 1
    assert np.all(np.load(scene / "landuse_1m.npy")[2:6, 2:6] == 5)
    assert np.all(np.load(source / "landuse_1m.npy") == original)
    assert np.all(np.load(scene / "obstacle_mask_1m.npy")[2:6, 2:6] == 1)
    assert (scene / "landuse_water.png").is_file()
    assert list_landuse_edits("demo", tmp_path / "scenes") == items

    assert delete_landuse_edit("demo", items[0]["id"], tmp_path / "scenes") == []
    assert np.array_equal(np.load(scene / "landuse_1m.npy"), original)
    assert np.all(np.load(scene / "obstacle_mask_1m.npy") == 0)

    create_landuse_edit("demo", 2, points, tmp_path / "scenes")
    assert clear_landuse_edits("demo", tmp_path / "scenes") == []
    assert np.array_equal(np.load(scene / "landuse_1m.npy"), original)
    assert np.all(np.load(scene / "obstacle_mask_1m.npy") == 0)
    assert not (scene / "landuse_base_1m.npy").exists()
    assert not (scene / "landuse_edits.json").exists()


def test_road_edit_marks_the_cells_unbuildable(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    create_landuse_edit("demo", 3, [(2, 2), (6, 2), (6, 6), (2, 6)], tmp_path / "scenes")
    assert np.all(np.load(directory / "landuse_1m.npy")[2:6, 2:6] == 3)
    assert np.all(np.load(directory / "obstacle_mask_1m.npy")[2:6, 2:6] == 1)
    assert (directory / "landuse_road.png").is_file()


def test_later_landuse_edits_override_earlier_edits_and_vertex_updates_persist(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    first = create_landuse_edit("demo", 1, [(1, 1), (7, 1), (7, 7), (1, 7)], tmp_path / "scenes")
    second = create_landuse_edit("demo", 2, [(3, 3), (5, 3), (5, 5), (3, 5)], tmp_path / "scenes")

    landuse = np.load(directory / "landuse_1m.npy")
    assert np.all(landuse[1:3, 1:7] == 1)
    assert np.all(landuse[5:7, 1:7] == 1)
    assert np.all(landuse[3:5, 1:3] == 1)
    assert np.all(landuse[3:5, 5:7] == 1)
    assert np.all(landuse[3:5, 3:5] == 2)

    points = [(3, 3), (5, 3), (5, 5)]
    updated = update_landuse_edit("demo", second[1]["id"], points, tmp_path / "scenes")
    assert updated[1]["points"] == [[3, 3], [5, 3], [5, 5]]
    # The new triangle leaves the lower-left cell, which returns to the earlier field edit.
    assert np.array_equal(np.load(directory / "landuse_1m.npy")[3:5, 3:5], np.array([[2, 2], [1, 2]]))
    assert updated[0]["id"] == first[0]["id"]


@pytest.mark.parametrize(
    ("class_id", "points", "message"),
    [
        (4, [(1, 1), (4, 1), (4, 4)], "class_id"),
        (5, [(-1, 1), (4, 1), (4, 4)], "outside"),
        (1, [(1, 1), (2, 2), (3, 3)], "area"),
    ],
)
def test_invalid_landuse_edits_are_rejected(
    tmp_path: Path,
    class_id: int,
    points: list[tuple[float, float]],
    message: str,
) -> None:
    _scene(tmp_path / "scenes" / "demo")
    with pytest.raises(ValueError, match=message):
        create_landuse_edit("demo", class_id, points, tmp_path / "scenes")


def test_landuse_edit_api_persists_and_rejects_unknown_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _scene(tmp_path / "scenes" / "demo")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    client = TestClient(create_app("sqlite://:memory:", ""))

    created = client.post("/api/v1/scenes/demo/landuse-edits", json={
        "class_id": 1,
        "points": [[1, 1], [6, 1], [6, 6], [1, 6]],
    })
    assert created.status_code == 200
    edit_id = created.json()["items"][0]["id"]
    listed = client.get("/api/v1/scenes/demo/landuse-edits")
    assert listed.json()["items"][0]["id"] == edit_id
    assert listed.headers["cache-control"] == "no-store"
    assert client.put(
        f"/api/v1/scenes/demo/landuse-edits/{edit_id}",
        json={"points": [[1, 1], [5, 1], [5, 5]]},
    ).status_code == 200
    cleared = client.delete("/api/v1/scenes/demo/landuse-edits")
    assert cleared.json()["items"] == []
    assert np.array_equal(np.load(tmp_path / "scenes" / "demo" / "landuse_1m.npy"), baseline)
    assert client.get("/api/v1/scenes/demo/landuse-edits").json()["items"] == []
    assert not (tmp_path / "scenes" / "demo" / "landuse_base_1m.npy").exists()
    assert not (tmp_path / "scenes" / "demo" / "landuse_edits.json").exists()
    assert client.delete(f"/api/v1/scenes/demo/landuse-edits/{edit_id}").status_code == 404
    assert client.delete("/api/v1/scenes/demo/landuse-edits/missing").status_code == 404


def test_pose_feasibility_follows_landuse_edit_and_deletion(tmp_path, monkeypatch):
    from dataclasses import replace
    from config.project_config import load_default_config
    import experiments.launch_site_run as launch

    scene = tmp_path / "scenes" / "demo"
    _scene(scene)
    arrays = {
        "dem_1m": np.zeros((8, 9), dtype=np.float64),
        "road_segments_local": np.array([[.5, .5, 8.5, .5]]),
        "road_segment_kind": np.zeros(1, dtype=np.int8),
        "road_voronoi_1m": np.zeros((8, 9), dtype=np.int64),
        "demand_points": np.array([[4., 4.]], dtype=np.float32),
    }
    for name, value in arrays.items():
        np.save(scene / f"{name}.npy", value)
    (scene / "data_metadata.json").write_text("{}")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    config = load_default_config()
    config = replace(config, modeling=replace(config.modeling, device="cpu"))
    monkeypatch.setattr(launch, "load_project_config", lambda _path: config)
    launch._scored_scene.cache_clear()
    client = TestClient(create_app("sqlite://:memory:", ""))
    path = "/api/v1/scenes/demo"
    body = {"rect_w_m": 4, "rect_h_m": 3, "road_setback_m": 0, "water_setback_m": 0,
            "mountain_policy": "allowed", "field_policy": "allowed", "field_cost": .5,
            "exclusion_zones": [], "feasible_zones": [], "include_demand": False,
            "poses": [{"x": 4, "y": 4, "theta": 0}]}

    def evaluate():
        response = client.post(f"{path}/pose-objectives", json=body)
        assert response.status_code == 200, response.text
        return response.json()["items"][0]

    try:
        assert evaluate()["is_feasible"] is True
        created = client.post(f"{path}/landuse-edits", json={
            "class_id": 2, "points": [[2, 2], [6, 2], [6, 6], [2, 6]],
        })
        assert created.status_code == 200, created.text
        blocked = evaluate()
        assert blocked["is_feasible"] is False and blocked["obstacle_hard_count"] > 0
        edit_id = created.json()["items"][0]["id"]
        assert client.delete(f"{path}/landuse-edits/{edit_id}").status_code == 200
        assert evaluate()["is_feasible"] is True
    finally:
        launch._scored_scene.cache_clear()
