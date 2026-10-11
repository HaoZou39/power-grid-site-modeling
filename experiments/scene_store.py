"""Prepared site scenes. Optimization reads these files and does not rebuild them."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

from data_tools.io_utils import write_json
from experiments.problem_context import context_from_arrays

Progress = Callable[[float, str, str], None]

SCENE_ARRAYS = (
    "dem_1m.npy",
    "obstacle_mask_1m.npy",
    "road_segments_local.npy",
    "road_voronoi_1m.npy",
    "demand_points.npy",
)
SCENE_METADATA = "data_metadata.json"
OBSTACLE_OVERLAY = "obstacle_overlay.png"
DEFAULT_SCENE = "cangnan"
SCENE_TITLES = {DEFAULT_SCENE: "苍南 1800 m"}


def scenes_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(os.environ.get("SCENE_ROOT", "scenes"))


def scene_directory(root: str | Path, scene_name: str) -> Path:
    """Resolve one scene directory and refuse path escape."""

    name = scene_name.strip()
    if not name or name in {".", ".."} or any(separator in name for separator in ("/", "\\")):
        raise ValueError("scene_name must be a single directory name")
    base = scenes_root(root).expanduser().resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise ValueError("scene_name must stay inside the scene root")
    return path


def scene_title(scene_name: str) -> str:
    return SCENE_TITLES.get(scene_name, scene_name)


def missing_scene_files(path: Path) -> list[str]:
    names = (*SCENE_ARRAYS, SCENE_METADATA)
    return [name for name in names if not (path / name).is_file()]


def load_scene(scene_name: str, device: Any, root: str | Path | None = None):
    """Load one finished scene onto the requested device."""

    path = scene_directory(scenes_root(root), scene_name)
    missing = missing_scene_files(path)
    if missing:
        missing_text = ", ".join(missing)
        raise FileNotFoundError(
            f"场景 {scene_name} 还没有完成数据构建，缺少 {missing_text}。请先构建场景数据，再开始优化。"
        )
    arrays = {
        "dem": np.load(path / "dem_1m.npy"),
        "obstacle_mask": np.load(path / "obstacle_mask_1m.npy"),
        "road_segments": np.load(path / "road_segments_local.npy"),
        "road_voronoi": np.load(path / "road_voronoi_1m.npy"),
        "demand_points": np.load(path / "demand_points.npy"),
    }
    metadata = _read_json(path / SCENE_METADATA)
    metadata = {**metadata, "scene_id": path.name, "scene_dir": str(path)}
    return context_from_arrays(arrays, device), metadata


def prepare_scene(
    scene_name: str,
    reporter: Progress,
    config_path: str | Path = "config/default_config.json",
    root: str | Path | None = None,
) -> Path:
    """Build one scene from the raw inputs. Call this only from the data stage."""

    from config.project_config import load_project_config
    from experiments.problem_context import write_scene_products

    path = scene_directory(scenes_root(root), scene_name)
    path.mkdir(parents=True, exist_ok=True)
    reporter(0.1, "scene", "正在构建场景数据。这一步不运行优化。")

    def on_step(message: str) -> None:
        reporter(0.4, "scene", message)

    _, metadata = write_scene_products(load_project_config(config_path), path, on_step)
    write_json(path / SCENE_METADATA, metadata)
    write_json(path / "scene.json", {"id": path.name, "title": scene_title(path.name)})
    write_obstacle_overlay(path)
    reporter(1.0, "completed", "场景数据已写入")
    return path


def adopt_scene(source: str | Path, scene_name: str, root: str | Path | None = None) -> Path:
    """Point a scene at arrays that were already built, without copying the grids."""

    origin = Path(source).expanduser().resolve()
    path = scene_directory(scenes_root(root), scene_name)
    path.mkdir(parents=True, exist_ok=True)
    for name in (*SCENE_ARRAYS, SCENE_METADATA):
        src = origin / name
        if not src.is_file():
            raise FileNotFoundError(src)
        dest = path / name
        if dest.exists():
            continue
        os.link(src, dest)
    landuse_src = origin / "landuse_1m.npy"
    if landuse_src.is_file() and not (path / "landuse_1m.npy").exists():
        os.link(landuse_src, path / "landuse_1m.npy")
    write_json(path / "scene.json", {"id": path.name, "title": scene_title(path.name)})
    write_obstacle_overlay(path)
    return path


def write_obstacle_overlay(scene_dir: Path) -> Path:
    """Paint land-use classes when the grid is present. Otherwise paint the binary mask red."""

    from PIL import Image

    landuse_path = scene_dir / "landuse_1m.npy"
    if landuse_path.is_file():
        return _write_class_overlays(scene_dir, np.load(landuse_path), Image)
    mask = np.load(scene_dir / "obstacle_mask_1m.npy")
    if mask.ndim != 2 or mask.size == 0:
        raise ValueError(f"obstacle mask must be a non-empty 2D array, got {mask.shape}")
    image = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)
    image[mask > 0] = (255, 70, 84, 130)
    out = scene_dir / OBSTACLE_OVERLAY
    Image.fromarray(image, mode="RGBA").save(out, format="PNG")
    return out


def _write_class_overlays(scene_dir: Path, landuse: np.ndarray, image_cls: Any) -> Path:
    from experiments.constraint_mask import CLASS_COLORS

    if landuse.ndim != 2 or landuse.size == 0:
        raise ValueError(f"landuse must be a non-empty 2D array, got {landuse.shape}")
    combined = np.zeros((landuse.shape[0], landuse.shape[1], 4), dtype=np.uint8)
    for name, (class_id, color) in CLASS_COLORS.items():
        layer = np.zeros_like(combined)
        layer[landuse == class_id] = color
        image_cls.fromarray(layer, mode="RGBA").save(scene_dir / f"landuse_{name}.png")
        combined = np.maximum(combined, layer)
    out = scene_dir / OBSTACLE_OVERLAY
    image_cls.fromarray(combined, mode="RGBA").save(out, format="PNG")
    return out


def landuse_overlay_path(scene_name: str, layer: str, root: str | Path | None = None) -> Path:
    from experiments.constraint_mask import CLASS_COLORS

    if layer not in CLASS_COLORS:
        raise ValueError(f"unknown landuse overlay {layer}")
    path = scene_directory(scenes_root(root), scene_name) / f"landuse_{layer}.png"
    if not path.is_file():
        raise FileNotFoundError(f"场景 {scene_name} 还没有 {layer} 用地图")
    return path


def obstacle_overlay_path(scene_name: str, root: str | Path | None = None) -> Path:
    path = scene_directory(scenes_root(root), scene_name) / OBSTACLE_OVERLAY
    if not path.is_file():
        raise FileNotFoundError(f"场景 {scene_name} 还没有不可建设区域图")
    return path


def list_scenes(root: str | Path | None = None) -> list[dict[str, Any]]:
    base = scenes_root(root)
    if not base.is_dir():
        return []
    scenes = []
    for path in sorted((item for item in base.iterdir() if item.is_dir()), key=lambda item: item.name):
        info = _read_json(path / "scene.json") if (path / "scene.json").is_file() else {}
        missing = missing_scene_files(path)
        scenes.append({
            "id": path.name,
            "title": str(info.get("title") or scene_title(path.name)),
            "ready": not missing,
            "missing": missing,
        })
    return scenes


def _read_json(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value
