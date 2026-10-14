"""Persist scene-level land-use corrections and rebuild their raster products."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from experiments.constraint_mask import BUILDING, FIELD, KNOWN_CLASSES, WATER, rasterize_exclusions
from experiments.scene_store import scene_directory, scenes_root, write_obstacle_overlay

EDIT_FILE = "landuse_edits.json"
BASE_FILE = "landuse_base_1m.npy"
EDITABLE_CLASSES = frozenset({FIELD, BUILDING, WATER})
_LOCK = threading.Lock()


def list_landuse_edits(scene_name: str, root: str | Path | None = None) -> list[dict[str, Any]]:
    directory = _directory(scene_name, root)
    with _LOCK:
        _require_landuse(directory)
        return _read_edits(directory)


def create_landuse_edit(
    scene_name: str,
    class_id: int,
    points: list[tuple[float, float]],
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    directory = _directory(scene_name, root)
    with _LOCK:
        _validate_class(class_id)
        base = _base_landuse(directory)
        ring = _validate_ring(points, base.shape)
        edits = _read_edits(directory)
        edits.append({"id": uuid.uuid4().hex, "class_id": class_id, "points": ring})
        _apply(directory, base, edits)
        return edits


def update_landuse_edit(
    scene_name: str,
    edit_id: str,
    points: list[tuple[float, float]],
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    directory = _directory(scene_name, root)
    with _LOCK:
        _require_landuse(directory)
        edits = _read_edits(directory)
        index = _find_edit(edits, edit_id)
        base = _base_landuse(directory)
        edits[index]["points"] = _validate_ring(points, base.shape)
        _apply(directory, base, edits)
        return edits


def delete_landuse_edit(
    scene_name: str,
    edit_id: str,
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    directory = _directory(scene_name, root)
    with _LOCK:
        _require_landuse(directory)
        edits = _read_edits(directory)
        index = _find_edit(edits, edit_id)
        base = _base_landuse(directory)
        del edits[index]
        _apply(directory, base, edits)
        return edits


def clear_landuse_edits(scene_name: str, root: str | Path | None = None) -> list[dict[str, Any]]:
    directory = _directory(scene_name, root)
    with _LOCK:
        _require_landuse(directory)
        base_path = directory / BASE_FILE
        edits_path = directory / EDIT_FILE
        if not base_path.is_file():
            if edits_path.is_file():
                if _read_edits(directory):
                    raise ValueError(f"missing {BASE_FILE} in scene {directory.name}")
                edits_path.unlink()
            return []
        base = np.load(base_path)
        if base.ndim != 2 or base.size == 0:
            raise ValueError(f"landuse must be a non-empty 2D array, got {base.shape}")
        unknown = set(np.unique(base).astype(int).tolist()) - KNOWN_CLASSES
        if unknown:
            raise ValueError(f"unknown landuse class ids: {sorted(unknown)}")
        _apply(directory, np.array(base, copy=True), [])
        base_path.unlink()
        edits_path.unlink(missing_ok=True)
        return []


def reset_landuse_edits(scene_dir: Path) -> None:
    """Forget scene corrections after newly prepared land-use products replace the grid."""

    for name in (BASE_FILE, EDIT_FILE):
        try:
            (scene_dir / name).unlink()
        except FileNotFoundError:
            pass


def _directory(scene_name: str, root: str | Path | None) -> Path:
    return scene_directory(scenes_root(root), scene_name)


def _require_landuse(directory: Path) -> Path:
    path = directory / "landuse_1m.npy"
    if not path.is_file():
        raise FileNotFoundError(f"场景 {directory.name} 缺少 landuse_1m.npy")
    return path


def _base_landuse(directory: Path) -> np.ndarray:
    landuse_path = _require_landuse(directory)
    base_path = directory / BASE_FILE
    if base_path.is_file():
        base = np.load(base_path)
    else:
        base = np.load(landuse_path)
        _atomic_save_array(base_path, base)
    if base.ndim != 2 or base.size == 0:
        raise ValueError(f"landuse must be a non-empty 2D array, got {base.shape}")
    unknown = set(np.unique(base).astype(int).tolist()) - KNOWN_CLASSES
    if unknown:
        raise ValueError(f"unknown landuse class ids: {sorted(unknown)}")
    return np.array(base, copy=True)


def _read_edits(directory: Path) -> list[dict[str, Any]]:
    path = directory / EDIT_FILE
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError(f"invalid {EDIT_FILE} in scene {directory.name}")
    edits: list[dict[str, Any]] = []
    for item in data["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError(f"invalid land-use edit in scene {directory.name}")
        class_id = item.get("class_id")
        _validate_class(class_id)
        points = item.get("points")
        if not isinstance(points, list):
            raise ValueError(f"invalid land-use edit ring in scene {directory.name}")
        edits.append({
            "id": item["id"],
            "class_id": class_id,
            "points": [[float(point[0]), float(point[1])] for point in points],
        })
    return edits


def _validate_class(class_id: Any) -> None:
    if type(class_id) is not int or class_id not in EDITABLE_CLASSES:
        raise ValueError("class_id must be 1 (field), 2 (building), or 5 (water)")


def _validate_ring(points: list[tuple[float, float]], shape: tuple[int, ...]) -> list[list[float]]:
    if len(points) < 3:
        raise ValueError("land-use polygon needs at least three vertices")
    height, width = shape
    ring: list[tuple[float, float]] = []
    for point in points:
        if len(point) != 2:
            raise ValueError("each land-use vertex must contain x and y")
        x, y = float(point[0]), float(point[1])
        if not (np.isfinite(x) and np.isfinite(y)):
            raise ValueError("land-use vertices must be finite")
        if x < 0 or y < 0 or x > width or y > height:
            raise ValueError("land-use vertex is outside the site")
        ring.append((x, y))
    if len(set(ring)) < 3:
        raise ValueError("land-use polygon needs at least three distinct vertices")
    area2 = abs(sum(
        ring[index][0] * ring[(index + 1) % len(ring)][1]
        - ring[(index + 1) % len(ring)][0] * ring[index][1]
        for index in range(len(ring))
    ))
    if area2 == 0:
        raise ValueError("land-use polygon must enclose an area")
    if not np.any(rasterize_exclusions([ring], shape)):
        raise ValueError("land-use polygon does not cover any grid cells")
    return [[x, y] for x, y in ring]


def _find_edit(edits: list[dict[str, Any]], edit_id: str) -> int:
    for index, item in enumerate(edits):
        if item["id"] == edit_id:
            return index
    raise FileNotFoundError(f"land-use edit {edit_id} does not exist")


def _apply(directory: Path, base: np.ndarray, edits: list[dict[str, Any]]) -> None:
    effective = np.array(base, copy=True)
    for item in edits:
        _validate_class(item["class_id"])
        mask = rasterize_exclusions([item["points"]], effective.shape) > 0
        effective[mask] = item["class_id"]
    obstacle = np.isin(effective, np.array([FIELD, BUILDING, 3, WATER], dtype=np.int32)).astype(np.uint8)

    _atomic_save_array(directory / "landuse_1m.npy", effective)
    _atomic_save_array(directory / "obstacle_mask_1m.npy", obstacle)
    write_obstacle_overlay(directory)
    _atomic_write_edits(directory / EDIT_FILE, edits)


def _atomic_save_array(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".npy")
    os.close(descriptor)
    try:
        np.save(temporary, array)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_write_edits(path: Path, edits: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "items": edits}, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
