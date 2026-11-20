"""Published scene paths, readable products and coordinate identity."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np


SCENE_ARRAYS = (
    "dem_1m.npy",
    "landuse_1m.npy",
    "obstacle_mask_1m.npy",
    "road_segments_local.npy",
    "road_segment_kind.npy",
    "road_voronoi_1m.npy",
    "demand_points.npy",
)
SCENE_METADATA = "data_metadata.json"


ROAD_REBUILD_MARKER = ".roads-rebuilding"
ROAD_PRODUCT_FILES = (
    "road_segments_local.npy",
    "road_segment_kind.npy",
    "road_segments_local.json",
    "road_voronoi_1m.npy",
    "road_voronoi_1m.json",
    SCENE_METADATA,
)


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


def missing_scene_files(path: Path) -> list[str]:
    names = (*SCENE_ARRAYS, SCENE_METADATA)
    return [name for name in names if not (path / name).is_file()]


def ensure_scene_readable(path: str | Path) -> None:
    marker = Path(path) / ROAD_REBUILD_MARKER
    if marker.exists():
        raise RuntimeError(f"场景道路数据正在安全切换或等待恢复，请检查保护标记：{marker}")


def ensure_scene_writable(path: Path) -> None:
    record = path / "scene.json"
    if record.is_file() and read_scene_json(record).get("read_only"):
        raise ValueError(f"历史场景 {path.name} 已封存，只能查看；请切换到新的 UTM 场景")


def scene_frame_info(scene_dir: Path) -> dict[str, Any] | None:
    """A scene-specific reference grid for the map, not the fixed Cangnan frame."""
    metadata_path = scene_dir / SCENE_METADATA
    if not metadata_path.is_file():
        return None
    metadata = read_scene_json(metadata_path)
    dem = metadata.get("dem") or {}
    transform = dem.get("target_transform")
    shape = dem.get("shape")
    crs = dem.get("reference_crs")
    if (
        not isinstance(crs, str)
        or not isinstance(transform, list) or len(transform) != 6
        or not isinstance(shape, list) or len(shape) != 2
    ):
        return None
    transform = [float(value) for value in transform]
    height, width = [int(value) for value in shape]
    if not all(np.isfinite(transform)) or transform[0] <= 0 or transform[4] >= 0:
        return None
    if abs(transform[1]) > 1e-8 or abs(transform[3]) > 1e-8 or width <= 0 or height <= 0:
        return None
    from data_tools.display_grid import display_grid, supported_crs
    from data_tools.metric_grid import frame_id
    from data_tools.study_domain import crop_grid, study_domain
    from experiments.scene_version import scene_data_version

    if not supported_crs(crs):
        return None
    frame = {"crs": crs, "transform": transform, "width": width, "height": height}
    domain = study_domain(frame)
    return {**frame, "display_frame": crop_grid(display_grid(frame), domain["window"]), "study_domain": domain,
            "frame_id": frame_id(frame),
            "scene_revision": scene_data_version(scene_dir, metadata)["scene_revision"], "units": metadata.get("coordinate_units", "web_mercator_projected_m")}


def read_scene_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value
