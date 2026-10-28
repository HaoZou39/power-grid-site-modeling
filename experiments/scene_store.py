"""Prepared site scenes. Optimization reads these files and does not rebuild them."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import numpy as np

from config.project_config import load_default_config
from data_tools.io_utils import write_json
from experiments.problem_context import context_from_arrays
from experiments.scene_lock import scene_write_lock

Progress = Callable[[float, str, str], None]
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

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
OBSTACLE_OVERLAY = "obstacle_overlay.png"
DEM_OVERLAY = "dem_elevation.png"
DEM_OVERLAY_METADATA = "dem_elevation.json"
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


def missing_scene_files(path: Path) -> list[str]:
    names = (*SCENE_ARRAYS, SCENE_METADATA)
    return [name for name in names if not (path / name).is_file()]


def ensure_scene_readable(path: str | Path) -> None:
    marker = Path(path) / ROAD_REBUILD_MARKER
    if marker.exists():
        raise RuntimeError(f"场景道路数据正在安全切换或等待恢复，请检查保护标记：{marker}")


def ensure_scene_writable(path: Path) -> None:
    record = path / "scene.json"
    if record.is_file() and _read_json(record).get("read_only"):
        raise ValueError(f"历史场景 {path.name} 已封存，只能查看；请切换到新的 UTM 场景")


def load_scene(
    scene_name: str,
    device: Any,
    root: str | Path | None = None,
    *,
    road_setback_m: float,
    water_setback_m: float,
    highway_setback_m: float,
):
    """Load one finished scene onto the requested device."""

    path = scene_directory(scenes_root(root), scene_name)
    with scene_write_lock(scene_name, path.parent, blocking=True):
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
        ensure_scene_readable(path)
        _validate_road_arrays(arrays["road_segments"], arrays["road_voronoi"], arrays["dem"].shape, arrays["road_segment_kinds"])
        from experiments.scene_version import scene_data_version
        metadata = {**metadata, "scene_id": path.name, "scene_dir": str(path),
                    "data_version": scene_data_version(path, metadata)}
        from experiments.base_constraint_cache import scene_buffer_sources
        sources = scene_buffer_sources(path, arrays["dem"].shape)
    return context_from_arrays(
        arrays,
        device,
        road_setback_m=road_setback_m,
        water_setback_m=water_setback_m,
        highway_setback_m=highway_setback_m,
        sources=sources,
    ), metadata


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


def detach_shared_file(path: Path) -> None:
    """Keep the bytes and permissions, but isolate a file shared with an experiment."""

    if not path.exists() or path.stat().st_nlink <= 1:
        return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(path, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_road_file(source: Path, destination: Path) -> None:
    detach_shared_file(destination)
    # Copy over the existing inode/file so Windows bind-mount ACLs remain readable by Docker.
    shutil.copyfile(source, destination)


def publish_road_bundle(scene: Path, staged: Path, backup_root: Path, product_id: str, *,
                        files: tuple[str, ...] = ROAD_PRODUCT_FILES, remove_files: tuple[str, ...] = ()) -> Path:
    """Publish while the caller holds scene_write_lock; failed recovery stays blocked."""

    ensure_scene_readable(scene)
    ensure_scene_writable(scene)
    from experiments.scene_version import write_scene_revision
    if SCENE_METADATA not in files:
        files = (*files, SCENE_METADATA)
    version_source = staged / SCENE_METADATA
    metadata = _read_json(version_source if version_source.is_file() else scene / SCENE_METADATA)
    write_scene_revision(staged, metadata)
    missing = [name for name in files if name not in remove_files and not (staged / name).is_file()]
    if missing:
        raise FileNotFoundError(f"road publication is missing candidate files: {', '.join(missing)}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_root.expanduser().resolve() / scene.name / f"{stamp}-{uuid4().hex[:8]}"
    backup.mkdir(parents=True, exist_ok=False)
    absent = [name for name in files if not (scene / name).is_file()]
    for name in files:
        if name not in absent:
            shutil.copy2(scene / name, backup / name)

    marker = scene / ROAD_REBUILD_MARKER
    with marker.open("x", encoding="utf-8") as stream:
        json.dump({"road_product_id": product_id, "backup": str(backup), "absent_files": absent, "files": list(files)}, stream)
    try:
        for name in files:
            if name in remove_files:
                (scene / name).unlink(missing_ok=True)
            else:
                _publish_road_file(staged / name, scene / name)
    except Exception as publication_error:
        try:
            for name in files:
                if name in absent:
                    (scene / name).unlink(missing_ok=True)
                else:
                    _publish_road_file(backup / name, scene / name)
        except Exception as rollback_error:
            raise RuntimeError(
                f"道路发布失败且回滚失败，场景保持不可读。备份目录：{backup}；保护标记：{marker}。"
                f"发布错误：{publication_error}；回滚错误：{rollback_error}"
            ) from rollback_error
        marker.unlink()
        raise
    else:
        marker.unlink()
    from experiments.import_retention import record_successful_backup
    record_successful_backup(backup, scene)
    return backup


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
        title = scene_title(scene_name)
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
        "source_mtime_ns": source.stat().st_mtime_ns,
    }
    destination = output_dir or scene_dir
    destination.mkdir(parents=True, exist_ok=True)
    from data_tools.display_grid import project_overlay_rgba

    frame = scene_frame_info(scene_dir)
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
            road_meta = _read_json(path / SCENE_METADATA).get("road", {})
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
    from experiments.scene_version import scene_data_version

    if not supported_crs(crs):
        return None
    frame = {"crs": crs, "transform": transform, "width": width, "height": height}
    return {**frame, "display_frame": display_grid(frame), "frame_id": frame_id(frame),
            "scene_revision": scene_data_version(scene_dir, metadata)["scene_revision"], "units": metadata.get("coordinate_units", "web_mercator_projected_m")}


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


def list_scenes(root: str | Path | None = None) -> list[dict[str, Any]]:
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
                "title": scene_title(name) if name in SCENE_SOURCES else str(info.get("title") or scene_title(name)),
                "ready": not missing and frame is not None,
                "read_only": bool(info.get("read_only", False)),
                "default": bool(info.get("default", name == DEFAULT_SCENE)),
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
