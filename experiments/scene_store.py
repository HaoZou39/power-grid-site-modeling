"""Prepared site scenes. Optimization reads these files and does not rebuild them."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

from config.project_config import load_default_config
from data_tools.io_utils import write_json
from experiments.problem_context import context_from_arrays
from experiments.scene_lock import scene_write_lock
from experiments.scene_files import (
    ROAD_PRODUCT_FILES, ROAD_REBUILD_MARKER, SCENE_ARRAYS, SCENE_METADATA,
    ensure_scene_readable, ensure_scene_writable, missing_scene_files,
    read_scene_json as _read_json, scene_directory, scene_frame_info, scenes_root,
)
from experiments.scene_overlays import (
    DEM_OVERLAY, DEM_OVERLAY_METADATA, OBSTACLE_OVERLAY,
    construction_feasibility_png, dem_overlay_info, landuse_overlay_path, obstacle_overlay_path,
    road_segment_bundle, road_segments, scene_layer_info, write_dem_overlay, write_obstacle_overlay,
)
from experiments.scene_publication import detach_shared_file, publish_road_bundle

Progress = Callable[[float, str, str], None]
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SCENE = load_default_config().default_scene
_DEFAULT_DATA = load_default_config().data
SCENE_SOURCES = {
    DEFAULT_SCENE: {
        "title": "苍南（UTM）",
        **{key:getattr(_DEFAULT_DATA,key) for key in ("dem_path","landuse_path","osm_roads_path","reference_geotiff_path")},
    },
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


def scene_title(scene_name: str) -> str:
    return SCENE_TITLES.get(scene_name, scene_name)


def scene_source_paths(scene_name: str) -> dict[str, Path]:
    source = SCENE_SOURCES.get(scene_name)
    if source is None:
        raise ValueError(f"未知预置场景 {scene_name}")
    return {key: Path(value) for key, value in source.items() if key != "title"}


def _resolve_source_path(value: str | Path) -> Path:
    """Source paths in scene records are relative to the repository, not the CWD."""

    return (REPOSITORY_ROOT / Path(value).expanduser()).resolve()


def _project_config_for_scene(scene_name: str, config_path: str | Path):
    from config.project_config import load_project_config

    config = load_project_config(config_path)
    return replace(config, data=replace(config.data, **scene_source_paths(scene_name)))


def load_scene(
    scene_name: str,
    device: Any,
    root: str | Path | None = None,
    *,
    road_setback_m: float,
    water_setback_m: float,
    highway_setback_m: float,
    snapshot: dict | None = None,
):
    """Load one finished scene onto the requested device."""

    snapshot = read_scene_snapshot(scene_name, root) if snapshot is None else snapshot
    from data_tools.study_domain import outside_study_mask
    arrays, frame = snapshot["arrays"], snapshot["frame"]
    return context_from_arrays(
        arrays, device, road_setback_m=road_setback_m, water_setback_m=water_setback_m,
        highway_setback_m=highway_setback_m, sources=snapshot["sources"],
        study_outside=None if frame is None else outside_study_mask(frame["study_domain"]["ring"], arrays["dem"].shape),
    ), snapshot["metadata"]


def read_scene_snapshot(scene_name: str, root: str | Path | None = None, *, writable: bool = False) -> dict:
    """Copy every computational input before releasing the short data lock."""

    path = scene_directory(scenes_root(root), scene_name)
    with scene_write_lock(scene_name, path.parent, blocking=True):
        if writable:
            ensure_scene_writable(path)
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
            "road_segment_kinds": np.load(path / "road_segment_kind.npy"),
            "road_voronoi": np.load(path / "road_voronoi_1m.npy"),
            "demand_points": np.load(path / "demand_points.npy"),
        }
        metadata = _read_json(path / SCENE_METADATA)
        frame = scene_frame_info(path)
        ensure_scene_readable(path)
        _validate_road_arrays(arrays["road_segments"], arrays["road_voronoi"], arrays["dem"].shape, arrays["road_segment_kinds"])
        from experiments.scene_version import scene_data_version
        metadata = {**metadata, "scene_id": path.name, "scene_dir": str(path),
                    "data_version": scene_data_version(path, metadata)}
        metadata["coordinate_context"] = {"scene_id": path.name, "frame_id": metadata["data_version"]["frame_id"], "frame": frame}
        from experiments.base_constraint_cache import scene_buffer_sources
        sources = scene_buffer_sources(path, arrays["dem"].shape)
        from experiments.protected_farmland import load_mask
        from experiments.haul_field_cache import scene_source_signature
        farmland = load_mask(path, arrays["dem"].shape)
        metadata["scene_signature"] = scene_source_signature(path, uses_landuse=True)
    return {"arrays": arrays, "metadata": metadata, "frame": frame, "sources": sources, "farmland": farmland}


def _validate_road_arrays(segments: np.ndarray, voronoi: np.ndarray, shape: tuple[int, ...], kinds: np.ndarray) -> None:
    if segments.ndim != 2 or segments.shape[1] != 4 or len(segments) == 0:
        raise ValueError(f"road segments must have non-empty shape [N, 4], got {segments.shape}")
    if not np.isfinite(segments).all():
        raise ValueError("road segments must be finite")
    if voronoi.shape != shape:
        raise ValueError(f"road Voronoi shape {voronoi.shape} does not match scene shape {shape}")
    if not np.issubdtype(voronoi.dtype, np.integer):
        raise ValueError("road Voronoi must contain integer segment ids")
    if voronoi.size == 0 or int(voronoi.min()) < 0 or int(voronoi.max()) >= len(segments):
        raise ValueError("road Voronoi contains a segment id outside the road segment array")
    if kinds.dtype != np.int8 or kinds.shape != (len(segments),) or not np.isin(kinds, [0, 1, 2, 3]).all():
        raise ValueError("road kinds must be int8 [N] with codes 0..3")
    if not np.any(kinds == 0) or np.any(kinds[voronoi] != 0):
        raise ValueError("road Voronoi must reference access roads only")


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
    with scene_write_lock(scene_name, scene.parent):
        ensure_scene_readable(scene)
        shape = tuple(int(value) for value in np.load(scene / "dem_1m.npy", mmap_mode="r").shape)
        if tuple(np.load(scene / "landuse_1m.npy", mmap_mode="r").shape) != shape:
            raise ValueError("scene landuse and DEM shapes do not match")

        record_path = scene / "scene.json"
        record = _read_json(record_path) if record_path.is_file() else {}
        imported = record.get("road_source")
        if imported and imported["provider"] != "osm":
            road_source = scene / "road_source_wgs84.geojson"
            provider = imported["provider"]
        else:
            original = record.get("source_files", {}).get("osm_roads_path")
            if original:
                road_source = _resolve_source_path(original)
            elif scene_name in SCENE_SOURCES:
                road_source = _project_config_for_scene(scene_name, config_path).data.osm_roads_path
            else:
                raise FileNotFoundError("场景未记录 OSM 道路来源")
            provider = "osm"
        with tempfile.TemporaryDirectory(prefix=f".{scene_name}-roads-", dir=scene.parent) as temporary:
            staged = Path(temporary)
            from experiments.scene_data_import import stage_road_source
            road_metadata = stage_road_source(scene, staged, road_source, provider, Path(config_path))
            product_id = road_metadata["road_product_id"]
            write_json(staged / "road_segments_local.json", road_metadata)
            write_json(staged / "road_voronoi_1m.json", road_metadata)
            scene_metadata = _read_json(scene / SCENE_METADATA)
            scene_metadata["road"] = road_metadata
            write_json(staged / SCENE_METADATA, scene_metadata)
            backup = publish_road_bundle(scene, staged, Path(backup_root), product_id)
    return scene, backup, road_metadata


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
    with scene_write_lock(destination.name, destination.parent, blocking=True):
        _publish_scene_directory(staged, destination)


def _publish_scene_directory(staged: Path, destination: Path) -> None:
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
        try:
            publish_scene_description(destination)
        except Exception:
            os.replace(destination, staged)
            raise
        return
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        shutil.rmtree(backup)
    os.replace(destination, backup)
    try:
        os.replace(staged, destination)
        publish_scene_description(destination)
    except Exception:
        if destination.exists():
            os.replace(destination, staged)
        if not destination.exists() and backup.exists():
            os.replace(backup, destination)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def scene_rebuild_notice(scene_dir: str | Path) -> str | None:
    """Warning recorded when a rebuild could not keep the previous farmland layer."""

    path = Path(scene_dir) / "scene.json"
    if not path.is_file():
        return None
    record = _read_json(path)
    notice = "。".join(value for value in (record.get("protected_farmland_notice"), record.get("road_notice")) if isinstance(value, str) and value.strip())
    if isinstance(notice, str) and notice.strip():
        return notice.strip()
    return None


def _retain_protected_farmland(previous: Path, staged: Path) -> str | None:
    """Copy farmland only when CRS, shape and affine match. A mismatch is reported, not copied."""

    from experiments.protected_farmland import MASK_NAME, META_NAME, OVERLAY_NAME, SOURCE_NAME

    if not previous.is_dir() or not (previous / MASK_NAME).is_file():
        return None
    old = scene_frame_info(previous)
    new = scene_frame_info(staged)
    if not _frames_compatible(old, new):
        return "地理参考已变化，未保留原永久基本农田，请重新导入。"
    mask = np.load(previous / MASK_NAME, mmap_mode="r")
    if tuple(int(value) for value in mask.shape) != (int(new["height"]), int(new["width"])):
        return "永久基本农田栅格与新场景网格不一致，未保留，请重新导入。"
    for name in (MASK_NAME, META_NAME, OVERLAY_NAME, SOURCE_NAME):
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
    scene_name: str, sources: dict[str, Path], reporter: Progress, *, title: str,
    source_site_id: str, config_path: str | Path = "config/default_config.json",
    root: str | Path | None = None, progress_stage: str = "scene",
    reference_frame: dict[str, Any] | None = None,
) -> Path:
    from experiments.scene_lock import scene_compute_lock
    with scene_compute_lock(scene_name, scenes_root(root)):
        with scene_write_lock(scene_name, scenes_root(root)):
            ensure_scene_writable(scene_directory(scenes_root(root), scene_name))
        return _prepare_scene_from_sources(
            scene_name, sources, reporter, title=title, source_site_id=source_site_id,
            config_path=config_path, root=root, progress_stage=progress_stage,
            reference_frame=reference_frame,
        )


def _prepare_scene_from_sources(
    scene_name: str,
    sources: dict[str, Path],
    reporter: Progress,
    *,
    title: str,
    source_site_id: str,
    config_path: str | Path = "config/default_config.json",
    root: str | Path | None = None,
    progress_stage: str = "scene",
    reference_frame: dict[str, Any] | None = None,
) -> Path:
    """Rebuild one scene from explicit raw files and publish it only after checks pass."""

    from experiments.problem_context import write_scene_products

    base = scenes_root(root).expanduser().resolve()
    path = scene_directory(base, scene_name)
    resolved = {key: _resolve_source_path(value) for key, value in sources.items()}
    old_record = _read_json(path / "scene.json") if (path / "scene.json").is_file() else {}
    reference_frame = reference_frame or old_record.get("target_grid")
    if reference_frame is None:
        # 已发布场景的网格在 data_metadata.json。缺 scene.json target_grid 时不能改用默认场景的网格。
        own = scene_frame_info(path)
        if own is not None:
            reference_frame = {key: own[key] for key in ("crs", "transform", "width", "height")}
    retained = old_record.get("road_source")
    keep_roads = bool(retained and retained["provider"] != "osm")
    for key, source in resolved.items():
        if key == "osm_roads_path" and keep_roads:
            source = path / "road_source_wgs84.geojson"
        if not source.is_file():
            raise FileNotFoundError(f"场景 {scene_name} 缺少原始文件：{source}")
    config = project_config_for_sources(resolved, config_path)
    base.mkdir(parents=True, exist_ok=True)
    reporter(0.1, progress_stage, f"正在构建{title}场景数据。这一步不运行优化。")

    def on_step(message: str) -> None:
        reporter(0.4, progress_stage, message)

    with tempfile.TemporaryDirectory(prefix=f".{scene_name}-prepare-", dir=base) as temporary:
        staged = Path(temporary) / scene_name
        road_notice = None
        if keep_roads:
            retained_source = Path(temporary) / "road_source_wgs84.geojson"
            shutil.copyfile(path / "road_source_wgs84.geojson", retained_source)
            config = replace(config, data=replace(config.data, osm_roads_path=retained_source))
        options = {"reference_frame": reference_frame} if reference_frame is not None else {}
        _, metadata = write_scene_products(config, staged, on_step, **options)
        if keep_roads:
            shutil.copyfile(retained_source, staged / "road_source_wgs84.geojson")
            previous_road = _read_json(path / SCENE_METADATA).get("road", {})
            metadata["road"].update({key: previous_road[key] for key in ("provider", "source_name", "source_sha256", "import") if key in previous_road})
            metadata["road"]["source_path"] = "road_source_wgs84.geojson"
            write_json(staged / "road_segments_local.json", metadata["road"])
            write_json(staged / "road_voronoi_1m.json", metadata["road"])
            label = "高德" if retained["provider"] == "gaode" else retained["provider"]
            road_notice = f"已保留导入的{label}道路"
        write_json(staged / SCENE_METADATA, metadata)
        write_obstacle_overlay(staged)
        write_dem_overlay(staged, staged)
        farmland_notice = _retain_protected_farmland(path, staged)
        if (path / "cad_files").is_dir():
            shutil.copytree(path / "cad_files", staged / "cad_files")
        from experiments.cad_landuse import retain_cad_landuse
        retain_cad_landuse(path, staged)
        scene_record = {
            "id": scene_name,
            "title": title,
            "source_site_id": source_site_id,
            "source_files": {
                key: value.relative_to(REPOSITORY_ROOT).as_posix()
                if value.is_relative_to(REPOSITORY_ROOT) else str(value)
                for key, value in resolved.items()
            },
        }
        dem_grid = metadata["dem"]
        scene_record["target_grid"] = {"crs":dem_grid["reference_crs"], "transform":dem_grid["target_transform"],
            "width":dem_grid["shape"][1], "height":dem_grid["shape"][0]}
        if keep_roads:
            scene_record["road_source"] = retained
            scene_record["road_notice"] = road_notice
        if farmland_notice:
            scene_record["protected_farmland_notice"] = farmland_notice
        write_json(staged / "scene.json", scene_record)
        missing = missing_scene_files(staged)
        if missing or not (staged / "landuse_1m.npy").is_file() or scene_frame_info(staged) is None:
            raise RuntimeError(f"场景 {scene_name} 构建产物不完整：{', '.join(missing)}")
        reporter(0.95, progress_stage, "正在检查并发布完整场景")
        publish_scene_directory(staged, path)
    message = "。".join(item for item in ("场景数据已写入", farmland_notice, road_notice) if item)
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
        sources = {key: _resolve_source_path(value) for key, value in scene_source_paths(scene_name).items()}
        existing = _read_json(path / "scene.json") if (path / "scene.json").is_file() else {}
        title = str(existing.get("title") or scene_title(scene_name))
        source_site_id = scene_name
    else:
        sources, title, source_site_id = _published_scene_sources(path, scene_name)
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
    sources = {key: _resolve_source_path(str(raw[key])) for key in required}
    title = str(record.get("title") or scene_name)
    source_site_id = str(record.get("source_site_id") or scene_name)
    return sources, title, source_site_id


def adopt_scene(source: str | Path, scene_name: str, root: str | Path | None = None) -> Path:
    """Copy prepared products without sharing mutable files with their source."""

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
        shutil.copy2(src, dest)
    landuse_src = origin / "landuse_1m.npy"
    if landuse_src.is_file() and not (path / "landuse_1m.npy").exists():
        shutil.copy2(landuse_src, path / "landuse_1m.npy")
    write_json(path / "scene.json", {"id": path.name, "title": scene_title(path.name)})
    write_obstacle_overlay(path)
    write_dem_overlay(path, path)
    return path


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
    if scene_name == DEFAULT_SCENE:
        return dict(config.data.target_grid)
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


def rename_scene(scene_name: str, title: str, root: str | Path | None = None) -> dict[str, str]:
    """Change the display title stored in scene.json. The directory name stays the id."""

    cleaned = title.strip()
    if not cleaned:
        raise ValueError("场景名称不能为空")
    if len(cleaned) > 80:
        raise ValueError("场景名称不能超过 80 个字")
    base = scenes_root(root).expanduser().resolve()
    path = scene_directory(base, scene_name)
    if not path.is_dir() and scene_name not in SCENE_SOURCES:
        raise FileNotFoundError(scene_name)
    with scene_write_lock(scene_name, base, blocking=True):
        path.mkdir(parents=True, exist_ok=True)
        record_path = path / "scene.json"
        record = _read_json(record_path) if record_path.is_file() else {"id": path.name}
        record["id"] = path.name
        record["title"] = cleaned
        temporary = record_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(record_path)
        publish_scene_description(path)
    return {"id": path.name, "title": cleaned}


def _scan_scene_descriptions(root: str | Path | None = None) -> list[dict[str, Any]]:
    base = scenes_root(root)
    directories = {
        item.name: item
        for item in base.iterdir()
        if item.is_dir() and not item.name.startswith(".") and not item.name.endswith(".previous")
    } if base.is_dir() else {}
    names = [DEFAULT_SCENE, *sorted(set(directories) - {DEFAULT_SCENE})]
    scenes = []
    for name in names:
        with scene_write_lock(name, base, blocking=True):
            path = directories.get(name, base / name)
            info = _read_json(path / "scene.json") if (path / "scene.json").is_file() else {}
            missing = missing_scene_files(path)
            try:
                frame = scene_frame_info(path) if not missing else source_scene_frame_info(name)
            except (ValueError, OSError, KeyError):
                frame = None
            scenes.append({
                "id": name,
                "title": str(info.get("title") or scene_title(name)),
                "ready": not missing and frame is not None,
                "read_only": bool(info.get("read_only", False)),
                "default": bool(info.get("default", name == DEFAULT_SCENE)),
                "missing": missing if missing else ([] if frame is not None else ["scene frame metadata (EPSG:3857)"]),
                "frame": frame,
                "source_site_id": info.get("source_site_id") or (name if name in SCENE_SOURCES else None),
            })
    return scenes


def publish_scene_description(directory: Path) -> None:
    """Publish metadata independently of locks protecting large scene inputs."""
    info = _read_json(directory / "scene.json") if (directory / "scene.json").is_file() else {}
    missing = missing_scene_files(directory)
    frame = scene_frame_info(directory) if not missing else source_scene_frame_info(directory.name)
    item = {"id": directory.name, "title": info.get("title") or scene_title(directory.name),
            "ready": not missing and frame is not None, "read_only": bool(info.get("read_only", False)),
            "default": bool(info.get("default", directory.name == DEFAULT_SCENE)), "missing": missing,
            "frame": frame, "source_site_id": info.get("source_site_id")}
    _write_scene_description(directory.parent, item)


def _write_scene_description(root: Path, item: dict) -> None:
    catalog = root / ".catalog"
    catalog.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".description-", dir=catalog)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(item, stream, ensure_ascii=False, allow_nan=False)
        os.replace(name, catalog / f"{item['id']}.json")
    finally:
        Path(name).unlink(missing_ok=True)


def initialize_scene_catalog(root: str | Path | None = None) -> None:
    base = scenes_root(root)
    for item in _scan_scene_descriptions(root):
        _write_scene_description(base, item)


def list_scenes(root: str | Path | None = None) -> list[dict[str, Any]]:
    base = scenes_root(root)
    catalog = base / ".catalog"
    # Direct Python callers get the same one-time migration as API startup.
    if not catalog.is_dir():
        initialize_scene_catalog(root)
    items = []
    for path in catalog.glob("*.json"):
        if path.stem != DEFAULT_SCENE and not (base / path.stem).is_dir() and not (base / ".previous" / path.stem).is_dir():
            continue
        try:
            items.append(_read_json(path))
        except FileNotFoundError:
            continue  # A concurrently deleted descriptor is no longer a listed scene.
    return sorted(items, key=lambda item: (not item["default"], item["id"]))
