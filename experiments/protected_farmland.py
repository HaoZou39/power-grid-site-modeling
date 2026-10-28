"""Permanent basic farmland as its own scene mask.

The mask is not land-use class 1. Building footprints treat burned cells as hard
obstacles. New access roads also stay off a distance buffer of those cells.
Scenes without the mask keep the previous constraints.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

MASK_NAME = "protected_farmland_mask_1m.npy"
META_NAME = "protected_farmland_import.json"
OVERLAY_NAME = "protected_farmland.png"
SOURCE_NAME = "protected_farmland_source.zip"
PREVIEW_DIRNAME = ".protected_farmland_preview"
OVERLAY_COLOR = (168, 50, 143, 160)
TARGET_CRS = "EPSG:3857"
POLYGON_TYPES = {5, 15, 25}
MAX_ZIP_BYTES = 80 * 1024 * 1024
MAX_UNZIP_BYTES = 400 * 1024 * 1024
MAX_ZIP_MEMBERS = 32
_TOKEN_CHARS = set("0123456789abcdef")


class FarmlandImportError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def mask_path(scene_dir: str | Path) -> Path:
    return Path(scene_dir) / MASK_NAME


def meta_path(scene_dir: str | Path) -> Path:
    return Path(scene_dir) / META_NAME


def overlay_path(scene_dir: str | Path) -> Path:
    return Path(scene_dir) / OVERLAY_NAME


def load_mask(scene_dir: str | Path, shape: tuple[int, int]) -> np.ndarray | None:
    """Return the saved boolean mask, or None when this scene has no farmland layer."""

    path = mask_path(scene_dir)
    if not path.is_file():
        return None
    mask = np.load(path)
    if mask.shape != shape:
        raise ValueError(
            f"永久基本农田栅格尺寸 {mask.shape} 与场景网格 {shape} 不一致"
        )
    return np.asarray(mask, dtype=bool)


def access_road_width_m() -> float:
    """Total width of a new access road. The blocked radius is half of this."""

    from config.project_config import load_default_config

    width = float(load_default_config().data.protected_farmland_access_width_m)
    if not math.isfinite(width) or width < 0 or width > 40:
        raise ValueError("protected_farmland_access_width_m 必须是 0 到 40 之间的有限值")
    return width


def dilate_mask(mask: np.ndarray, width_m: float) -> np.ndarray:
    """Cells whose centre is within half the road width of a farmland cell.

    This is the same 1 m distance-transform approximation used for road setback.
    A width of 0 blocks only the farmland cells themselves.
    """

    blocked = np.asarray(mask, dtype=bool)
    if width_m <= 0 or not blocked.any():
        return blocked
    from scipy.ndimage import distance_transform_edt

    distance = distance_transform_edt(~blocked)
    return distance <= (width_m / 2.0)


def burn_farmland(
    hard_mask: np.ndarray,
    soft_mask: np.ndarray,
    farmland: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """OR exact farmland cells into both masks. ``None`` leaves the masks unchanged."""

    if farmland is None:
        return hard_mask, soft_mask
    if soft_mask.shape != hard_mask.shape or np.asarray(farmland).shape != hard_mask.shape:
        raise ValueError("hard and soft masks must share one shape")
    burned = np.asarray(farmland).astype(np.float32, copy=False)
    return np.maximum(hard_mask, burned), np.maximum(soft_mask, burned)


def stamp_constraint_masks(
    scene_dir: str | Path,
    hard_mask: np.ndarray,
    soft_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """OR the exact farmland cells into both masks. Policy cannot clear them."""

    mask = load_mask(scene_dir, hard_mask.shape)
    if mask is None:
        return hard_mask, soft_mask
    if soft_mask.shape != hard_mask.shape:
        raise ValueError("hard and soft masks must share one shape")
    return burn_farmland(hard_mask, soft_mask, mask)


def access_inputs(
    scene_dir: str | Path,
    hard_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Walkable cells, and the dilated mask new connectors must not touch.

    The second value stays None when the scene has no farmland file, so haul
    caches built before this layer keep their previous key.
    """

    from experiments.base_constraint_cache import cached_farmland_buffer, stamp_file

    path = mask_path(scene_dir)
    before = stamp_file(path)
    mask = load_mask(scene_dir, hard_mask.shape)
    after = stamp_file(path)
    walkable = np.asarray(hard_mask) == 0
    if mask is None:
        return walkable, None
    width = access_road_width_m()
    # Stat twice so a file replaced between the stamp and the read is not cached under the old identity.
    if before is not None and before == after:
        blocked = cached_farmland_buffer(before, width, hard_mask.shape, lambda: dilate_mask(mask, width))
    else:
        blocked = dilate_mask(mask, width)
    return walkable & ~blocked, blocked


def farmland_file_signature(scene_dir: str | Path) -> tuple[str, int, int] | None:
    path = mask_path(scene_dir)
    if not path.is_file():
        return None
    stat = path.stat()
    return (MASK_NAME, stat.st_mtime_ns, stat.st_size)


def layer_info(scene_dir: str | Path) -> dict[str, Any]:
    directory = Path(scene_dir)
    path = mask_path(directory)
    if not path.is_file():
        return {"available": False}
    info: dict[str, Any] = {"available": True, "overlay": overlay_path(directory).is_file()}
    meta = meta_path(directory)
    if meta.is_file():
        import json

        try:
            saved = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            info["error"] = "永久基本农田导入说明无法读取"
            return info
        if isinstance(saved, dict):
            for key in (
                "source_name",
                "source_crs",
                "feature_count",
                "intersecting_feature_count",
                "area_m2",
                "access_road_width_m",
                "osm_overlap_cells",
                "imported_at",
                "content_sha256",
            ):
                if key in saved:
                    info[key] = saved[key]
    info["osm_overlap_cells"] = current_access_overlap(directory)
    return info


def overlay_file(scene_dir: str | Path) -> Path:
    path = overlay_path(scene_dir)
    if not path.is_file():
        raise FileNotFoundError("当前场景还没有永久基本农田图层")
    return path


def preview_overlay_file(scene_dir: str | Path, token: str) -> Path:
    path = _preview_dir(scene_dir, token) / OVERLAY_NAME
    if not path.is_file():
        raise FarmlandImportError("预览已失效，请重新选择压缩包", status=404)
    return path


def preview_zip(scene_dir: str | Path, filename: str, payload: bytes) -> dict[str, Any]:
    """Parse a shapefile zip and write a preview that does not replace the layer."""

    directory = Path(scene_dir)
    _require_scene_grid(directory)
    if len(payload) > MAX_ZIP_BYTES:
        raise FarmlandImportError(f"压缩包不能超过 {MAX_ZIP_BYTES // (1024 * 1024)} MB", status=413)
    token = uuid4().hex
    preview_root = directory / PREVIEW_DIRNAME
    preview_root.mkdir(exist_ok=True)
    for child in preview_root.iterdir():
        if child.name != token:
            shutil.rmtree(child, ignore_errors=True)
    destination = preview_root / token
    destination.mkdir()
    try:
        summary = _rasterize_zip(directory, destination, filename, payload)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    summary["token"] = token
    summary["scene_id"] = directory.name
    summary["saved"] = False
    from data_tools.io_utils import write_json

    write_json(destination / "summary.json", summary)
    return summary


def commit_preview(scene_dir: str | Path, token: str) -> dict[str, Any]:
    """Replace this scene's farmland layer with a preview the user already checked."""

    directory = Path(scene_dir)
    from experiments.scene_store import ensure_scene_writable
    ensure_scene_writable(directory)
    destination = _preview_dir(directory, token)
    summary_path = destination / "summary.json"
    preview_mask = destination / MASK_NAME
    if not summary_path.is_file() or not preview_mask.is_file():
        raise FarmlandImportError("预览已失效，请重新选择压缩包", status=404)
    import json

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FarmlandImportError("预览已失效，请重新选择压缩包", status=404) from exc
    if not isinstance(summary, dict):
        raise FarmlandImportError("预览已失效，请重新选择压缩包", status=404)
    current_grid = _grid_signature(directory)
    if summary.get("grid_signature") != current_grid:
        raise FarmlandImportError("场景网格已经变化，请重新预览后再导入")
    mask = np.load(preview_mask)
    expected = _scene_shape(directory)
    if mask.shape != expected or not np.asarray(mask).any():
        raise FarmlandImportError("预览栅格与当前场景不一致，请重新预览")
    record = {key: value for key, value in summary.items() if key not in {"token", "saved"}}
    record["saved"] = True
    record["imported_at"] = datetime.now(timezone.utc).isoformat()
    record["content_sha256"] = _array_sha256(np.asarray(mask, dtype=bool))
    record["access_road_width_m"] = access_road_width_m()
    _publish_layer(directory, np.asarray(mask, dtype=bool), record, destination / OVERLAY_NAME)
    shutil.copy2(destination / SOURCE_NAME, directory / SOURCE_NAME)
    from experiments.scene_version import write_scene_revision
    write_scene_revision(directory)
    shutil.rmtree(destination, ignore_errors=True)
    invalidate_runtime_caches()
    return record


def delete_layer(scene_dir: str | Path) -> None:
    directory = Path(scene_dir)
    from experiments.scene_lock import scene_write_lock
    with scene_write_lock(directory.name, directory.parent):
        from experiments.scene_store import ensure_scene_writable
        ensure_scene_writable(directory)
        for path in (mask_path(directory), meta_path(directory), overlay_path(directory)):
            if path.is_file():
                path.unlink()
        shutil.rmtree(directory / PREVIEW_DIRNAME, ignore_errors=True)
        from experiments.scene_version import write_scene_revision
        write_scene_revision(directory)
        invalidate_runtime_caches()


def invalidate_runtime_caches() -> None:
    from experiments.base_constraint_cache import clear_base_constraint_cache
    from experiments.launch_site_run import _scored_scene
    from experiments.site_report import clear_site_report_cache

    _scored_scene.cache_clear()
    clear_site_report_cache()
    clear_base_constraint_cache()


def _require_scene_grid(scene_dir: Path) -> None:
    if not (scene_dir / "dem_1m.npy").is_file() or not (scene_dir / "landuse_1m.npy").is_file():
        raise FarmlandImportError("目标场景尚未准备完成，不能导入永久基本农田", status=409)
    frame = _frame(scene_dir)
    if frame is None:
        raise FarmlandImportError("目标场景缺少可用的投影网格地理参考，不能对齐永久基本农田", status=409)


def _scene_shape(scene_dir: Path) -> tuple[int, int]:
    dem = np.load(scene_dir / "dem_1m.npy", mmap_mode="r")
    landuse = np.load(scene_dir / "landuse_1m.npy", mmap_mode="r")
    if dem.shape != landuse.shape or dem.ndim != 2:
        raise FarmlandImportError("场景 DEM 与用地栅格尺寸不一致，不能导入")
    frame = _frame(scene_dir)
    if frame is None or (frame["height"], frame["width"]) != dem.shape:
        raise FarmlandImportError("场景地理参考与 1 m 栅格尺寸不一致，不能导入")
    return dem.shape


def _frame(scene_dir: Path) -> dict[str, Any] | None:
    from experiments.scene_store import scene_frame_info

    return scene_frame_info(scene_dir)


def _grid_signature(scene_dir: Path) -> str:
    frame = _frame(scene_dir)
    dem = scene_dir / "dem_1m.npy"
    landuse = scene_dir / "landuse_1m.npy"
    stat_dem = dem.stat()
    stat_landuse = landuse.stat()
    payload = (
        f"{frame['crs']}|{frame['height']}x{frame['width']}|{frame['transform']}|"
        f"{stat_dem.st_mtime_ns}:{stat_dem.st_size}|{stat_landuse.st_mtime_ns}:{stat_landuse.st_size}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preview_dir(scene_dir: Path, token: str) -> Path:
    if len(token) != 32 or any(char not in _TOKEN_CHARS for char in token):
        raise FarmlandImportError("预览已失效，请重新选择压缩包", status=404)
    return scene_dir / PREVIEW_DIRNAME / token


def _rasterize_zip(scene_dir: Path, destination: Path, filename: str, payload: bytes) -> dict[str, Any]:
    shape = _scene_shape(scene_dir)
    frame = _frame(scene_dir)
    assert frame is not None
    (destination / SOURCE_NAME).write_bytes(payload)
    extracted = destination / "source"
    extracted.mkdir()
    members = _extract_zip(payload, extracted)
    prj_text, encoding = _read_sidecars(members)
    source_crs = _source_crs(prj_text)
    geometries, feature_count, empty_count = _read_polygons(members["shp"], encoding, source_crs, frame["crs"])
    intersecting = _clip_to_scene(geometries, frame)
    if not intersecting:
        raise FarmlandImportError("图斑与当前场景没有相交，没有写入禁建数据")
    mask = _burn(intersecting, frame, shape)
    area = int(np.count_nonzero(mask))
    if area <= 0:
        raise FarmlandImportError("图斑与当前场景没有相交，没有写入禁建数据")
    np.save(destination / MASK_NAME, mask)
    _write_overlay(mask, destination / OVERLAY_NAME, frame)
    overlap = _osm_overlap(scene_dir, mask)
    authority = source_crs.to_authority()
    source_label = f"{authority[0]}:{authority[1]}" if authority else source_crs.name
    return {
        "source_name": Path(filename).name or "protected_farmland.zip",
        "source_zip_sha256": hashlib.sha256(payload).hexdigest(),
        "source_crs": source_label,
        "source_crs_wkt": source_crs.to_wkt(),
        "scene_crs": frame["crs"],
        "feature_count": feature_count,
        "empty_feature_count": empty_count,
        "intersecting_feature_count": len(intersecting),
        "area_m2": area,
        "osm_overlap_cells": overlap,
        "access_road_width_m": access_road_width_m(),
        "grid_signature": _grid_signature(scene_dir),
        "content_sha256": _array_sha256(mask),
        "version": 1,
    }


def _extract_zip(payload: bytes, destination: Path) -> dict[str, Path]:
    from io import BytesIO

    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise FarmlandImportError("请上传包含 shp、shx、dbf、prj 的 ZIP 压缩包") from exc
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > MAX_ZIP_MEMBERS:
        raise FarmlandImportError(f"压缩包内文件不能超过 {MAX_ZIP_MEMBERS} 个")
    written: dict[str, Path] = {}
    total = 0
    for info in infos:
        name = info.filename.replace("\\", "/")
        parts = Path(name).parts
        if not parts or name.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise FarmlandImportError("压缩包包含不安全路径，已拒绝解压")
        suffix = Path(parts[-1]).suffix.lower()
        if suffix not in {".shp", ".shx", ".dbf", ".prj", ".cpg"}:
            continue
        if suffix in written:
            raise FarmlandImportError("压缩包里有多套同类型文件，请只保留一套 Shapefile")
        with archive.open(info) as source:
            blob = source.read(MAX_UNZIP_BYTES - total + 1)
        total += len(blob)
        if total > MAX_UNZIP_BYTES:
            raise FarmlandImportError("解压后的总体积超过限制")
        target = destination / f"farmland{suffix}"
        target.write_bytes(blob)
        written[suffix.lstrip(".")] = target
    missing = [suffix for suffix in ("shp", "shx", "dbf", "prj") if suffix not in written]
    if missing:
        raise FarmlandImportError(f"压缩包缺少 {', '.join(missing)} 文件")
    return written


def _read_sidecars(members: dict[str, Path]) -> tuple[str, str | None]:
    prj_text = members["prj"].read_text(encoding="utf-8", errors="replace").strip()
    if not prj_text:
        raise FarmlandImportError("prj 为空，无法识别源坐标系")
    encoding = None
    if "cpg" in members:
        encoding = members["cpg"].read_text(encoding="ascii", errors="replace").strip() or None
    return prj_text, encoding


def _source_crs(prj_text: str):
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    try:
        crs = CRS.from_wkt(prj_text)
    except CRSError as exc:
        raise FarmlandImportError("无法根据 prj 内容识别源坐标系，没有猜测坐标") from exc
    if crs is None:
        raise FarmlandImportError("无法根据 prj 内容识别源坐标系，没有猜测坐标")
    return crs


def _read_polygons(shp_path: Path, encoding: str | None, source_crs, target_crs=TARGET_CRS) -> tuple[list[Any], int, int]:
    import shapefile
    from pyproj import Transformer
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
    from shapely.validation import make_valid

    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    chosen = encoding or "utf-8"
    try:
        reader = shapefile.Reader(str(shp_path.with_suffix("")), encoding=chosen)
    except UnicodeError:
        if encoding:
            raise FarmlandImportError(f"无法按 .cpg 指定的编码 {encoding} 读取属性表") from None
        reader = shapefile.Reader(str(shp_path.with_suffix("")), encoding="gbk")
    geometries = []
    feature_count = 0
    empty_count = 0
    failed: list[int] = []
    try:
        for index, shape in enumerate(reader.iterShapes(), start=1):
            if shape.shapeType == 0 or not shape.points:
                empty_count += 1
                continue
            if shape.shapeType not in POLYGON_TYPES:
                raise FarmlandImportError(f"第 {index} 个要素不是面，只接受 Polygon 或 MultiPolygon")
            feature_count += 1
            try:
                rings = _transform_rings(shape, transformer)
                geometry = _rings_to_polygon(rings, Polygon) if rings else None
                if geometry is not None and not geometry.is_valid:
                    geometry = make_valid(geometry)
                geometry = _polygonal(geometry, GeometryCollection, Polygon, MultiPolygon)
            except Exception:
                geometry = None
            if geometry is None or geometry.is_empty:
                failed.append(index)
                continue
            geometries.append(geometry)
    finally:
        reader.close()
    if failed:
        shown = "、".join(str(item) for item in failed[:8])
        extra = "" if len(failed) <= 8 else f" 等 {len(failed)} 个"
        raise FarmlandImportError(f"第 {shown}{extra} 个图斑无法修复为有效多边形，没有写入数据")
    if feature_count == 0:
        raise FarmlandImportError("Shapefile 中没有可用的面图斑")
    return geometries, feature_count, empty_count


def _transform_rings(shape, transformer) -> list[list[tuple[float, float]]]:
    points = np.asarray(shape.points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2:
        return []
    xs, ys = transformer.transform(points[:, 0], points[:, 1])
    if not np.isfinite(xs).all() or not np.isfinite(ys).all():
        return []
    transformed = np.column_stack((xs, ys))
    parts = list(shape.parts) + [len(shape.points)]
    rings = []
    for start, end in zip(parts, parts[1:]):
        ring = transformed[start:end]
        if len(ring) >= 4:
            rings.append([(float(x), float(y)) for x, y in ring])
    return rings


def _rings_to_polygon(rings, polygon_cls):
    geoms = []
    shell = None
    holes: list[list[tuple[float, float]]] = []
    for ring in rings:
        if shell is None:
            shell = ring
            holes = []
            continue
        container = polygon_cls(shell)
        probe = polygon_cls(ring).representative_point()
        try:
            inside = container.is_valid and bool(container.contains(probe))
        except Exception:
            inside = False
        if inside:
            holes.append(ring)
        else:
            geoms.append(polygon_cls(shell, holes))
            shell = ring
            holes = []
    if shell is not None:
        geoms.append(polygon_cls(shell, holes))
    if not geoms:
        return None
    if len(geoms) == 1:
        return geoms[0]
    from shapely.ops import unary_union

    return unary_union(geoms)


def _polygonal(geometry, collection_cls, polygon_cls, multi_cls):
    from shapely.ops import unary_union

    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, (polygon_cls, multi_cls)):
        return geometry
    if isinstance(geometry, collection_cls):
        parts = [
            part for part in geometry.geoms
            if isinstance(part, (polygon_cls, multi_cls)) and not part.is_empty
        ]
        if not parts:
            return None
        return unary_union(parts)
    return None


def _clip_to_scene(geometries, frame: dict[str, Any]):
    from shapely.geometry import box

    scene_box = box(*_scene_bounds(frame))
    kept = []
    for geometry in geometries:
        try:
            hit = geometry.intersection(scene_box)
        except Exception as exc:
            raise FarmlandImportError(f"图斑与场景范围求交失败：{exc}") from exc
        kept_geom = _keep_polygonal(hit)
        if kept_geom is not None and not kept_geom.is_empty and kept_geom.area > 0:
            kept.append(kept_geom)
    return kept


def _keep_polygonal(geometry):
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
    from shapely.ops import unary_union

    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        parts = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
        if not parts:
            return None
        return unary_union(parts)
    return None


def _scene_bounds(frame: dict[str, Any]) -> tuple[float, float, float, float]:
    transform = frame["transform"]
    width = int(frame["width"])
    height = int(frame["height"])
    corners = []
    for col, row in ((0, 0), (width, 0), (width, height), (0, height)):
        x = transform[0] * col + transform[1] * row + transform[2]
        y = transform[3] * col + transform[4] * row + transform[5]
        corners.append((x, y))
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _burn(geometries, frame: dict[str, Any], shape: tuple[int, int]) -> np.ndarray:
    from rasterio.features import rasterize
    from rasterio.transform import Affine

    transform = frame["transform"]
    affine = Affine(*transform)
    burned = rasterize(
        [(geometry, 1) for geometry in geometries],
        out_shape=shape,
        transform=affine,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )
    if burned.shape != shape:
        raise FarmlandImportError("栅格化结果与场景网格尺寸不一致")
    return burned.astype(bool)


def _osm_overlap(scene_dir: Path, mask: np.ndarray) -> int:
    segments_path = scene_dir / "road_segments_local.npy"
    if not segments_path.is_file():
        return 0
    segments = np.load(segments_path, mmap_mode="r")
    if segments.size == 0:
        return 0
    from modeling.context import rasterize_osm_centerlines

    kinds = np.load(scene_dir / "road_segment_kind.npy")
    roads = rasterize_osm_centerlines(np.asarray(segments)[kinds == 0], mask.shape)
    return int(np.count_nonzero(roads & mask))


def current_access_overlap(scene_dir: Path) -> int:
    paths = [scene_dir / name for name in ("road_segments_local.npy", "road_segment_kind.npy", MASK_NAME)]
    signature = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)
    kind_hash = hashlib.sha256((scene_dir / "road_segment_kind.npy").read_bytes()).hexdigest()
    return _cached_access_overlap(str(scene_dir.resolve()), (*signature, kind_hash))


@lru_cache(maxsize=8)
def _cached_access_overlap(scene_dir: str, signature: tuple) -> int:
    directory = Path(scene_dir)
    mask = np.load(directory / MASK_NAME, mmap_mode="r")
    return _osm_overlap(directory, np.asarray(mask, dtype=bool))


def _write_overlay(mask: np.ndarray, path: Path, frame: dict | None = None) -> None:
    from PIL import Image

    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[np.asarray(mask, dtype=bool)] = OVERLAY_COLOR
    from data_tools.display_grid import project_overlay_rgba

    if frame is not None:
        rgba = project_overlay_rgba(rgba, frame)
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG")


def _array_sha256(mask: np.ndarray) -> str:
    array = np.ascontiguousarray(mask, dtype=bool)
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def _publish_layer(scene_dir: Path, mask: np.ndarray, record: dict[str, Any], preview_overlay: Path) -> None:
    from data_tools.io_utils import write_json

    temporary = Path(tempfile.mkdtemp(dir=scene_dir))
    try:
        mask_tmp = temporary / MASK_NAME
        meta_tmp = temporary / META_NAME
        overlay_tmp = temporary / OVERLAY_NAME
        np.save(mask_tmp, mask)
        write_json(meta_tmp, record)
        if preview_overlay.is_file():
            shutil.copyfile(preview_overlay, overlay_tmp)
        else:
            _write_overlay(mask, overlay_tmp, _frame(scene_dir))
        os.replace(mask_tmp, mask_path(scene_dir))
        os.replace(overlay_tmp, overlay_path(scene_dir))
        os.replace(meta_tmp, meta_path(scene_dir))
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
