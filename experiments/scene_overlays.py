"""Render and read optional map resources for published scenes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from data_tools.io_utils import write_json
from experiments.scene_files import (
    SCENE_METADATA, ensure_scene_readable, read_scene_json, scene_directory, scene_frame_info, scenes_root,
)
from experiments.scene_lock import scene_write_lock


OBSTACLE_OVERLAY = "obstacle_overlay.png"
DEM_OVERLAY = "dem_elevation.png"
DEM_OVERLAY_METADATA = "dem_elevation.json"


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
    from data_tools.display_grid import project_overlay_rgba

    frame = scene_frame_info(scene_dir)
    Image.fromarray(project_overlay_rgba(image, frame) if frame else image, mode="RGBA").save(out, format="PNG")
    return out


def _write_class_overlays(scene_dir: Path, landuse: np.ndarray, image_cls: Any) -> Path:
    if landuse.ndim != 2 or landuse.size == 0:
        raise ValueError(f"landuse must be a non-empty 2D array, got {landuse.shape}")
    frame = scene_frame_info(scene_dir)
    # UTM 只把类别最近邻投到 3857 一次。3857 和没有 frame 的网格直接做调色板。
    if frame is not None and frame["crs"] != "EPSG:3857":
        from data_tools.display_grid import project_landuse_classes

        landuse = project_landuse_classes(landuse, frame)
    _write_palette_class_overlays(scene_dir, landuse, image_cls)
    return scene_dir / OBSTACLE_OVERLAY


def _write_palette_class_overlays(scene_dir: Path, landuse: np.ndarray, image_cls: Any) -> None:
    from experiments.constraint_mask import CLASS_COLORS

    transparent = (0, 0, 0, 0)
    combined = np.zeros(landuse.shape, dtype=np.uint8)
    combined_colors = [transparent]
    for slot, (name, (class_id, color)) in enumerate(CLASS_COLORS.items(), start=1):
        selected = landuse == class_id
        index = np.zeros(landuse.shape, dtype=np.uint8)
        index[selected] = 1
        _save_indexed_png(scene_dir / f"landuse_{name}.png", index, (transparent, color), image_cls)
        combined[selected] = slot
        combined_colors.append(color)
    _save_indexed_png(scene_dir / OBSTACLE_OVERLAY, combined, combined_colors, image_cls)


def _save_indexed_png(path: Path, index: np.ndarray, colors: tuple | list, image_cls: Any) -> None:
    image = image_cls.fromarray(index, mode="P")
    image.putpalette([channel for color in colors for channel in color[:3]])
    image.info["transparency"] = bytes(color[3] for color in colors)
    # 压缩级别与可行域调色板一致。解码后的 RGBA 不随级别变化。
    image.save(path, format="PNG", compress_level=1)


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


def construction_feasibility_png(
    scene_name: str,
    form: dict[str, Any],
    root: str | Path | None = None,
) -> bytes:
    """Render land hard cells plus road and water setbacks. Not a rotated-footprint test."""

    from experiments.feasibility_overlay_cache import render_construction_feasibility_png

    return render_construction_feasibility_png(scene_name, form, root)


def write_dem_overlay(scene_dir: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Render the aligned DEM as a cached colour image without changing scene readiness."""

    from PIL import Image

    source = scene_dir / "dem_1m.npy"
    if not source.is_file():
        raise FileNotFoundError(f"场景 {scene_dir.name} 缺少 dem_1m.npy")
    with scene_write_lock(scene_dir.name, scene_dir.parent, blocking=True):
        dem = np.load(source)
        metadata = read_scene_json(scene_dir / SCENE_METADATA)
        source_mtime = source.stat().st_mtime_ns
        frame = scene_frame_info(scene_dir)
    if dem.ndim != 2 or dem.size == 0:
        raise ValueError(f"DEM must be a non-empty 2D array, got {dem.shape}")
    finite = np.isfinite(dem)
    if not finite.any():
        raise ValueError("DEM does not contain finite elevations")

    minimum = float(np.min(dem[finite]))
    maximum = float(np.max(dem[finite]))
    normalized = np.zeros(dem.shape, dtype=np.float32)
    if maximum > minimum:
        normalized[finite] = (dem[finite] - minimum) / (maximum - minimum)
    stops = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
    colours = np.array([
        [28, 74, 122],
        [42, 137, 132],
        [117, 176, 111],
        [218, 188, 103],
        [248, 239, 211],
    ], dtype=np.float32)
    image = np.zeros((*dem.shape, 4), dtype=np.uint8)
    for channel in range(3):
        image[..., channel] = np.interp(normalized, stops, colours[:, channel]).astype(np.uint8)
    image[..., 3] = np.where(finite, 255, 0).astype(np.uint8)

    dem_metadata = metadata.get("dem") if isinstance(metadata.get("dem"), dict) else {}
    transform = dem_metadata.get("source_transform")
    source_resolution = None
    if isinstance(transform, list) and len(transform) >= 5:
        if dem_metadata.get("source_crs") and dem_metadata.get("raw_shape"):
            from data_tools.dem_tool import source_pixel_size_m
            source_resolution = source_pixel_size_m(dem_metadata["source_crs"], transform, dem_metadata["raw_shape"])
        else:
            source_resolution = max(abs(float(transform[0])), abs(float(transform[4])))
    info = {
        "min_elevation_m": minimum,
        "max_elevation_m": maximum,
        "unit": "m",
        "source_resolution_m": source_resolution,
        "grid_resolution_m": float(dem_metadata.get("target_resolution_m", 1.0)),
        "resampling": str(dem_metadata.get("resampling", "unknown")),
        "width": int(dem.shape[1]),
        "height": int(dem.shape[0]),
        "source_mtime_ns": source_mtime,
    }
    destination = output_dir or scene_dir
    destination.mkdir(parents=True, exist_ok=True)
    from data_tools.display_grid import project_overlay_rgba

    display_image = project_overlay_rgba(image, frame) if frame else image
    Image.fromarray(display_image, mode="RGBA").save(destination / DEM_OVERLAY, format="PNG")
    write_json(destination / DEM_OVERLAY_METADATA, info)
    return info


def dem_overlay_info(scene_name: str, root: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    """Return a current DEM image and metadata, using a writable cache for legacy scenes."""

    scene_dir = scene_directory(scenes_root(root), scene_name)
    source = scene_dir / "dem_1m.npy"
    if not source.is_file():
        raise FileNotFoundError(f"场景 {scene_name} 缺少 dem_1m.npy")

    candidates = [scene_dir]
    cache_root = Path(os.environ.get(
        "SCENE_LAYER_CACHE_ROOT",
        str(Path(tempfile.gettempdir()) / "power-grid-site-layer-cache"),
    ))
    candidates.append(cache_root / scene_name)
    for directory in candidates:
        image_path = directory / DEM_OVERLAY
        metadata_path = directory / DEM_OVERLAY_METADATA
        if not image_path.is_file() or not metadata_path.is_file():
            continue
        info = read_scene_json(metadata_path)
        if int(info.get("source_mtime_ns", -1)) == source.stat().st_mtime_ns:
            return image_path, info

    cache_dir = candidates[-1]
    info = write_dem_overlay(scene_dir, cache_dir)
    return cache_dir / DEM_OVERLAY, info


def road_segments(scene_name: str, root: str | Path | None = None) -> list[list[float]]:
    """Read the prepared OSM segments in the shared local metre coordinate system."""

    scene = scene_directory(scenes_root(root), scene_name)
    ensure_scene_readable(scene)
    path = scene / "road_segments_local.npy"
    if not path.is_file():
        raise FileNotFoundError(f"场景 {scene_name} 缺少 road_segments_local.npy")
    segments = np.load(path)
    ensure_scene_readable(scene)
    if segments.ndim != 2 or segments.shape[1] != 4 or not np.isfinite(segments).all():
        raise ValueError(f"road segments must have shape [N, 4] with finite values, got {segments.shape}")
    return segments.astype(float, copy=False).tolist()


def road_segment_bundle(scene_name: str, root: str | Path | None = None) -> dict:
    scene = scene_directory(scenes_root(root), scene_name)
    with scene_write_lock(scene_name, scene.parent, blocking=True):
        segments = road_segments(scene_name, root)
        kinds = np.load(scene / "road_segment_kind.npy")
        if kinds.shape != (len(segments),) or kinds.dtype != np.int8 or not np.isin(kinds, [0,1,2,3]).all():
            raise ValueError("道路线段与类别不一致")
        from experiments.scene_version import scene_data_version
        return {"segments": segments, "kinds": kinds.tolist(), "count": len(segments),
                "data_version": scene_data_version(scene)}


def scene_layer_info(scene_name: str, root: str | Path | None = None) -> dict[str, Any]:
    path = scene_directory(scenes_root(root), scene_name)
    # Legacy images may need rendering; do that before entering the metadata read lock.
    try:
        dem_overlay_info(scene_name, root)
    except (FileNotFoundError, ValueError, OSError):
        pass  # The metadata response reports this resource's availability below.
    with scene_write_lock(scene_name, path.parent, blocking=True):
        return _scene_layer_info(scene_name, root)


def _scene_layer_info(scene_name: str, root: str | Path | None = None) -> dict[str, Any]:
    """Describe optional map resources without making them required scene products."""

    path = scene_directory(scenes_root(root), scene_name)
    ensure_scene_readable(path)
    if not path.is_dir():
        raise FileNotFoundError(f"场景 {scene_name} 不存在")
    landuse = {
        layer: (path / f"landuse_{layer}.png").is_file()
        for layer in ("field", "building", "road", "water")
    }
    dem: dict[str, Any]
    try:
        _, dem_info = dem_overlay_info(scene_name, root)
        dem = {"available": True, **dem_info}
    except (FileNotFoundError, ValueError, OSError) as exc:
        dem = {"available": False, "error": str(exc)}
    roads_path = path / "road_segments_local.npy"
    roads: dict[str, Any] = {"available": roads_path.is_file(), "segment_count": 0}
    if roads_path.is_file():
        try:
            segments = np.load(roads_path, mmap_mode="r")
            if segments.ndim != 2 or segments.shape[1] != 4:
                raise ValueError(f"road segments must have shape [N, 4], got {segments.shape}")
            roads["segment_count"] = int(segments.shape[0])
            road_meta = read_scene_json(path / SCENE_METADATA).get("road", {})
            roads["provider"] = str(road_meta.get("provider", "osm"))
            roads["road_product_id"] = road_meta.get("road_product_id", "")
            kinds = np.load(path / "road_segment_kind.npy")
            if kinds.shape != (len(segments),):
                raise ValueError("road kinds must align with segments")
            roads["segment_kind_counts"] = {str(k): int(np.count_nonzero(kinds == k)) for k in range(4)}
        except (ValueError, OSError) as exc:
            roads = {"available": False, "segment_count": 0, "error": str(exc)}
    from experiments.protected_farmland import layer_info

    from experiments.scene_version import scene_data_version
    return {"scene_id": scene_name, "data_version": scene_data_version(path), "dem": dem, "landuse": landuse, "roads": roads, "protected_farmland": layer_info(path)}
