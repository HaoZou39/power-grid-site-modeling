"""Conditional water→other corrections only change current water cells."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from experiments.landuse_edits import (
    WATER_TO_OTHER,
    compose_landuse,
    landuse_edit_snapshot,
    replace_landuse_edits,
)
from experiments.scene_version import scene_data_version


def _scene(directory: Path, landuse: np.ndarray | None = None) -> np.ndarray:
    directory.mkdir(parents=True, exist_ok=True)
    grid = landuse if landuse is not None else np.zeros((8, 9), dtype=np.uint8)
    np.save(directory / "landuse_1m.npy", grid)
    np.save(directory / "obstacle_mask_1m.npy", np.zeros(grid.shape, dtype=np.uint8))
    np.save(directory / "protected_farmland_mask_1m.npy", np.zeros(grid.shape, dtype=bool))
    return grid


def _paint(edit_id: str, class_id: int, points: list[tuple[float, float]]) -> dict:
    return {"id": edit_id, "class_id": class_id, "points": points}


def _clear(edit_id: str, points: list[tuple[float, float]]) -> dict:
    return {"id": edit_id, "operation": WATER_TO_OTHER, "points": points}


def _square(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_compose_clears_only_water_inside_the_ring() -> None:
    base = np.array([
        [1, 1, 5, 5, 2],
        [1, 5, 5, 3, 2],
        [4, 4, 5, 0, 0],
        [3, 3, 3, 3, 3],
    ], dtype=np.uint8)
    outside = base.copy()
    cleared = compose_landuse(base, [_clear("fix", _square(0.5, 0.5, 3.5, 2.5))])
    expected = base.copy()
    expected[0, 2] = 0
    expected[0, 3] = 0
    expected[1, 1] = 0
    expected[1, 2] = 0
    expected[2, 2] = 0
    assert np.array_equal(cleared, expected)
    assert cleared[0, 0] == 1
    assert cleared[0, 4] == 2
    assert cleared[1, 3] == 3
    assert cleared[3, 0] == 3
    assert np.array_equal(base, outside)


def test_compose_rejects_rings_without_current_water() -> None:
    base = np.full((6, 6), 1, dtype=np.uint8)
    with pytest.raises(ValueError, match="没有需要纠正的水体"):
        compose_landuse(base, [_clear("noop", _square(1, 1, 4, 4))])


def test_order_paint_then_clear_then_paint_again(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "order"
    base = np.full((8, 8), 1, dtype=np.uint8)
    _scene(directory, base)
    revision = scene_data_version(directory)["scene_revision"]
    water = _paint("water", 5, _square(1, 1, 6, 6))
    clear = _clear("clear", _square(2, 2, 5, 5))
    rebuild = _paint("rebuild", 5, _square(3, 3, 4.5, 4.5))
    first = replace_landuse_edits("order", revision, [water, clear], tmp_path / "scenes")
    landuse = np.load(directory / "landuse_1m.npy")
    assert landuse[1, 1] == 5
    assert landuse[3, 3] == 0
    assert landuse[0, 0] == 1
    second = replace_landuse_edits("order", first["scene_revision"], [water, clear, rebuild], tmp_path / "scenes")
    landuse = np.load(directory / "landuse_1m.npy")
    assert landuse[3, 3] == 5
    assert landuse[2, 2] == 0
    removed = replace_landuse_edits("order", second["scene_revision"], [water], tmp_path / "scenes")
    assert np.all(np.load(directory / "landuse_1m.npy")[1:6, 1:6] == 5)
    assert [item["id"] for item in removed["items"]] == ["water"]
    assert removed["items"][0]["class_id"] == 5


def test_delete_clear_restores_underlying_paint(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "restore"
    _scene(directory, np.zeros((7, 7), dtype=np.uint8))
    revision = scene_data_version(directory)["scene_revision"]
    field = _paint("field", 1, _square(1, 1, 5, 5))
    water = _paint("water", 5, _square(2, 2, 4, 4))
    clear = _clear("clear", _square(2, 2, 4, 4))
    published = replace_landuse_edits("restore", revision, [field, water, clear], tmp_path / "scenes")
    assert np.load(directory / "landuse_1m.npy")[3, 3] == 0
    without_clear = replace_landuse_edits("restore", published["scene_revision"], [field, water], tmp_path / "scenes")
    assert np.load(directory / "landuse_1m.npy")[3, 3] == 5
    with pytest.raises(ValueError, match="没有需要纠正的水体"):
        replace_landuse_edits("restore", without_clear["scene_revision"], [field, clear], tmp_path / "scenes")
    assert np.load(directory / "landuse_1m.npy")[3, 3] == 5


def test_class_zero_paint_is_rejected_and_old_json_loads(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "compat"
    _scene(directory)
    revision = scene_data_version(directory)["scene_revision"]
    with pytest.raises(ValueError, match="class_id"):
        replace_landuse_edits("compat", revision, [
            {"id": "zero", "class_id": 0, "points": _square(1, 1, 3, 3)},
        ], tmp_path / "scenes")
    (directory / "landuse_edits.json").write_text(json.dumps({
        "version": 1,
        "items": [{"id": "pond", "class_id": 5, "points": [[2, 2], [5, 2], [5, 5], [2, 5]]}],
    }), encoding="utf-8")
    items, _ = landuse_edit_snapshot("compat", tmp_path / "scenes")
    assert items == [{"id": "pond", "class_id": 5, "points": [[2.0, 2.0], [5.0, 2.0], [5.0, 5.0], [2.0, 5.0]]}]


def test_batch_http_accepts_mixed_paint_and_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "scenes" / "http"
    landuse = np.zeros((8, 8), dtype=np.uint8)
    landuse[2:6, 2:6] = 5
    landuse[2:4, 2:4] = 1
    _scene(directory, landuse)
    farmland = (directory / "protected_farmland_mask_1m.npy").read_bytes()
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    client = TestClient(create_app("sqlite://:memory:", ""))
    revision = client.get("/api/v1/scenes/http/landuse-edits").json()["scene_revision"]
    response = client.post("/api/v1/scenes/http/landuse-edits/batch", json={
        "expected_scene_revision": revision,
        "items": [
            _paint("field", 1, _square(1, 1, 3, 3)),
            _clear("clear", _square(2, 2, 6, 6)),
            _paint("road", 3, _square(5, 5, 7, 7)),
        ],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert any(item.get("operation") == WATER_TO_OTHER for item in body["items"])
    grid = np.load(directory / "landuse_1m.npy")
    obstacle = np.load(directory / "obstacle_mask_1m.npy")
    assert grid[2, 2] == 1
    assert grid[4, 4] == 0
    assert grid[5, 5] == 3
    assert obstacle[4, 4] == 0
    assert obstacle[5, 5] == 1
    assert (directory / "protected_farmland_mask_1m.npy").read_bytes() == farmland
    same = client.post("/api/v1/scenes/http/landuse-edits/batch", json={
        "expected_scene_revision": body["scene_revision"],
        "items": body["items"],
    })
    assert same.status_code == 200
    assert same.json()["changed"] is False
    rejected = client.post("/api/v1/scenes/http/landuse-edits/batch", json={
        "expected_scene_revision": body["scene_revision"],
        "items": [{"id": "zero", "class_id": 0, "points": [[1, 1], [2, 1], [2, 2]]}],
    })
    assert rejected.status_code == 422
