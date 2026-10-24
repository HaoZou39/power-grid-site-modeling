"""Fill gaps in class-5 water from built-in river centerlines.

Reliable cross-sections first shift the official line onto the remote-sensing
water center. A short gap with water at both ends is filled by straight lines
between those banks. A longer or one-sided gap stays on the corrected line and
is filled with that line's existing width, not a wider corridor. Samples that
kink or sit beside a different water body are left out. Original road and
building cells are not painted. Width comes from cross-sections on water that
is already in the scene, then from other measured reaches of the same named
river, then from a positive ``width`` attribute, then from a class fallback.
``width == 0`` means the attribute is missing. Filling uses the scene grid,
whose affine pixel size is the meter used here.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

SOURCE_NAME = "water_lines"
SOURCE_REL = "masking_pipeline/data/regional"
# Total width, not radius. Drains and unrecognized classes are not given a width.
CLASS_WIDTH_M = {"river": 10.0, "stream": 4.0, "canal": 4.0}
_CLASS_NAMES = {
    "river": "river",
    "河": "river",
    "江": "river",
    "河/江": "river",
    "stream": "stream",
    "溪": "stream",
    "小河": "stream",
    "溪/小河": "stream",
    "canal": "canal",
    "运河": "canal",
    "明渠": "canal",
    "drain": "drain",
    "排水管": "drain",
    "下水道": "drain",
    "排水管/下水道": "drain",
}
_WIDTH_FIELDS = ("width", "width_m")
_CLASS_FIELDS = ("fclass", "waterway", "type", "class")
_CLASS_CN_FIELDS = ("fclass_cn", "type_cn")
_NAME_FIELDS = ("name", "river_name")
_ID_FIELDS = ("osm_id", "id", "fid")
_LINE_TYPES = {3, 13, 23}
SAMPLE_STEP_M = 8.0
MAX_HALF_WIDTH_M = 40.0
MIN_WIDTH_M = 1.5
MIN_VALID_SAMPLES = 3
# Do not pull a centerline onto a neighboring channel farther than this.
MAX_ALIGN_M = 25.0
# Short holes between reliable centers may be interpolated. Longer ones stay put.
ALIGN_GAP_M = 40.0
# A centerline this close to existing water is the same channel, not a gap.
CENTER_MATCH_M = 2.0
GAP_MIN_M = 12.0
# Level 1 joins both banks only inside this length. Longer dry reaches follow
# the corrected line at the same width; length does not widen the corridor.
RIVER_GAP_SAMPLE_SPACING_M = 5.0
RIVER_GAP_MAX_LENGTH_M = 200.0
RIVER_GAP_MAX_WIDTH_RATIO = 2.5
RIVER_GAP_MAX_END_OFFSET_M = 8.0
# Along-river direction of an end section versus the straight line between the
# two water centers. A larger turn is left unfilled. The official vertices
# between the sections are not part of the new polygon.
MAX_ENDPOINT_DIRECTION_ERROR_DEG = 65.0
# One grid meter past each bank, along that bank, so the polygon overlaps
# water that is already there. It does not push the straight edges sideways.
BANK_SEAM_M = 1.0


def water_line_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "masking_pipeline" / "data" / "regional"


def fuse_water_lines(
    landuse: np.ndarray,
    dem_meta: dict[str, Any],
    obstacle_classes: tuple[int, ...],
    original_landuse: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Buffer estimated river lines onto class 5 without erasing existing water.

    ``original_landuse`` is the remote-sensing grid from before either water
    fusion. Class 2 and class 3 in that grid stay building and road. The
    official line is moved to the remote-sensing center before the width is
    estimated. Those cells are restored only when the result is written.
    """

    from experiments.official_water import WATER_CLASS, frame_from_dem_metadata

    grid = np.asarray(landuse)
    if grid.ndim != 2:
        raise ValueError(f"landuse must be 2D before water-line fusion, got {grid.shape}")
    frame = frame_from_dem_metadata(dem_meta, grid.shape)
    known = grid == WATER_CLASS
    lines, crs_meta = _read_scene_lines(frame)
    satellite = known if original_landuse is None else np.asarray(original_landuse) == WATER_CLASS
    road = _original_class_mask(original_landuse, grid.shape, 3)
    building = _original_class_mask(original_landuse, grid.shape, 2)
    protected = road | building
    _align_lines(lines, satellite, road, frame)
    _assign_widths(lines, known, frame)
    mask = _rasterize_gaps(lines, known, frame, road, building)
    updated = np.array(grid, dtype=np.int32, copy=True)
    updated[mask] = WATER_CLASS
    polygon_road = int(np.count_nonzero(road & (grid == WATER_CLASS)))
    polygon_building = int(np.count_nonzero(building & (grid == WATER_CLASS)))
    added = int(np.count_nonzero(mask & (grid != WATER_CLASS)))
    if protected.any():
        source = np.asarray(original_landuse)
        updated[protected] = source[protected]
    classes = np.asarray(tuple(obstacle_classes), dtype=np.int32)
    obstacle = np.isin(updated, classes).astype(np.float32)
    meta = {
        **crs_meta,
        "intersecting_feature_count": len(lines),
        "added_cells": added,
        "road_excluded_cells": polygon_road + _sum_gap_field(lines, "road_cells"),
        "building_excluded_cells": polygon_building + _sum_gap_field(lines, "building_cells"),
        "rejected_gap_count": _count_fill(lines, ("rejected_geometry",)),
        "official_road_excluded_cells": polygon_road,
        "official_building_excluded_cells": polygon_building,
    }
    return updated, obstacle, meta


def _original_class_mask(original_landuse: np.ndarray | None, shape: tuple[int, int], code: int) -> np.ndarray:
    if original_landuse is None:
        return np.zeros(shape, dtype=bool)
    original = np.asarray(original_landuse)
    if original.shape != shape:
        raise ValueError(f"融合前土地分类 {original.shape} 与当前网格 {shape} 不一致，不能保护遥感道路和建筑")
    # Class 2 is building and class 3 is road, both taken before either water fusion.
    return original == code


def _count_fill(lines: list[dict[str, Any]], fills: tuple[str, ...]) -> int:
    return sum(1 for line in lines for gap in line.get("gaps", []) if gap.get("fill") in fills)


def _sum_gap_field(lines: list[dict[str, Any]], key: str) -> int:
    return sum(int(gap.get(key, 0)) for line in lines for gap in line.get("gaps", []))


def _pixel_size(frame: dict[str, Any]) -> dict[str, float]:
    transform = frame["transform"]
    return {"x": abs(float(transform[0])), "y": abs(float(transform[4]))}


def _require_sidecars() -> dict[str, Path]:
    directory = water_line_dir()
    paths = {suffix: directory / f"{SOURCE_NAME}.{suffix}" for suffix in ("shp", "shx", "dbf", "prj", "cpg")}
    missing = [path.name for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "缺少内置水系线数据，请将 "
            + "、".join(missing)
            + f" 放到 {SOURCE_REL}/。不会猜测或生成这些文件。"
        )
    return paths


def _pick_field(names: list[str], aliases: tuple[str, ...]) -> str | None:
    lookup = {name.lower(): name for name in names}
    for alias in aliases:
        found = lookup.get(alias.lower())
        if found is not None:
            return found
    return None


def _class_key(raw_class: str, raw_cn: str) -> str:
    for value in (raw_class, raw_cn):
        key = _CLASS_NAMES.get(str(value).strip())
        if key is not None:
            return key
    return ""


def _positive_width(value: Any) -> float | None:
    try:
        width = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(width) or width <= 0:
        return None
    return width


def _read_scene_lines(frame: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import shapefile
    from pyproj import Transformer
    from shapely.geometry import LineString, MultiLineString

    from experiments.official_water import _source_query_bbox
    from experiments.protected_farmland import (
        TARGET_CRS,
        FarmlandImportError,
        _scene_bounds,
        _source_crs,
    )

    paths = _require_sidecars()
    prj_text = paths["prj"].read_text(encoding="utf-8", errors="replace").strip()
    if not prj_text:
        raise ValueError(f"{SOURCE_REL}/water_lines.prj 为空，无法识别水系线坐标系")
    try:
        source_crs = _source_crs(prj_text)
    except FarmlandImportError as exc:
        raise ValueError(f"官方水系线无法识别源坐标系：{exc}") from exc
    encoding = paths["cpg"].read_text(encoding="ascii", errors="replace").strip() or None
    query = _source_query_bbox(frame, source_crs)
    transformer = Transformer.from_crs(source_crs, TARGET_CRS, always_xy=True)
    chosen = encoding or "utf-8"
    try:
        reader = shapefile.Reader(str(paths["shp"].with_suffix("")), encoding=chosen)
    except UnicodeError:
        if encoding:
            raise ValueError(f"无法按 .cpg 指定的编码 {encoding} 读取水系线属性表") from None
        reader = shapefile.Reader(str(paths["shp"].with_suffix("")), encoding="gbk")
    field_names = [field[0] for field in reader.fields if field[0] != "DeletionFlag"]
    width_field = _pick_field(field_names, _WIDTH_FIELDS)
    class_field = _pick_field(field_names, _CLASS_FIELDS)
    class_cn_field = _pick_field(field_names, _CLASS_CN_FIELDS)
    name_field = _pick_field(field_names, _NAME_FIELDS)
    id_field = _pick_field(field_names, _ID_FIELDS)
    if width_field is None or (class_field is None and class_cn_field is None):
        reader.close()
        raise ValueError(f"水系线属性表缺少宽度或类别字段，实际字段为：{'、'.join(field_names)}")
    scene_box_bounds = _scene_bounds(frame)
    from shapely.geometry import box

    scene_box = box(*scene_box_bounds)
    lines: list[dict[str, Any]] = []
    line_count = 0
    rejected: list[Any] = []
    try:
        for index, shape in enumerate(reader.iterShapes()):
            if shape.shapeType == 0 or not shape.points:
                continue
            if shape.shapeType in _LINE_TYPES:
                line_count += 1
            if not _bbox_hits(shape, query):
                continue
            if shape.shapeType not in _LINE_TYPES:
                raise ValueError(f"官方水系线第 {index + 1} 个场景内要素不是线")
            record = {name: value for name, value in zip(field_names, reader.record(index))}
            parts = _clip_line(shape, transformer, scene_box, LineString, MultiLineString)
            if parts is None:
                raise ValueError(f"官方水系线第 {index + 1} 条无法转换到场景坐标系，已中止构建")
            if not parts:
                rejected.append(_as_3857_line(shape, transformer, LineString))
                continue
            raw_class = str(record.get(class_field, "") or "").strip() if class_field else ""
            raw_cn = str(record.get(class_cn_field, "") or "").strip() if class_cn_field else ""
            water_type = _class_key(raw_class, raw_cn)
            name = str(record.get(name_field, "") or "").strip() if name_field else ""
            feature_id = str(record.get(id_field, "") or "").strip() if id_field else ""
            lines.append(
                {
                    "feature_id": feature_id or str(index + 1),
                    "river_name": name,
                    "water_type": raw_class or raw_cn or water_type,
                    "class_key": water_type,
                    "attribute_width_m": _positive_width(record.get(width_field)),
                    "parts": parts,
                    "measured": None,
                    "width_m": None,
                    "width_source": "",
                }
            )
    finally:
        reader.close()
    if line_count == 0:
        raise ValueError(f"{SOURCE_REL}/water_lines.shp 中没有可用的线")
    far = [geom for geom in rejected if geom is not None and not geom.is_empty]
    if far and not lines:
        from experiments.official_water import _require_projection_near_scene

        _require_projection_near_scene(far, scene_box_bounds)
    authority = source_crs.to_authority()
    source_label = f"{authority[0]}:{authority[1]}" if authority else source_crs.name
    return lines, {
        "source_path": f"{SOURCE_REL}/water_lines.shp",
        "source_crs": source_label,
        "source_crs_wkt": source_crs.to_wkt(),
        "scene_crs": TARGET_CRS,
    }


def _bbox_hits(shape, query: tuple[float, float, float, float]) -> bool:
    bbox = getattr(shape, "bbox", None)
    if not bbox or len(bbox) < 4:
        return True
    sx0, sy0, sx1, sy1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    qminx, qminy, qmaxx, qmaxy = query
    return not (sx1 < qminx or sx0 > qmaxx or sy1 < qminy or sy0 > qmaxy)


def _as_3857_line(shape, transformer, line_cls):
    points = np.asarray(shape.points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2:
        return None
    xs, ys = transformer.transform(points[:, 0], points[:, 1])
    if not np.isfinite(xs).all() or not np.isfinite(ys).all():
        return None
    if len(xs) < 2:
        return None
    return line_cls(np.column_stack((xs, ys)))


def _clip_line(shape, transformer, scene_box, line_cls, multi_cls) -> list[Any] | None:
    points = np.asarray(shape.points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2:
        return []
    xs, ys = transformer.transform(points[:, 0], points[:, 1])
    if not np.isfinite(xs).all() or not np.isfinite(ys).all():
        return None
    coords = np.column_stack((xs, ys))
    bounds = list(shape.parts) + [len(shape.points)]
    kept: list[Any] = []
    for start, end in zip(bounds, bounds[1:]):
        seg = coords[start:end]
        if len(seg) < 2:
            continue
        hit = line_cls(seg).intersection(scene_box)
        pieces = list(hit.geoms) if isinstance(hit, multi_cls) else [hit]
        for piece in pieces:
            if piece.geom_type == "LineString" and piece.length > 0:
                kept.append(np.asarray(piece.coords, dtype=np.float64))
    return kept


def _align_lines(lines: list[dict[str, Any]], water: np.ndarray, road: np.ndarray, frame: dict[str, Any]) -> None:
    sx, sy = _pixel_size(frame)["x"], _pixel_size(frame)["y"]
    for line in lines:
        if line["class_key"] not in CLASS_WIDTH_M:
            continue
        replaced = []
        moved = False
        for part in line["parts"]:
            samples = _part_samples([part], frame, sx, sy)[0]
            shifted = _shift_samples(samples, water, road, sx, sy)
            if shifted is None:
                replaced.append(part)
                continue
            replaced.append(_pixels_to_3857(shifted, frame))
            moved = True
        if moved:
            line["parts"] = replaced


def _shift_samples(
    samples: np.ndarray,
    water: np.ndarray,
    road: np.ndarray,
    sx: float,
    sy: float,
) -> np.ndarray | None:
    if len(samples) < 2 or not water.any():
        return None
    steps: list[tuple[float, float] | None] = []
    observed: list[tuple[int, float, float]] = []
    for index in range(len(samples)):
        neighbor = samples[min(index + 1, len(samples) - 1)] - samples[max(index - 1, 0)]
        step = _perp_step(float(neighbor[0]), float(neighbor[1]), sx, sy)
        steps.append(step)
        if step is None:
            continue
        offset = _water_center_offset(water, road, float(samples[index, 0]), float(samples[index, 1]), step[0], step[1])
        if offset is None:
            continue
        observed.append((index, offset[0], offset[1]))
    if len(observed) < MIN_VALID_SAMPLES:
        return None
    widths = np.asarray([item[2] for item in observed], dtype=np.float64)
    offsets = np.asarray([item[1] for item in observed], dtype=np.float64)
    mid_width = float(np.median(widths))
    mid_offset = float(np.median(offsets))
    keep = (
        (widths >= max(MIN_WIDTH_M, mid_width * 0.4))
        & (widths <= max(mid_width * 2.5, mid_width + 8.0))
        & (np.abs(offsets - mid_offset) <= 12.0)
    )
    kept = [observed[index] for index in range(len(observed)) if keep[index]]
    if len(kept) < MIN_VALID_SAMPLES:
        return None
    smoothed = _rolling_median([item[1] for item in kept], 5)
    applied = np.zeros(len(samples), dtype=np.float64)
    for (index, _offset, _width), value in zip(kept, smoothed):
        applied[index] = value
    for earlier, later in zip(kept, kept[1:]):
        gap_m = (later[0] - earlier[0]) * SAMPLE_STEP_M
        if gap_m <= 0 or gap_m > ALIGN_GAP_M:
            continue
        start, end = earlier[0], later[0]
        for index in range(start + 1, end):
            weight = (index - start) / (end - start)
            applied[index] = (1.0 - weight) * applied[start] + weight * applied[end]
    if float(np.max(np.abs(applied))) < 0.5:
        return None
    shifted = np.array(samples, dtype=np.float64, copy=True)
    for index, offset in enumerate(applied):
        step = steps[index]
        if step is None or offset == 0.0:
            continue
        shifted[index, 0] = samples[index, 0] + float(offset) * step[0]
        shifted[index, 1] = samples[index, 1] + float(offset) * step[1]
    return shifted


def _water_center_offset(
    water: np.ndarray,
    road: np.ndarray | None,
    col: float,
    row: float,
    dcol: float,
    drow: float,
) -> tuple[float, float] | None:
    """Signed meters from the official sample to the remote-sensing water center."""

    cell = _cell(col, row, water.shape)
    if road is not None and cell is not None and road[cell]:
        return None
    half = int(math.ceil(MAX_ALIGN_M + MAX_HALF_WIDTH_M))
    flags = []
    for meter in range(-half, half + 1):
        hit = _cell(col + meter * dcol, row + meter * drow, water.shape)
        flags.append(hit is not None and bool(water[hit]))
    runs: list[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    closed = [(left, right) for left, right in runs if left > 0 and right < len(flags) - 1]
    if len(closed) != 1:
        return None
    left, right = closed[0]
    center_m = (left + right) / 2.0 - half
    if abs(center_m) > MAX_ALIGN_M:
        return None
    center = _cell(col + center_m * dcol, row + center_m * drow, water.shape)
    if center is None or not water[center]:
        return None
    positive = _bank_distance(water, center, drow, dcol)
    negative = _bank_distance(water, center, -drow, -dcol)
    if positive is None or negative is None:
        return None
    width = positive + negative
    if not (MIN_WIDTH_M <= width <= 2 * MAX_HALF_WIDTH_M):
        return None
    # Positive bank distance is measured along +perpendicular from the snapped center.
    offset = center_m + (positive - negative) / 2.0
    if abs(offset) > MAX_ALIGN_M:
        return None
    return offset, width


def _rolling_median(values: list[float], window: int) -> list[float]:
    half = window // 2
    smoothed = []
    for index in range(len(values)):
        lo = max(0, index - half)
        hi = min(len(values), index + half + 1)
        smoothed.append(float(np.median(values[lo:hi])))
    return smoothed


def _pixels_to_3857(samples: np.ndarray, frame: dict[str, Any]) -> np.ndarray:
    transform = frame["transform"]
    east = transform[0] * samples[:, 0] + transform[2]
    north = transform[4] * samples[:, 1] + transform[5]
    return np.column_stack((east, north))


def _assign_widths(lines: list[dict[str, Any]], known: np.ndarray, frame: dict[str, Any]) -> None:
    sx, sy = _pixel_size(frame)["x"], _pixel_size(frame)["y"]
    for line in lines:
        if line["class_key"] not in CLASS_WIDTH_M:
            line["width_source"] = "excluded"
            continue
        line["measured"] = _cross_sections(known, _part_samples(line["parts"], frame, sx, sy), sx, sy)
    measured_by_name: dict[str, list[float]] = {}
    for line in lines:
        if line["measured"] is not None and line["river_name"]:
            measured_by_name.setdefault(line["river_name"], []).append(float(line["measured"]))
    reference = {name: float(np.median(values)) for name, values in measured_by_name.items()}
    for line in lines:
        if line["width_source"] == "excluded":
            continue
        measured = line["measured"]
        attribute = line["attribute_width_m"]
        if measured is not None:
            line["width_m"] = measured
            line["width_source"] = "satellite_measured"
            continue
        if line["river_name"] and line["river_name"] in reference:
            line["width_m"] = reference[line["river_name"]]
            line["width_source"] = "same_river"
            continue
        if attribute is not None:
            line["width_m"] = attribute
            line["width_source"] = "attribute"
            continue
        line["width_m"] = CLASS_WIDTH_M[line["class_key"]]
        line["width_source"] = "class_fallback"


def _part_samples(
    parts: list[np.ndarray],
    frame: dict[str, Any],
    sx: float,
    sy: float,
    step_m: float = SAMPLE_STEP_M,
) -> list[np.ndarray]:
    from shapely.geometry import LineString

    transform = frame["transform"]
    sampled = []
    for part in parts:
        cols = (part[:, 0] - transform[2]) / transform[0]
        rows = (part[:, 1] - transform[5]) / transform[4]
        meter = LineString([(float(col * sx), float(row * sy)) for col, row in zip(cols, rows)])
        if meter.length < 1 or len(part) < 2:
            sampled.append(np.asarray([(float(cols[0]), float(rows[0]))], dtype=np.float64))
            continue
        count = max(int(round(meter.length / step_m)), 1)
        points = []
        for distance in np.linspace(0, meter.length, count + 1):
            point = meter.interpolate(float(distance))
            points.append((point.x / sx, point.y / sy))
        sampled.append(np.asarray(points, dtype=np.float64))
    return sampled


def _cell(col: float, row: float, shape: tuple[int, int]) -> tuple[int, int] | None:
    c = int(round(col))
    r = int(round(row))
    height, width = shape
    if 0 <= r < height and 0 <= c < width:
        return r, c
    return None


def _cross_sections(
    known: np.ndarray,
    part_samples: list[np.ndarray],
    sx: float,
    sy: float,
) -> float | None:
    if not known.any():
        return None
    widths = []
    for samples in part_samples:
        if len(samples) < 2:
            continue
        for index in range(len(samples)):
            cell = _cell(samples[index, 0], samples[index, 1], known.shape)
            if cell is None or not known[cell]:
                continue
            neighbor = samples[min(index + 1, len(samples) - 1)] - samples[max(index - 1, 0)]
            step = _perp_step(float(neighbor[0]), float(neighbor[1]), sx, sy)
            if step is None:
                continue
            dcol, drow = step
            left = _bank_distance(known, cell, drow, dcol)
            right = _bank_distance(known, cell, -drow, -dcol)
            if left is None or right is None:
                continue
            width = left + right
            if MIN_WIDTH_M <= width <= 2 * MAX_HALF_WIDTH_M:
                widths.append(width)
    if len(widths) < MIN_VALID_SAMPLES:
        return None
    values = np.asarray(widths, dtype=np.float64)
    mid = float(np.median(values))
    keep = values[(values >= max(MIN_WIDTH_M, mid * 0.4)) & (values <= max(mid * 2.5, mid + 8.0))]
    if len(keep) < MIN_VALID_SAMPLES:
        return None
    return float(np.median(keep))


def _perp_step(dcol: float, drow: float, sx: float, sy: float) -> tuple[float, float] | None:
    mx = dcol * sx
    my = drow * sy
    norm = math.hypot(mx, my)
    if norm < 1e-6:
        return None
    # One ground-grid meter perpendicular to the centerline, in pixel steps.
    return (-my / norm) / sx, (mx / norm) / sy


def _bank_distance(mask: np.ndarray, start: tuple[int, int], drow: float, dcol: float) -> float | None:
    row, col = float(start[0]), float(start[1])
    limit = int(math.ceil(MAX_HALF_WIDTH_M))
    for step in range(1, limit + 1):
        row += drow
        col += dcol
        cell = _cell(col, row, mask.shape)
        if cell is None:
            return None
        if not mask[cell]:
            return step - 0.5
    return None


def _rasterize_gaps(
    lines: list[dict[str, Any]],
    known: np.ndarray,
    frame: dict[str, Any],
    road: np.ndarray,
    building: np.ndarray,
) -> np.ndarray:
    from experiments.protected_farmland import FarmlandImportError, _burn

    sx, sy = _pixel_size(frame)["x"], _pixel_size(frame)["y"]
    dist = None
    if known.any():
        from scipy.ndimage import distance_transform_edt

        # Zeros of ~known are the water cells, so this is meters to existing water.
        dist = distance_transform_edt(~known, sampling=(sy, sx))
    shape = (int(frame["height"]), int(frame["width"]))
    protected = road | building
    mask = np.zeros(shape, dtype=bool)
    for line in lines:
        line["gaps"] = []
        width = line["width_m"]
        if width is None or line["width_source"] == "excluded":
            continue
        for samples in _part_samples(line["parts"], frame, sx, sy, RIVER_GAP_SAMPLE_SPACING_M):
            for gap in _gap_spans(samples, known, dist, float(width), sx, sy):
                if gap["status"] == "candidate":
                    gap = _connect_banks(gap, frame, sx, sy)
                polygon = gap.pop("polygon", None)
                gap.pop("parent", None)
                gap.pop("measured", None)
                pieces: list[tuple[dict[str, Any], Any]] = []
                if gap["status"] == "accepted" and polygon is not None:
                    gap["fill"] = "observed_interpolation"
                    pieces = [(gap, polygon)]
                else:
                    if gap["status"] == "accepted":
                        gap["status"] = "rejected"
                        gap["reason"] = "invalid_polygon"
                    pieces = _conservative_pieces(gap, float(width), known, dist, frame, sx, sy)
                for piece, piece_polygon in pieces:
                    burned = np.zeros(shape, dtype=bool)
                    if piece_polygon is not None:
                        try:
                            burned = _burn([piece_polygon], frame, shape)
                        except FarmlandImportError as exc:
                            raise ValueError(f"水系线栅格化失败：{exc}") from exc
                    fresh_burn = burned & ~known
                    piece["road_cells"] = int(np.count_nonzero(fresh_burn & road))
                    piece["building_cells"] = int(np.count_nonzero(fresh_burn & building))
                    burned &= ~protected
                    line["gaps"].append(piece)
                    mask |= burned
    return mask


def _gap_spans(
    samples: np.ndarray,
    known: np.ndarray,
    dist: np.ndarray | None,
    width: float,
    sx: float,
    sy: float,
) -> list[dict[str, Any]]:
    """One span per run that lacks a reliable cross-section and actually leaves the water."""

    count = len(samples)
    if count < 2:
        return []
    tolerance = max(CENTER_MATCH_M, width / 2.0)
    covered = np.zeros(count, dtype=bool)
    usable = np.zeros(count, dtype=bool)
    measured: list[tuple[float, float, float, float] | None] = [None] * count
    for index, (col, row) in enumerate(samples):
        cell = _cell(float(col), float(row), known.shape)
        if cell is None:
            continue
        usable[index] = True
        if dist is not None:
            covered[index] = bool(known[cell] or float(dist[cell]) <= tolerance)
        if known[cell] or (dist is not None and float(dist[cell]) <= MAX_ALIGN_M):
            measured[index] = _end_observation(samples, index, known, sx, sy)
    anchor = [value is not None for value in measured]
    spans = []
    start = None
    for index, is_anchor in enumerate(anchor + [True]):
        if not is_anchor and start is None:
            start = index
        elif is_anchor and start is not None:
            end = index - 1
            spans.extend(_span_between(samples, measured, covered, usable, start, end, sx, sy))
            start = None
    return spans


def _span_between(
    samples: np.ndarray,
    measured: list[tuple[float, float, float, float] | None],
    covered: np.ndarray,
    usable: np.ndarray,
    start: int,
    end: int,
    sx: float,
    sy: float,
) -> list[dict[str, Any]]:
    if not any(usable[index] and not covered[index] for index in range(start, end + 1)):
        return []
    # The samples just outside a non-anchor run are anchors when the run is interior.
    left = start - 1 if start > 0 else None
    right = end + 1 if end + 1 < len(samples) else None
    both = left is not None and right is not None
    lo = start if left is None else left
    hi = end if right is None else right
    chosen = samples[lo : hi + 1]
    length = _span_length(chosen, sx, sy)
    if length < GAP_MIN_M or len(chosen) < 2:
        return []
    width_start = None if left is None or measured[left] is None else measured[left][1]
    width_end = None if right is None or measured[right] is None else measured[right][1]
    status = "rejected"
    reason = "open_end"
    if both and width_start is not None and width_end is not None:
        ratio = max(width_start, width_end) / min(width_start, width_end)
        if length > RIVER_GAP_MAX_LENGTH_M:
            reason = "too_long"
        elif ratio > RIVER_GAP_MAX_WIDTH_RATIO:
            reason = "width_ratio"
        else:
            status = "candidate"
            reason = ""
    return [
        {
            "samples": chosen,
            "parent": samples,
            "measured": measured,
            "left_index": left,
            "right_index": right,
            "status": status,
            "reason": reason,
        }
    ]


def _end_observation(
    samples: np.ndarray,
    index: int,
    water: np.ndarray,
    sx: float,
    sy: float,
) -> tuple[float, float, float, float] | None:
    """Signed center offset, width, and the perpendicular pixel step of one sample."""

    neighbor = samples[min(index + 1, len(samples) - 1)] - samples[max(index - 1, 0)]
    step = _perp_step(float(neighbor[0]), float(neighbor[1]), sx, sy)
    if step is None:
        return None
    hit = _water_center_offset(
        water,
        None,
        float(samples[index, 0]),
        float(samples[index, 1]),
        step[0],
        step[1],
    )
    # A center this far from the corrected line belongs to another water body.
    if hit is None or abs(hit[0]) > RIVER_GAP_MAX_END_OFFSET_M:
        return None
    return float(hit[0]), float(hit[1]), float(step[0]), float(step[1])


def _connect_banks(gap: dict[str, Any], frame: dict[str, Any], sx: float, sy: float) -> dict[str, Any]:
    """Join the two end sections with straight banks. Official gap vertices are not used."""

    parent = gap["parent"]
    measured = gap["measured"]
    left_obs = measured[int(gap["left_index"])]
    right_obs = measured[int(gap["right_index"])]
    if left_obs is None or right_obs is None:
        return _reject(gap, "unreliable_end")
    start = _section_banks(parent[int(gap["left_index"])], left_obs, sx, sy)
    end = _section_banks(parent[int(gap["right_index"])], right_obs, sx, sy)
    if float(np.dot(start["perp_m"], end["perp_m"])) < 0.0:
        end = _flip_section(end)
    chord = end["center_m"] - start["center_m"]
    chord_m = float(np.hypot(chord[0], chord[1]))
    start_dir = _along_track(start["perp_m"], chord)
    end_dir = _along_track(end["perp_m"], chord)
    direction_start = None if chord_m < 1.0 else _angle_deg(start_dir, chord)
    direction_end = None if chord_m < 1.0 else _angle_deg(end_dir, chord)
    if (
        chord_m < 1.0
        or direction_start > MAX_ENDPOINT_DIRECTION_ERROR_DEG
        or direction_end > MAX_ENDPOINT_DIRECTION_ERROR_DEG
    ):
        return _reject(gap, "direction")
    if min(start["width"], end["width"]) <= 0 or max(start["width"], end["width"]) / min(start["width"], end["width"]) > RIVER_GAP_MAX_WIDTH_RATIO:
        return _reject(gap, "width_ratio")
    polygon = _straight_bank_polygon(start, end, frame, sx, sy)
    if polygon is None:
        return _reject(gap, "bank_pairing")
    gap["polygon"] = polygon
    gap["status"] = "accepted"
    gap["reason"] = ""
    return gap


def _conservative_pieces(
    gap: dict[str, Any],
    width: float,
    known: np.ndarray,
    dist: np.ndarray | None,
    frame: dict[str, Any],
    sx: float,
    sy: float,
) -> list[tuple[dict[str, Any], Any]]:
    """Follow the corrected line at the existing width. Length does not widen it."""

    samples = gap["samples"]
    labels = [_sample_decision(samples, index, known, dist, sx, sy) for index in range(len(samples))]
    pieces: list[tuple[dict[str, Any], Any]] = []
    start = 0
    while start < len(samples):
        keep = labels[start] == "keep"
        end = start + 1
        while end < len(samples) and (labels[end] == "keep") == keep:
            end += 1
        run = samples[start:end]
        if keep and len(run) < 2:
            start = end
            continue
        reason = "" if keep else str(labels[start])
        piece = _piece_from(keep, reason)
        polygon = _corridor_polygon(run, min(width / 2.0, MAX_HALF_WIDTH_M), frame, sx, sy) if keep and len(run) >= 2 else None
        if keep and polygon is None and len(run) >= 2:
            piece["status"] = "rejected"
            piece["fill"] = "rejected_geometry"
            piece["reason"] = "invalid_polygon"
        pieces.append((piece, polygon if piece["fill"] == "conservative_line" else None))
        start = end
    return pieces


def _sample_decision(
    samples: np.ndarray,
    index: int,
    known: np.ndarray,
    dist: np.ndarray | None,
    sx: float,
    sy: float,
) -> str:
    """Dry samples stay. A kink, or a sample beside water it does not sit on, is local."""

    col, row = float(samples[index, 0]), float(samples[index, 1])
    cell = _cell(col, row, known.shape)
    if cell is None:
        return "outside"
    if 0 < index < len(samples) - 1:
        turn = _angle_deg(samples[index] - samples[index - 1], samples[index + 1] - samples[index])
        if turn > MAX_ENDPOINT_DIRECTION_ERROR_DEG:
            return "kink"
    # No water within the alignment range is a dry bed, not evidence the line is wrong.
    if dist is None or float(dist[cell]) > MAX_ALIGN_M:
        return "keep"
    neighbor = samples[min(index + 1, len(samples) - 1)] - samples[max(index - 1, 0)]
    step = _perp_step(float(neighbor[0]), float(neighbor[1]), sx, sy)
    if step is None:
        return "kink"
    hit = _water_center_offset(known, None, col, row, step[0], step[1])
    # A measured center more than 8 m off this sample is a different channel.
    # A miss on the perpendicular is not, by itself, a reason to stop the corridor.
    if hit is not None and abs(float(hit[0])) > RIVER_GAP_MAX_END_OFFSET_M:
        return "offset"
    return "keep"


def _piece_from(keep: bool, reason: str) -> dict[str, Any]:
    return {
        "status": "accepted" if keep else "rejected",
        "reason": "" if keep else reason,
        "fill": "conservative_line" if keep else "rejected_geometry",
    }


def _corridor_polygon(samples: np.ndarray, half_m: float, frame: dict[str, Any], sx: float, sy: float):
    from shapely.geometry import LineString
    from shapely.ops import transform

    if len(samples) < 2 or half_m <= 0:
        return None
    points = [_to_meter(sample, sx, sy) for sample in samples]
    extended = _extend_polyline(points, BANK_SEAM_M)
    line = LineString([(float(point[0]), float(point[1])) for point in extended])
    if line.is_empty or line.length <= 0 or not line.is_simple:
        return None
    polygon = line.buffer(half_m, cap_style="flat", join_style="round")
    if polygon.geom_type == "MultiPolygon":
        polygon = max(polygon.geoms, key=lambda part: part.area)
    if polygon.is_empty or not polygon.is_valid or polygon.geom_type != "Polygon" or polygon.area <= 0:
        return None
    moved = transform(_to_3857(sx, sy, frame["transform"]), polygon)
    if moved.is_empty or not moved.is_valid or moved.geom_type != "Polygon":
        return None
    return moved


def _extend_polyline(points: list[np.ndarray], seam: float) -> list[np.ndarray]:
    if len(points) < 2 or seam <= 0:
        return points
    forward = points[1] - points[0]
    backward = points[-1] - points[-2]
    forward_norm = float(np.hypot(forward[0], forward[1]))
    backward_norm = float(np.hypot(backward[0], backward[1]))
    if forward_norm < 1e-6 or backward_norm < 1e-6:
        return points
    start = points[0] - forward / forward_norm * seam
    end = points[-1] + backward / backward_norm * seam
    return [start, *points[1:-1], end]


def _reject(gap: dict[str, Any], reason: str) -> dict[str, Any]:
    gap["status"] = "rejected"
    gap["reason"] = reason
    return gap


def _section_banks(
    sample: np.ndarray,
    observation: tuple[float, float, float, float],
    sx: float,
    sy: float,
) -> dict[str, Any]:
    offset, width, dcol, drow = observation
    perp_px = np.array([dcol, drow], dtype=np.float64)
    center_px = np.asarray(sample, dtype=np.float64) + float(offset) * perp_px
    half = float(width) / 2.0
    left_px = center_px + half * perp_px
    right_px = center_px - half * perp_px
    return {
        "center_px": center_px,
        "left_px": left_px,
        "right_px": right_px,
        "center_m": _to_meter(center_px, sx, sy),
        "left_m": _to_meter(left_px, sx, sy),
        "right_m": _to_meter(right_px, sx, sy),
        "perp_m": np.array([dcol * sx, drow * sy], dtype=np.float64),
        "width": float(width),
    }


def _flip_section(section: dict[str, Any]) -> dict[str, Any]:
    flipped = dict(section)
    flipped["left_px"] = section["right_px"]
    flipped["right_px"] = section["left_px"]
    flipped["left_m"] = section["right_m"]
    flipped["right_m"] = section["left_m"]
    flipped["perp_m"] = -section["perp_m"]
    return flipped


def _along_track(perp_m: np.ndarray, chord: np.ndarray) -> np.ndarray:
    candidate = np.array([-float(perp_m[1]), float(perp_m[0])], dtype=np.float64)
    if float(np.dot(candidate, chord)) < 0.0:
        candidate = -candidate
    return candidate


def _to_meter(point: np.ndarray, sx: float, sy: float) -> np.ndarray:
    return np.array([float(point[0]) * sx, float(point[1]) * sy], dtype=np.float64)


def _angle_deg(earlier: np.ndarray, later: np.ndarray) -> float:
    left = float(np.hypot(earlier[0], earlier[1]))
    right = float(np.hypot(later[0], later[1]))
    if left < 1e-6 or right < 1e-6:
        return 180.0
    cosine = float(np.dot(earlier, later) / (left * right))
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))


def _span_length(samples: np.ndarray, sx: float, sy: float) -> float:
    total = 0.0
    for earlier, later in zip(samples, samples[1:]):
        total += math.hypot((float(later[0]) - float(earlier[0])) * sx, (float(later[1]) - float(earlier[1])) * sy)
    return total


def _straight_bank_polygon(start: dict[str, Any], end: dict[str, Any], frame: dict[str, Any], sx: float, sy: float):
    from shapely.geometry import Polygon
    from shapely.ops import transform

    left = _extend_bank(start["left_m"], end["left_m"])
    right = _extend_bank(start["right_m"], end["right_m"])
    if left is None or right is None:
        return None
    ring = [tuple(map(float, point)) for point in (left[0], left[1], right[1], right[0])]
    polygon = Polygon(ring)
    if polygon.is_empty or not polygon.is_valid or not polygon.is_simple or polygon.area <= 0:
        return None
    moved = transform(_to_3857(sx, sy, frame["transform"]), polygon)
    if moved.is_empty or not moved.is_valid or moved.geom_type != "Polygon":
        return None
    return moved


def _extend_bank(start: np.ndarray, end: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    delta = end - start
    norm = float(np.hypot(delta[0], delta[1]))
    if norm < 1e-6:
        return None
    # Slide along the bank itself. The edge stays on the line between the two banks.
    unit = delta / norm
    return start - unit * BANK_SEAM_M, end + unit * BANK_SEAM_M


def _to_3857(sx: float, sy: float, transform: list[float]):
    def convert(x, y, z=None):
        cols = np.asarray(x, dtype=np.float64) / sx
        rows = np.asarray(y, dtype=np.float64) / sy
        east = transform[0] * cols + transform[2]
        north = transform[4] * rows + transform[5]
        if z is None:
            return east, north
        return east, north, z

    return convert

