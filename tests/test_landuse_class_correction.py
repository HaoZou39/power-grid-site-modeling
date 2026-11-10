"""Conditional class→other edits clear one current class inside the ring."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from experiments.constraint_mask import CLASS_COLORS
from experiments.landuse_edits import (
    CLASS_TO_OTHER,
    WATER_TO_OTHER,
    compose_landuse,
    landuse_edit_snapshot,
    replace_landuse_edits,
)
from experiments.scene_version import scene_data_version


def _scene(directory: Path, landuse: np.ndarray) -> np.ndarray:
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "landuse_1m.npy", landuse)
    np.save(directory / "obstacle_mask_1m.npy", np.isin(landuse, [1, 2, 3, 5]).astype(np.uint8))
    np.save(directory / "protected_farmland_mask_1m.npy", np.zeros(landuse.shape, dtype=bool))
    return landuse


def _mixed() -> np.ndarray:
    # Ring (0.5, 0.5)–(3.5, 2.5) covers rows 0–2 and columns 0–3. Column 4 and row 3 stay outside.
    grid = np.zeros((4, 5), dtype=np.uint8)
    grid[1, 0] = 1
    grid[1, 1] = 3
    grid[1, 2] = 2
    grid[1, 3] = 5
    grid[0, 0] = 4
    grid[1, 4] = 2
    grid[3, :] = 3
    return grid


def _square(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _clear(edit_id: str, target: int, points: list[tuple[float, float]] | None = None) -> dict:
    return {
        "id": edit_id,
        "operation": CLASS_TO_OTHER,
        "target_class_id": target,
        "points": points or _square(0.5, 0.5, 3.5, 2.5),
    }


def _paint(edit_id: str, class_id: int, points: list[tuple[float, float]]) -> dict:
    return {"id": edit_id, "class_id": class_id, "points": points}


@pytest.mark.parametrize("target,cleared", [(2, (1, 2)), (1, (1, 0)), (3, (1, 1)), (5, (1, 3))])
def test_compose_clears_only_the_named_class(target: int, cleared: tuple[int, int]) -> None:
    base = _mixed()
    original = base.copy()
    result = compose_landuse(base, [_clear("fix", target)])
    expected = base.copy()
    expected[cleared] = 0
    assert np.array_equal(result, expected)
    assert result[1, 4] == 2
    assert result[3, 0] == 3
    assert result[0, 0] == 4
    assert np.array_equal(base, original)


def test_old_water_to_other_still_clears_only_water() -> None:
    base = _mixed()
    result = compose_landuse(base, [{
        "id": "old",
        "operation": WATER_TO_OTHER,
        "points": _square(0.5, 0.5, 3.5, 2.5),
    }])
    assert result[1, 3] == 0
    assert result[1, 0] == 1
    assert result[1, 1] == 3
    assert result[1, 2] == 2


def test_paint_and_correction_follow_list_order() -> None:
    base = np.zeros((8, 8), dtype=np.uint8)
    building = _paint("building", 2, _square(1, 1, 6, 6))
    clear = _clear("clear", 2, _square(2, 2, 5, 5))
    field = _paint("field", 1, _square(3, 3, 4.5, 4.5))
    result = compose_landuse(base, [building, clear, field])
    assert result[1, 1] == 2
    assert result[2, 2] == 0
    assert result[3, 3] == 1
    with pytest.raises(ValueError, match="没有需要纠正的建筑"):
        compose_landuse(base, [clear, building])


def test_delete_correction_restores_the_class_under_it(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "restore"
    _scene(directory, np.zeros((8, 8), dtype=np.uint8))
    root = tmp_path / "scenes"
    revision = scene_data_version(directory)["scene_revision"]
    building = _paint("building", 2, _square(1, 1, 6, 6))
    clear = _clear("clear", 2, _square(2, 2, 5, 5))
    published = replace_landuse_edits("restore", revision, [building, clear], root)
    assert np.load(directory / "landuse_1m.npy")[3, 3] == 0
    restored = replace_landuse_edits("restore", published["scene_revision"], [building], root)
    assert np.load(directory / "landuse_1m.npy")[3, 3] == 2
    assert [item["id"] for item in restored["items"]] == ["building"]


def test_missing_target_class_rejects_without_publishing(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "empty"
    base = np.full((6, 6), 1, dtype=np.uint8)
    _scene(directory, base)
    before = (directory / "landuse_1m.npy").read_bytes()
    revision = scene_data_version(directory)["scene_revision"]
    with pytest.raises(ValueError, match="没有需要纠正的建筑"):
        replace_landuse_edits("empty", revision, [_clear("noop", 2, _square(1, 1, 4, 4))], tmp_path / "scenes")
    assert (directory / "landuse_1m.npy").read_bytes() == before
    assert not (directory / "landuse_edits.json").is_file()
    assert scene_data_version(directory)["scene_revision"] == revision


def test_publish_keeps_landuse_obstacle_and_png_aligned(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "aligned"
    _scene(directory, _mixed())
    revision = scene_data_version(directory)["scene_revision"]
    replace_landuse_edits("aligned", revision, [_clear("building", 2)], tmp_path / "scenes")
    landuse = np.load(directory / "landuse_1m.npy")
    obstacle = np.load(directory / "obstacle_mask_1m.npy")
    assert landuse[1, 2] == 0
    assert np.array_equal(obstacle, np.isin(landuse, [1, 2, 3, 5]).astype(np.uint8))
    for name, (class_id, _color) in CLASS_COLORS.items():
        index = np.asarray(Image.open(directory / f"landuse_{name}.png"))
        assert np.array_equal(index > 0, landuse == class_id)


def test_independent_constraints_stay_byte_for_byte(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "isolated"
    landuse = _mixed()
    _scene(directory, landuse)
    farmland = np.zeros(landuse.shape, dtype=bool)
    farmland[1, 0] = True
    farmland[1, 2] = True
    np.save(directory / "protected_farmland_mask_1m.npy", farmland)
    roads = np.array([[0.0, 0.0, 8.0, 3.0]], dtype=np.float32)
    kinds = np.array([1], dtype=np.uint8)
    voronoi = np.arange(landuse.size, dtype=np.float32).reshape(landuse.shape)
    dem = np.arange(landuse.size, dtype=np.float32).reshape(landuse.shape) + 12
    np.save(directory / "road_segments_local.npy", roads)
    np.save(directory / "road_segment_kind.npy", kinds)
    np.save(directory / "road_voronoi_1m.npy", voronoi)
    np.save(directory / "dem_1m.npy", dem)
    snapshots = {
        name: (directory / name).read_bytes()
        for name in (
            "protected_farmland_mask_1m.npy",
            "road_segments_local.npy",
            "road_segment_kind.npy",
            "road_voronoi_1m.npy",
            "dem_1m.npy",
        )
    }
    revision = scene_data_version(directory)["scene_revision"]
    replace_landuse_edits("isolated", revision, [_clear("field", 1), _clear("building", 2), _clear("road", 3)], tmp_path / "scenes")
    published = np.load(directory / "landuse_1m.npy")
    assert published[1, 0] == 0
    assert published[1, 2] == 0
    assert published[1, 1] == 0
    assert published[1, 3] == 5
    for name, payload in snapshots.items():
        assert (directory / name).read_bytes() == payload


def test_failed_batch_restores_the_published_scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "scenes" / "rollback"
    _scene(directory, _mixed())
    root = tmp_path / "scenes"
    revision = scene_data_version(directory)["scene_revision"]
    published = replace_landuse_edits("rollback", revision, [_paint("field", 1, _square(0, 0, 2, 2))], root)
    snapshots = {
        name: (directory / name).read_bytes()
        for name in ("landuse_1m.npy", "obstacle_mask_1m.npy", "landuse_edits.json", "data_metadata.json")
    }

    def fail_overlay(_scene_dir: Path) -> None:
        raise OSError("overlay failed")

    monkeypatch.setattr("experiments.landuse_edits.write_obstacle_overlay", fail_overlay)
    with pytest.raises(OSError, match="overlay failed"):
        replace_landuse_edits("rollback", published["scene_revision"], [_clear("building", 2)], root)
    for name, payload in snapshots.items():
        assert (directory / name).read_bytes() == payload
    assert scene_data_version(directory)["scene_revision"] == published["scene_revision"]
    assert np.load(directory / "landuse_1m.npy")[1, 2] == 2


def test_historical_water_file_and_batch_api_stay_compatible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "scenes" / "history"
    _scene(directory, _mixed())
    (directory / "landuse_edits.json").write_text(json.dumps({
        "version": 1,
        "items": [{
            "id": "pond",
            "operation": WATER_TO_OTHER,
            "points": [[0.5, 0.5], [3.5, 0.5], [3.5, 2.5], [0.5, 2.5]],
        }],
    }), encoding="utf-8")
    items, _revision = landuse_edit_snapshot("history", tmp_path / "scenes")
    assert items == [{
        "id": "pond",
        "operation": WATER_TO_OTHER,
        "points": [[0.5, 0.5], [3.5, 0.5], [3.5, 2.5], [0.5, 2.5]],
    }]
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    client = TestClient(create_app("sqlite://:memory:", ""))
    current = client.get("/api/v1/scenes/history/landuse-edits").json()
    assert current["items"][0]["operation"] == WATER_TO_OTHER
    assert "target_class_id" not in current["items"][0]
    response = client.post("/api/v1/scenes/history/landuse-edits/batch", json={
        "expected_scene_revision": current["scene_revision"],
        "items": [
            {"id": "pond", "operation": WATER_TO_OTHER, "points": _square(0.5, 0.5, 3.5, 2.5)},
            _clear("building", 2),
        ],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["operation"] == WATER_TO_OTHER
    assert body["items"][1]["operation"] == CLASS_TO_OTHER
    assert body["items"][1]["target_class_id"] == 2
    grid = np.load(directory / "landuse_1m.npy")
    assert grid[1, 3] == 0
    assert grid[1, 2] == 0
    assert grid[1, 0] == 1
    rejected = client.post("/api/v1/scenes/history/landuse-edits/batch", json={
        "expected_scene_revision": body["scene_revision"],
        "items": [{"id": "bad", "operation": CLASS_TO_OTHER, "target_class_id": 4, "points": _square(1, 1, 2, 2)}],
    })
    assert rejected.status_code == 422
    missing = client.post("/api/v1/scenes/history/landuse-edits/batch", json={
        "expected_scene_revision": body["scene_revision"],
        "items": [{"id": "bad", "operation": CLASS_TO_OTHER, "points": _square(1, 1, 2, 2)}],
    })
    assert missing.status_code == 422
    painted = client.post("/api/v1/scenes/history/landuse-edits", json={
        "class_id": 5,
        "points": _square(0, 0, 1.5, 1.5),
    })
    assert painted.status_code == 200
    assert painted.json()["items"][-1]["class_id"] == 5
    assert painted.json()["items"][0]["operation"] == WATER_TO_OTHER
