"""Fuse the built-in water polygons into a scene's class-5 land use.

The polygons stay in ``masking_pipeline/data/regional/``, next to the regional OSM
and DEM. Only ``fclass=water`` is burned. This module does not invent polygons,
and it does not add a setback. Building clearance is applied later from
``landuse == 5``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

WATER_CLASS = 5
SOURCE_NAME = "water_polygons"
SOURCE_REL = "masking_pipeline/data/regional"
# A correct projection of a scene-sized query stays near the scene. Tens of kilometres means the CRS was wrong.
MAX_PROJECTION_GAP_M = 20_000.0
# riverbank polygons cover land. reservoir, wetland and dock are not burned either.
INCLUDED_FCLASS = frozenset({"water"})


def water_polygon_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "masking_pipeline" / "data" / "regional"


def rasterize_official_water(frame: dict[str, Any], shape: tuple[int, int]) -> tuple[np.ndarray, dict[str, Any]]:
    """Burn scene-intersecting water polygons onto the scene grid.

    An empty intersection keeps the remote-sensing water already in ``landuse``.
    A CRS that throws the polygons far from the scene aborts the build.
    """

    if (int(frame["height"]), int(frame["width"])) != shape:
        raise ValueError(
            f"官方水系栅格尺寸 {shape} 与场景地理参考 "
            f"{frame['height']}×{frame['width']} 不一致"
        )
    paths = _require_sidecars()
    from experiments.protected_farmland import (
        POLYGON_TYPES,
        FarmlandImportError,
        _burn,
        _clip_to_scene,
        _polygonal,
        _rings_to_polygon,
        _scene_bounds,
        _source_crs,
        _transform_rings,
    )

    prj_text = paths["prj"].read_text(encoding="utf-8", errors="replace").strip()
    if not prj_text:
        raise ValueError(f"{SOURCE_REL}/water_polygons.prj 为空，无法识别水系坐标系")
    try:
        source_crs = _source_crs(prj_text)
    except FarmlandImportError as exc:
        raise ValueError(f"官方水系面无法识别源坐标系：{exc}") from exc
    encoding = paths["cpg"].read_text(encoding="ascii", errors="replace").strip() or None
    query = _source_query_bbox(frame, source_crs)
    parsed, candidates, failed = _read_scene_polygons(
        paths["shp"],
        encoding,
        source_crs,
        query,
        POLYGON_TYPES,
        _transform_rings,
        _rings_to_polygon,
        _polygonal,
        frame["crs"],
    )
    if failed:
        shown = "、".join(str(item) for item in failed[:8])
        extra = "" if len(failed) <= 8 else f" 等 {len(failed)} 个"
        raise ValueError(f"官方水系面第 {shown}{extra} 个场景内图斑无法修复为有效多边形，已中止构建")
    included: dict[str, int] = {}
    skipped: dict[str, int] = {}
    clipped: list[Any] = []
    try:
        for geometry, fclass in parsed:
            hit = _clip_to_scene([geometry], frame)
            if not hit:
                continue
            if fclass in INCLUDED_FCLASS:
                clipped.extend(hit)
                included[fclass] = included.get(fclass, 0) + 1
            else:
                skipped[fclass] = skipped.get(fclass, 0) + 1
    except FarmlandImportError as exc:
        raise ValueError(f"官方水系面与场景范围求交失败：{exc}") from exc
    if parsed and not included and not skipped:
        _require_projection_near_scene([geometry for geometry, _fclass in parsed], _scene_bounds(frame))
    if clipped:
        try:
            mask = _burn(clipped, frame, shape)
        except FarmlandImportError as exc:
            raise ValueError(f"官方水系面栅格化失败：{exc}") from exc
    else:
        mask = np.zeros(shape, dtype=bool)
    if mask.shape != shape:
        raise ValueError(f"官方水系栅格 {mask.shape} 与 landuse {shape} 不一致")
    authority = source_crs.to_authority()
    source_label = f"{authority[0]}:{authority[1]}" if authority else source_crs.name
    return mask, {
        "source_path": f"{SOURCE_REL}/water_polygons.shp",
        "source_crs": source_label,
        "source_crs_wkt": source_crs.to_wkt(),
        "scene_crs": frame["crs"],
        "candidate_feature_count": candidates,
        "intersecting_feature_count": sum(included.values()) + sum(skipped.values()),
        "included_fclass_counts": dict(sorted(included.items())),
        "skipped_fclass_counts": dict(sorted(skipped.items())),
        "raster_cells": int(np.count_nonzero(mask)),
    }


def frame_from_dem_metadata(dem_meta: dict[str, Any], shape: tuple[int, int]) -> dict[str, Any]:
    """The same projected frame ``scene_frame_info`` accepts, checked before burning."""

    crs = dem_meta.get("reference_crs")
    transform = dem_meta.get("target_transform")
    recorded = dem_meta.get("shape")
    from data_tools.display_grid import supported_crs

    if not supported_crs(crs):
        raise ValueError(f"场景参考坐标系必须是 EPSG:3857 或 WGS84 UTM，实际为 {crs!r}")
    if not isinstance(transform, (list, tuple)) or len(transform) != 6:
        raise ValueError("场景 DEM 缺少 target_transform，不能融合官方水系")
    if not isinstance(recorded, (list, tuple)) or list(recorded) != [int(shape[0]), int(shape[1])]:
        raise ValueError(
            f"DEM 记录的网格 {recorded} 与 landuse {[int(shape[0]), int(shape[1])]} 不一致，不能融合官方水系"
        )
    values = [float(item) for item in transform]
    if not all(math.isfinite(item) for item in values) or values[0] <= 0 or values[4] >= 0:
        raise ValueError("场景仿射变换无效，不能融合官方水系")
    if abs(values[1]) > 1e-8 or abs(values[3]) > 1e-8:
        raise ValueError("场景仿射变换含有旋转或错切，不能融合官方水系")
    return {"crs": str(crs), "transform": values, "width": int(shape[1]), "height": int(shape[0])}


def fuse_official_water(
    landuse: np.ndarray,
    dem_meta: dict[str, Any],
    obstacle_classes: tuple[int, ...],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Paint official water onto class 5 and rebuild the obstacle mask from that grid."""

    grid = np.asarray(landuse)
    if grid.ndim != 2:
        raise ValueError(f"landuse must be 2D before official water fusion, got {grid.shape}")
    frame = frame_from_dem_metadata(dem_meta, grid.shape)
    mask, meta = rasterize_official_water(frame, grid.shape)
    updated = np.array(grid, dtype=np.int32, copy=True)
    meta = {**meta, "added_cells": int(np.count_nonzero(mask & (updated != WATER_CLASS)))}
    updated[mask] = WATER_CLASS
    classes = np.asarray(tuple(obstacle_classes), dtype=np.int32)
    obstacle = np.isin(updated, classes).astype(np.float32)
    return updated, obstacle, meta


def _require_sidecars() -> dict[str, Path]:
    directory = water_polygon_dir()
    paths = {suffix: directory / f"{SOURCE_NAME}.{suffix}" for suffix in ("shp", "shx", "dbf", "prj", "cpg")}
    missing = [path.name for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "缺少内置水系面数据，请将 "
            + "、".join(missing)
            + f" 放到 {SOURCE_REL}/。不会猜测或生成这些文件。"
        )
    return paths


def _source_query_bbox(frame: dict[str, Any], source_crs) -> tuple[float, float, float, float]:
    """Scene extent in the shapefile CRS, padded so a borderline polygon is not dropped."""

    from experiments.protected_farmland import _scene_bounds
    from pyproj import Transformer

    inverse = Transformer.from_crs(frame["crs"], source_crs, always_xy=True)
    minx, miny, maxx, maxy = _scene_bounds(frame)
    xs, ys = inverse.transform([minx, maxx, minx, maxx], [miny, miny, maxy, maxy])
    if not np.isfinite(xs).all() or not np.isfinite(ys).all():
        raise ValueError("场景范围无法转换到水系面坐标系，已中止构建")
    pad = 0.02 if source_crs.is_geographic else 2_000.0
    return (
        float(np.min(xs)) - pad,
        float(np.min(ys)) - pad,
        float(np.max(xs)) + pad,
        float(np.max(ys)) + pad,
    )


def _bbox_hits(shape, query: tuple[float, float, float, float]) -> bool:
    bbox = getattr(shape, "bbox", None)
    if not bbox or len(bbox) < 4:
        return True
    sx0, sy0, sx1, sy1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    qminx, qminy, qmaxx, qmaxy = query
    return not (sx1 < qminx or sx0 > qmaxx or sy1 < qminy or sy0 > qmaxy)


def _read_scene_polygons(
    shp_path: Path,
    encoding: str | None,
    source_crs,
    query: tuple[float, float, float, float],
    polygon_types: set[int],
    transform_rings,
    rings_to_polygon,
    polygonal,
    target_crs="EPSG:3857",
) -> tuple[list[tuple[Any, str]], int, list[int]]:
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
            raise ValueError(f"无法按 .cpg 指定的编码 {encoding} 读取水系面属性表") from None
        reader = shapefile.Reader(str(shp_path.with_suffix("")), encoding="gbk")
    field_names = [field[0] for field in reader.fields[1:]]
    if "fclass" not in field_names:
        reader.close()
        raise ValueError(f"{SOURCE_REL}/water_polygons.shp 属性表缺少 fclass，不能筛选水体类别")
    fclass_at = field_names.index("fclass")
    parsed: list[tuple[Any, str]] = []
    candidates = 0
    polygon_count = 0
    failed: list[int] = []
    try:
        for index, item in enumerate(reader.iterShapeRecords(), start=1):
            shape = item.shape
            if shape.shapeType == 0 or not shape.points:
                continue
            if shape.shapeType in polygon_types:
                polygon_count += 1
            if not _bbox_hits(shape, query):
                continue
            if shape.shapeType not in polygon_types:
                raise ValueError(f"官方水系面第 {index} 个场景内要素不是面，只接受 Polygon 或 MultiPolygon")
            candidates += 1
            try:
                rings = transform_rings(shape, transformer)
                geometry = rings_to_polygon(rings, Polygon) if rings else None
                if geometry is not None and not geometry.is_valid:
                    geometry = make_valid(geometry)
                geometry = polygonal(geometry, GeometryCollection, Polygon, MultiPolygon)
            except Exception:
                geometry = None
            if geometry is None or geometry.is_empty:
                failed.append(index)
                continue
            parsed.append((geometry, str(item.record[fclass_at]).strip()))
    finally:
        reader.close()
    if polygon_count == 0:
        raise ValueError(f"{SOURCE_REL}/water_polygons.shp 中没有可用的面图斑")
    return parsed, candidates, failed


def _require_projection_near_scene(geometries, scene_bounds: tuple[float, float, float, float]) -> None:
    gap = min(_box_gap(geometry.bounds, scene_bounds) for geometry in geometries)
    if gap > MAX_PROJECTION_GAP_M:
        raise ValueError(
            "官方水系面转换到场景投影后与场景范围相距超过 "
            f"{int(MAX_PROJECTION_GAP_M / 1000)} km，已中止构建，避免把错位水体写入土地分类"
        )


def _box_gap(
    bounds: tuple[float, float, float, float],
    scene_bounds: tuple[float, float, float, float],
) -> float:
    dx = max(0.0, bounds[0] - scene_bounds[2], scene_bounds[0] - bounds[2])
    dy = max(0.0, bounds[1] - scene_bounds[3], scene_bounds[1] - bounds[3])
    return math.hypot(dx, dy)
