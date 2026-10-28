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

from experiments.constraint_mask import BUILDING, FIELD, KNOWN_CLASSES, ROAD, WATER, rasterize_exclusions
from experiments.scene_lock import scene_write_lock
from experiments.scene_store import scene_directory, scenes_root, write_obstacle_overlay

EDIT_FILE = "landuse_edits.json"
BASE_FILE = "landuse_base_1m.npy"
EDITABLE_CLASSES = frozenset({FIELD, BUILDING, ROAD, WATER})
MAX_BATCH_ITEMS = 128
MAX_BATCH_VERTICES = 8000
_LOCK = threading.Lock()


class LanduseRevisionConflict(Exception):
    """A batch was built from a scene revision that is no longer current."""

    def __init__(self, scene_revision: str) -> None:
        super().__init__(scene_revision)
        self.scene_revision = scene_revision


def list_landuse_edits(scene_name: str, root: str | Path | None = None) -> list[dict[str, Any]]:
    items, _revision = landuse_edit_snapshot(scene_name, root)
    return items


def landuse_edit_snapshot(scene_name: str, root: str | Path | None = None) -> tuple[list[dict[str, Any]], str]:
    """Return the published edits and scene revision from one locked read."""

    directory = _directory(scene_name, root)
    with scene_write_lock(scene_name, directory.parent, blocking=True), _LOCK:
        _require_landuse(directory)
        from experiments.scene_version import scene_data_version

        return _read_edits(directory), scene_data_version(directory)["scene_revision"]


def replace_landuse_edits(
    scene_name: str,
    expected_scene_revision: str,
    items: list[dict[str, Any]],
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Replace the published edit list in one pass. Later items cover earlier ones."""

    directory = _directory(scene_name, root)
    with scene_write_lock(scene_name, directory.parent), _LOCK:
        _require_landuse(directory)
        from experiments.scene_version import scene_data_version

        # Reject a stale draft before any equality shortcut or file write.
        current_revision = scene_data_version(directory)["scene_revision"]
        if expected_scene_revision != current_revision:
            raise LanduseRevisionConflict(current_revision)
        current = _read_edits(directory)
        base = _load_base_array(directory)
        proposed = _normalize_batch(items, base.shape)
        if _same_edits(current, proposed):
            return {"items": current, "scene_revision": current_revision, "changed": False}
        base_path = directory / BASE_FILE
        created_base = False
        if not base_path.is_file():
            _atomic_save_array(base_path, base)
            created_base = True
        try:
            _apply(directory, base, proposed)
        except Exception:
            if created_base:
                base_path.unlink(missing_ok=True)
            raise
        revision = scene_data_version(directory)["scene_revision"]
        return {"items": proposed, "scene_revision": revision, "changed": True}


def create_landuse_edit(
    scene_name: str,
    class_id: int,
    points: list[tuple[float, float]],
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    directory = _directory(scene_name, root)
    with scene_write_lock(scene_name, directory.parent), _LOCK:
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
    with scene_write_lock(scene_name, directory.parent), _LOCK:
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
    with scene_write_lock(scene_name, directory.parent), _LOCK:
        _require_landuse(directory)
        edits = _read_edits(directory)
        index = _find_edit(edits, edit_id)
        base = _base_landuse(directory)
        del edits[index]
        _apply(directory, base, edits)
        return edits


def clear_landuse_edits(scene_name: str, root: str | Path | None = None) -> list[dict[str, Any]]:
    directory = _directory(scene_name, root)
    with scene_write_lock(scene_name, directory.parent), _LOCK:
        from experiments.scene_store import ensure_scene_writable
        ensure_scene_writable(directory)
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
    from experiments.scene_store import ensure_scene_writable
    ensure_scene_writable(directory)
    _require_landuse(directory)
    base_path = directory / BASE_FILE
    if not base_path.is_file():
        _atomic_save_array(base_path, np.load(directory / "landuse_1m.npy"))
    return _load_base_array(directory)


def _load_base_array(directory: Path) -> np.ndarray:
    from experiments.scene_store import ensure_scene_writable
    ensure_scene_writable(directory)
    _require_landuse(directory)
    base_path = directory / BASE_FILE
    base = np.load(base_path if base_path.is_file() else directory / "landuse_1m.npy")
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
        raise ValueError("class_id must be 1 (field), 2 (building), 3 (road), or 5 (water)")


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


def _same_edits(current: list[dict[str, Any]], proposed: list[dict[str, Any]]) -> bool:
    if len(current) != len(proposed):
        return False
    for left, right in zip(current, proposed):
        if left["id"] != right["id"] or left["class_id"] != right["class_id"] or left["points"] != right["points"]:
            return False
    return True


def _validate_id(edit_id: Any) -> None:
    if not isinstance(edit_id, str) or not edit_id or len(edit_id) > 64:
        raise ValueError("land-use edit id must be 1 to 64 characters")
    if any(character not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-" for character in edit_id):
        raise ValueError("land-use edit id contains an unsupported character")


def _normalize_batch(items: list[dict[str, Any]], shape: tuple[int, ...]) -> list[dict[str, Any]]:
    if len(items) > MAX_BATCH_ITEMS:
        raise ValueError(f"land-use batch is limited to {MAX_BATCH_ITEMS} polygons")
    seen: set[str] = set()
    vertices = 0
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each land-use batch item must be an object")
        edit_id = item.get("id")
        _validate_id(edit_id)
        if edit_id in seen:
            raise ValueError("land-use edit ids must be unique")
        seen.add(edit_id)
        class_id = item.get("class_id")
        _validate_class(class_id)
        points = item.get("points")
        if not isinstance(points, list):
            raise ValueError("land-use polygon needs at least three vertices")
        ring = _validate_ring(points, shape)
        vertices += len(ring)
        if vertices > MAX_BATCH_VERTICES:
            raise ValueError(f"land-use batch is limited to {MAX_BATCH_VERTICES} vertices")
        normalized.append({"id": edit_id, "class_id": class_id, "points": ring})
    return normalized


def _apply(directory: Path, base: np.ndarray, edits: list[dict[str, Any]]) -> None:
    effective = np.array(base, copy=True)
    for item in edits:
        _validate_class(item["class_id"])
        mask = rasterize_exclusions([item["points"]], effective.shape) > 0
        effective[mask] = item["class_id"]
    obstacle = np.isin(effective, np.array([FIELD, BUILDING, ROAD, WATER], dtype=np.int32)).astype(np.uint8)

    from experiments.constraint_mask import CLASS_COLORS
    from experiments.scene_store import OBSTACLE_OVERLAY, ensure_scene_writable
    from experiments.scene_version import write_scene_revision

    ensure_scene_writable(directory)
    targets = [
        directory / "landuse_1m.npy",
        directory / "obstacle_mask_1m.npy",
        *[directory / f"landuse_{name}.png" for name in CLASS_COLORS],
        directory / OBSTACLE_OVERLAY,
        directory / EDIT_FILE,
        directory / "data_metadata.json",
    ]
    # os.replace is atomic per file. Move each old file aside so a later failure can put that same inode back.
    backups: list[tuple[Path, Path | None]] = []
    try:
        _publish_array(targets[0], effective, backups)
        _publish_array(targets[1], obstacle, backups)
        for path in targets[2:-2]:
            backups.append((path, _move_aside(path)))
        write_obstacle_overlay(directory)
        backups.append((targets[-2], _move_aside(targets[-2])))
        _atomic_write_edits(targets[-2], edits)
        # The revision writer reads this file. Keep it in place and restore from a copy.
        backups.append((targets[-1], _copy_aside(targets[-1])))
        write_scene_revision(directory)
    except Exception:
        _restore_published_files(backups)
        raise
    _discard_backups(backups)


def _publish_array(path: Path, array: np.ndarray, backups: list[tuple[Path, Path | None]]) -> None:
    backups.append((path, _move_aside(path)))
    _atomic_save_array(path, array)


def _move_aside(path: Path) -> Path | None:
    if not path.is_file():
        return None
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".bak", dir=path.parent)
    os.close(descriptor)
    backup = Path(name)
    os.replace(path, backup)
    return backup


def _copy_aside(path: Path) -> Path | None:
    if not path.is_file():
        return None
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".bak", dir=path.parent)
    os.close(descriptor)
    backup = Path(name)
    backup.write_bytes(path.read_bytes())
    return backup


def _restore_published_files(backups: list[tuple[Path, Path | None]]) -> None:
    for path, backup in reversed(backups):
        if backup is None:
            path.unlink(missing_ok=True)
        elif backup.is_file():
            os.replace(backup, path)


def _discard_backups(backups: list[tuple[Path, Path | None]]) -> None:
    for _path, backup in backups:
        if backup is not None and backup.is_file():
            backup.unlink()


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
