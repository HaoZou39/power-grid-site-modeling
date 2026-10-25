"""Prepared site scenes. Optimization reads these files and does not rebuild them."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import numpy as np

from data_tools.io_utils import write_json
from experiments.problem_context import context_from_arrays

Progress = Callable[[float, str, str], None]

SCENE_ARRAYS = (
    "dem_1m.npy",
    "landuse_1m.npy",
    "obstacle_mask_1m.npy",
    "road_segments_local.npy",
    "road_voronoi_1m.npy",
    "demand_points.npy",
)
SCENE_METADATA = "data_metadata.json"
OBSTACLE_OVERLAY = "obstacle_overlay.png"
DEM_OVERLAY = "dem_elevation.png"
DEM_OVERLAY_METADATA = "dem_elevation.json"
DEFAULT_SCENE = "cangnan"
SCENE_SOURCES = {
    "cangnan": {
        "title": "苍南",
        "dem_path": Path("data/苍南10m84_clip_1800m_10m_180x180_3857.tif"),
        "landuse_path": Path("data/satellite_27.501662_120.194639_r0.90km_z18_crop_epsg3857_routing_coarse_mask_downsampled.csv"),
        "osm_roads_path": Path("data/osm_roads_27.501662_120.194639_r0.90km_wgs84.geojson"),
        "reference_geotiff_path": Path("data/satellite_27.501662_120.194639_r0.90km_z18_crop_epsg3857.tif"),
    },
    "yongjia": {
        "title": "永嘉",
        "dem_path": Path("data/sites/yongjia/dem.tif"),
        "landuse_path": Path("data/sites/yongjia/landuse.csv"),
        "osm_roads_path": Path("data/sites/yongjia/osm_roads.geojson"),
        "reference_geotiff_path": Path("data/sites/yongjia/satellite_ref.tif"),
    },
}
SCENE_TITLES = {name: str(source["title"]) for name, source in SCENE_SOURCES.items()}
ROAD_REBUILD_MARKER = ".roads-rebuilding"
ROAD_PRODUCT_FILES = (
    "road_segments_local.npy",
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


def scene_title(scene_name: str) -> str:
    return SCENE_TITLES.get(scene_name, scene_name)


def scene_source_paths(scene_name: str) -> dict[str, Path]:
    source = SCENE_SOURCES.get(scene_name)
    if source is None:
        raise ValueError(f"未知场景 {scene_name}；只允许 cangnan 或 yongjia")
    return {key: Path(value) for key, value in source.items() if key != "title"}


def _project_config_for_scene(scene_name: str, config_path: str | Path):
    from config.project_config import load_project_config

    config = load_project_config(config_path)
    return replace(config, data=replace(config.data, **scene_source_paths(scene_name)))


def missing_scene_files(path: Path) -> list[str]:
    names = (*SCENE_ARRAYS, SCENE_METADATA)
    return [name for name in names if not (path / name).is_file()]


def ensure_scene_readable(path: str | Path) -> None:
    if (Path(path) / ROAD_REBUILD_MARKER).exists():
        raise RuntimeError("场景道路数据正在安全切换，请稍后重试")


def load_scene(
    scene_name: str,
    device: Any,
    root: str | Path | None = None,
    road_setback_m: float = 5.0,
    water_setback_m: float = 5.0,
):
    """Load one finished scene onto the requested device."""

    path = scene_directory(scenes_root(root), scene_name)
    ensure_scene_readable(path)
    missing = missing_scene_files(path)
    if missing:
        missing_text = ", ".join(missing)
        raise FileNotFoundError(
            f"场景 {scene_name} 还没有完成数据构建，缺少 {missing_text}。请先构建场景数据，再开始优化。"
        )
    arrays = {
        "dem": np.load(path / "dem_1m.npy"),
        "landuse": np.load(path / "landuse_1m.npy"),
        "obstacle_mask": np.load(path / "obstacle_mask_1m.npy"),
        "road_segments": np.load(path / "road_segments_local.npy"),
        "road_voronoi": np.load(path / "road_voronoi_1m.npy"),
        "demand_points": np.load(path / "demand_points.npy"),
    }
    metadata = _read_json(path / SCENE_METADATA)
    ensure_scene_readable(path)
    _validate_road_arrays(arrays["road_segments"], arrays["road_voronoi"], arrays["dem"].shape)
    metadata = {**metadata, "scene_id": path.name, "scene_dir": str(path)}
    return context_from_arrays(
        arrays,
        device,
        road_setback_m=road_setback_m,
        water_setback_m=water_setback_m,
    ), metadata


def _validate_road_arrays(segments: np.ndarray, voronoi: np.ndarray, shape: tuple[int, ...]) -> None:
    if segments.ndim != 2 or segments.shape[1] != 4 or len(segments) == 0:
        raise ValueError(f"road segments must have non-empty shape [N, 4], got {segments.shape}")
    if not np.isfinite(segments).all():
        raise ValueError("road segments must be finite")
    if voronoi.shape != shape:
        raise ValueError(f"road Voronoi shape {voronoi.shape} does not match scene shape {shape}")
    if voronoi.size == 0 or int(voronoi.min()) < 0 or int(voronoi.max()) >= len(segments):
        raise ValueError("road Voronoi contains a segment id outside the road segment array")


def rebuild_scene_roads(
    scene_name: str,
    config_path: str | Path = "config/default_config.json",
    root: str | Path | None = None,
    backup_root: str | Path = "outputs/scene-road-backups",
) -> tuple[Path, Path, dict[str, Any]]:
    """Rebuild and guardedly publish only one scene's road products."""

    from config.project_config import load_project_config
    from data_tools.traffic_tool import build_road_product

    scene = scene_directory(scenes_root(root), scene_name)
    required = ("dem_1m.npy", "landuse_1m.npy", *ROAD_PRODUCT_FILES)
    missing = [name for name in required if not (scene / name).is_file()]
    if missing:
        raise FileNotFoundError(f"scene road rebuild is missing: {', '.join(missing)}")
    ensure_scene_readable(scene)
    shape = tuple(int(value) for value in np.load(scene / "dem_1m.npy", mmap_mode="r").shape)
    if tuple(np.load(scene / "landuse_1m.npy", mmap_mode="r").shape) != shape:
        raise ValueError("scene landuse and DEM shapes do not match")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(backup_root) / scene_name / f"{stamp}-{uuid4().hex[:8]}"
    backup.mkdir(parents=True, exist_ok=False)
    for name in ROAD_PRODUCT_FILES:
        source = scene / name
        if source.is_file():
            shutil.copy2(source, backup / name)

    config = (
        _project_config_for_scene(scene_name, config_path)
        if scene_name in SCENE_SOURCES
        else load_project_config(config_path)
    )
    with tempfile.TemporaryDirectory(prefix=f".{scene_name}-roads-", dir=scene.parent) as temporary:
        staged = Path(temporary)
        segments, voronoi, road_metadata = build_road_product(
            config.data.osm_roads_path,
            staged / "road_segments_local.npy",
            staged / "road_voronoi_1m.npy",
            config.data.reference_geotiff_path,
            shape,
            config.data.road_dp_tolerance_m,
            config.data.road_resolution_m,
            voronoi_backend=config.data.road_voronoi_backend,
            voronoi_device=config.data.road_voronoi_device,
            voronoi_chunk_points=config.data.road_voronoi_chunk_points,
            voronoi_segment_tile=config.data.road_voronoi_segment_tile,
        )
        _validate_road_arrays(segments, voronoi, shape)
        product_id = uuid4().hex
        road_metadata = {**road_metadata, "road_product_id": product_id}
        write_json(staged / "road_segments_local.json", road_metadata)
        write_json(staged / "road_voronoi_1m.json", road_metadata)
        scene_metadata = _read_json(scene / SCENE_METADATA)
        scene_metadata["road"] = road_metadata
        write_json(staged / SCENE_METADATA, scene_metadata)

        marker = scene / ROAD_REBUILD_MARKER
        marker.write_text(product_id, encoding="utf-8")
        try:
            for name in ROAD_PRODUCT_FILES:
                _publish_road_file(staged / name, scene / name)
        except Exception:
            for name in ROAD_PRODUCT_FILES:
                saved = backup / name
                if saved.is_file():
                    _publish_road_file(saved, scene / name)
            raise
        finally:
            marker.unlink(missing_ok=True)
    return scene, backup, road_metadata


def _publish_road_file(source: Path, destination: Path) -> None:
    # Copy over the existing inode/file so Windows bind-mount ACLs remain readable by Docker.
    shutil.copyfile(source, destination)


def project_config_for_sources(
    sources: dict[str, Path],
    config_path: str | Path = "config/default_config.json",
):
    """Load the project config with explicit four-file inputs."""

    from config.project_config import load_project_config

    config = load_project_config(config_path)
    paths = {key: Path(value) for key, value in sources.items()}
    return replace(config, data=replace(config.data, **paths))


def publish_scene_directory(staged: Path, destination: Path) -> None:
    """Publish a validated scene directory without deleting the previous one first.

    The previous directory is moved aside and removed only after the new directory
    is in place. A crash before that point leaves the previous copy under
    ``.previous/``.
    """

    if not staged.is_dir():
        raise FileNotFoundError(staged)
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.parent / ".previous" / destination.name
    if not destination.exists() and backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        os.replace(backup, destination)
    if not destination.exists():
        os.replace(staged, destination)
        return
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        shutil.rmtree(backup)
    os.replace(destination, backup)
    try:
        os.replace(staged, destination)
    except Exception:
        if not destination.exists() and backup.exists():
            os.replace(backup, destination)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def scene_rebuild_notice(scene_dir: str | Path) -> str | None:
    """Warning recorded when a rebuild could not keep the previous farmland layer."""

    path = Path(scene_dir) / "scene.json"
    if not path.is_file():
        return None
    notice = _read_json(path).get("protected_farmland_notice")
    if isinstance(notice, str) and notice.strip():
        return notice.strip()
    return None


def _retain_protected_farmland(previous: Path, staged: Path) -> str | None:
    """Copy farmland only when CRS, shape and affine match. A mismatch is reported, not copied."""

    from experiments.protected_farmland import MASK_NAME, META_NAME, OVERLAY_NAME

    if not previous.is_dir() or not (previous / MASK_NAME).is_file():
        return None
    old = scene_frame_info(previous)
    new = scene_frame_info(staged)
    if not _frames_compatible(old, new):
        return "地理参考已变化，未保留原永久基本农田，请重新导入。"
    mask = np.load(previous / MASK_NAME, mmap_mode="r")
    if tuple(int(value) for value in mask.shape) != (int(new["height"]), int(new["width"])):
        return "永久基本农田栅格与新场景网格不一致，未保留，请重新导入。"
    for name in (MASK_NAME, META_NAME, OVERLAY_NAME):
        source = previous / name
        if source.is_file():
            shutil.copy2(source, staged / name)
    if not (staged / MASK_NAME).is_file():
        raise RuntimeError("永久基本农田掩膜没有写入新场景")
    return None


def _frames_compatible(old: dict[str, Any] | None, new: dict[str, Any] | None) -> bool:
    if old is None or new is None or old.get("crs") != new.get("crs"):
        return False
    if int(old["width"]) != int(new["width"]) or int(old["height"]) != int(new["height"]):
        return False
    old_transform = old.get("transform")
    new_transform = new.get("transform")
    if not isinstance(old_transform, list) or not isinstance(new_transform, list):
        return False
    if len(old_transform) != 6 or len(new_transform) != 6:
        return False
    return all(abs(float(left) - float(right)) <= 1e-3 for left, right in zip(old_transform, new_transform))


def prepare_scene_from_sources(
    scene_name: str,
    sources: dict[str, Path],
    reporter: Progress,
    *,
    title: str,
    source_site_id: str,
    config_path: str | Path = "config/default_config.json",
    root: str | Path | None = None,
    progress_stage: str = "scene",
) -> Path:
    """Rebuild one scene from explicit raw files and publish it only after checks pass."""

    from experiments.problem_context import write_scene_products

    base = scenes_root(root).expanduser().resolve()
    path = scene_directory(base, scene_name)
    resolved = {key: Path(value) for key, value in sources.items()}
    for source in resolved.values():
        if not source.is_file():
            raise FileNotFoundError(f"场景 {scene_name} 缺少原始文件：{source}")
    config = project_config_for_sources(resolved, config_path)
    base.mkdir(parents=True, exist_ok=True)
    reporter(0.1, progress_stage, f"正在构建{title}场景数据。这一步不运行优化。")

    def on_step(message: str) -> None:
        reporter(0.4, progress_stage, message)

    with tempfile.TemporaryDirectory(prefix=f".{scene_name}-prepare-", dir=base) as temporary:
        staged = Path(temporary) / scene_name
        _, metadata = write_scene_products(config, staged, on_step)
        write_json(staged / SCENE_METADATA, metadata)
        write_obstacle_overlay(staged)
        write_dem_overlay(staged, staged)
        farmland_notice = _retain_protected_farmland(path, staged)
        scene_record = {
            "id": scene_name,
            "title": title,
            "source_site_id": source_site_id,
            "source_files": {key: str(value) for key, value in resolved.items()},
        }
        if farmland_notice:
            scene_record["protected_farmland_notice"] = farmland_notice
        write_json(staged / "scene.json", scene_record)
        missing = missing_scene_files(staged)
        if missing or not (staged / "landuse_1m.npy").is_file() or scene_frame_info(staged) is None:
            raise RuntimeError(f"场景 {scene_name} 构建产物不完整：{', '.join(missing)}")
        publish_scene_directory(staged, path)
    message = "场景数据已写入" if not farmland_notice else f"场景数据已写入。{farmland_notice}"
    reporter(1.0, "completed" if progress_stage == "scene" else progress_stage, message)
    return path


def prepare_scene(
    scene_name: str,
    reporter: Progress,
    config_path: str | Path = "config/default_config.json",
    root: str | Path | None = None,
    rebuild: bool = False,
) -> Path:
    """Build one registered scene from its raw inputs. Call this only from the data stage.

    Opening a ready scene reuses it. ``rebuild`` writes the scene again from its
    source files and fuses the current water data instead of keeping the old landuse.
    """

    base = scenes_root(root).expanduser().resolve()
    path = scene_directory(base, scene_name)
    if not rebuild and not missing_scene_files(path) and scene_frame_info(path) is not None:
        reporter(1.0, "completed", "场景数据已就绪，直接复用")
        return path

    if scene_name in SCENE_SOURCES:
        sources = scene_source_paths(scene_name)
        title = scene_title(scene_name)
        source_site_id = scene_name
    else:
        sources, title, source_site_id = _published_scene_sources(path, scene_name)
    for source in sources.values():
        if not source.is_file():
            raise FileNotFoundError(f"场景 {scene_name} 缺少原始文件：{source}")
    return prepare_scene_from_sources(
        scene_name,
        sources,
        reporter,
        title=title,
        source_site_id=source_site_id,
        config_path=config_path,
        root=root,
    )


def _published_scene_sources(path: Path, scene_name: str) -> tuple[dict[str, Path], str, str]:
    record_path = path / "scene.json"
    if not record_path.is_file():
        raise FileNotFoundError(f"场景 {scene_name} 没有 scene.json，不能重新构建")
    record = _read_json(record_path)
    raw = record.get("source_files")
    required = ("dem_path", "landuse_path", "osm_roads_path", "reference_geotiff_path")
    if not isinstance(raw, dict) or any(not raw.get(key) for key in required):
        raise FileNotFoundError(f"场景 {scene_name} 没有记录原始四文件，不能重新构建")
    sources = {key: Path(str(raw[key])) for key in required}
    title = str(record.get("title") or scene_name)
    source_site_id = str(record.get("source_site_id") or scene_name)
    return sources, title, source_site_id


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
    write_dem_overlay(path, path)
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
    dem = np.load(source, mmap_mode="r")
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

    metadata = _read_json(scene_dir / SCENE_METADATA)
    dem_metadata = metadata.get("dem") if isinstance(metadata.get("dem"), dict) else {}
    transform = dem_metadata.get("source_transform")
    source_resolution = None
    if isinstance(transform, list) and len(transform) >= 5:
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
        "source_mtime_ns": source.stat().st_mtime_ns,
    }
    destination = output_dir or scene_dir
    destination.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image, mode="RGBA").save(destination / DEM_OVERLAY, format="PNG")
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
        info = _read_json(metadata_path)
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


def scene_layer_info(scene_name: str, root: str | Path | None = None) -> dict[str, Any]:
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
        except (ValueError, OSError) as exc:
            roads = {"available": False, "segment_count": 0, "error": str(exc)}
    from experiments.protected_farmland import layer_info

    return {"dem": dem, "landuse": landuse, "roads": roads, "protected_farmland": layer_info(path)}


def scene_frame_info(scene_dir: Path) -> dict[str, Any] | None:
    """A scene-specific reference grid for the map, not the fixed Cangnan frame."""
    metadata_path = scene_dir / SCENE_METADATA
    if not metadata_path.is_file():
        return None
    metadata = _read_json(metadata_path)
    dem = metadata.get("dem") or {}
    transform = dem.get("target_transform")
    shape = dem.get("shape")
    crs = dem.get("reference_crs")
    if (
        crs != "EPSG:3857"
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
    return {"crs": crs, "transform": transform, "width": width, "height": height}


def _landuse_csv_shape(path: Path) -> tuple[int, int]:
    height = 0
    width: int | None = None
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            columns = len(stripped.split(","))
            if width is None:
                width = columns
            elif columns != width:
                raise ValueError(f"landuse CSV rows have inconsistent widths: {path}")
            height += 1
    if height <= 0 or width is None or width <= 0:
        raise ValueError(f"landuse CSV is empty: {path}")
    return height, width


def source_scene_frame_info(scene_name: str, config_path: str | Path = "config/default_config.json") -> dict[str, Any] | None:
    """Read an unbuilt scene's real reference bounds without creating products."""

    if scene_name not in SCENE_SOURCES:
        return None
    config = _project_config_for_scene(scene_name, config_path)
    if not config.data.landuse_path.is_file() or not config.data.reference_geotiff_path.is_file():
        return None
    import rasterio
    from rasterio.transform import from_bounds

    raw_height, raw_width = _landuse_csv_shape(config.data.landuse_path)
    scale = config.data.landuse_input_resolution_m / config.data.target_resolution_m
    height = int(round(raw_height * scale))
    width = int(round(raw_width * scale))
    if height <= 0 or width <= 0:
        raise ValueError("scene preview grid shape is invalid")
    with rasterio.open(config.data.reference_geotiff_path) as reference:
        if reference.crs is None:
            raise ValueError(f"reference GeoTIFF has no CRS: {config.data.reference_geotiff_path}")
        if str(reference.crs) != "EPSG:3857":
            raise ValueError(f"reference GeoTIFF must use EPSG:3857, got {reference.crs}")
        transform = from_bounds(*reference.bounds, width, height)
    return {
        "crs": "EPSG:3857",
        "transform": [float(value) for value in list(transform)[:6]],
        "width": width,
        "height": height,
    }


def list_scenes(root: str | Path | None = None) -> list[dict[str, Any]]:
    base = scenes_root(root)
    directories = {
        item.name: item
        for item in base.iterdir()
        if item.is_dir() and not item.name.startswith(".") and not item.name.endswith(".previous")
    } if base.is_dir() else {}
    names = [*SCENE_SOURCES, *sorted(set(directories) - set(SCENE_SOURCES))]
    scenes = []
    for name in names:
        path = directories.get(name, base / name)
        info = _read_json(path / "scene.json") if (path / "scene.json").is_file() else {}
        missing = missing_scene_files(path)
        try:
            frame = scene_frame_info(path) if not missing else source_scene_frame_info(name)
        except (ValueError, OSError, KeyError):
            frame = None
        scenes.append({
            "id": name,
            "title": scene_title(name) if name in SCENE_SOURCES else str(info.get("title") or scene_title(name)),
            "ready": not missing and frame is not None,
            "missing": missing if missing else ([] if frame is not None else ["scene frame metadata (EPSG:3857)"]),
            "frame": frame,
            "source_site_id": info.get("source_site_id") or (name if name in SCENE_SOURCES else None),
        })
    return scenes


def _read_json(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value
