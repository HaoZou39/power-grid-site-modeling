"""Project and simplify OSM roads into local coordinates and a Voronoi grid."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, shape

try:
    from numba import njit, prange
except ImportError:  # pragma: no cover - the documented environment includes numba
    njit = None
    prange = range

from .io_utils import LOCAL_COORD_CONVENTION, save_array_product, write_json


@dataclass(frozen=True)
class RoadLine:
    source_id: str
    part: int
    coords: np.ndarray
    level: int


def _tag_is_true(value: Any) -> bool:
    return str(value).strip().lower() not in {"", "0", "false", "no", "none"}


def _effective_level(properties: dict[str, Any]) -> int:
    value = properties.get("layer")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid OSM layer value: {value!r}") from exc
    bridge = _tag_is_true(properties.get("bridge"))
    tunnel = _tag_is_true(properties.get("tunnel"))
    if bridge and tunnel:
        raise ValueError("one road feature cannot be both bridge and tunnel")
    return 1 if bridge else (-1 if tunnel else 0)


def _node_key(point: np.ndarray, level: int = 0) -> tuple[float, float, int]:
    return round(float(point[0]), 6), round(float(point[1]), 6), int(level)


def _graph_key(point: np.ndarray) -> tuple[float, float]:
    return round(float(point[0]), 3), round(float(point[1]), 3)


def _iter_lines(geom):
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        yield from geom.geoms


def _project_lines(
    raw: dict[str, Any],
    transformer: Transformer,
    ref_bounds: Any,
    x_scale: float,
    y_scale: float,
) -> list[RoadLine]:
    lines: list[RoadLine] = []
    for feature_index, feature in enumerate(raw.get("features", [])):
        properties = feature.get("properties") or {}
        geom = shape(feature.get("geometry"))
        for part, line in enumerate(_iter_lines(geom)):
            coords = np.asarray(line.coords, dtype=np.float64)
            if len(coords) < 2 or not np.isfinite(coords).all():
                raise ValueError("OSM roads must contain finite LineStrings with at least two points")
            ref_x, ref_y = transformer.transform(coords[:, 0], coords[:, 1])
            local = np.column_stack([
                (np.asarray(ref_x) - ref_bounds.left) * x_scale,
                (ref_bounds.top - np.asarray(ref_y)) * y_scale,
            ])
            lines.append(RoadLine(
                source_id=str(properties.get("@id") or feature_index),
                part=part,
                coords=local,
                level=_effective_level(properties),
            ))
    if not lines:
        raise ValueError("no valid road LineStrings found")
    return lines


def _raw_segments(lines: list[RoadLine]) -> np.ndarray:
    segments = [
        [float(a[0]), float(a[1]), float(b[0]), float(b[1])]
        for line in lines
        for a, b in zip(line.coords[:-1], line.coords[1:])
        if np.linalg.norm(b - a) > 1e-9
    ]
    if not segments:
        raise ValueError("no valid road segments found")
    return np.asarray(segments, dtype=np.float64)


def _component_stats(segments: np.ndarray) -> dict[str, Any]:
    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = defaultdict(list)
    for segment in np.asarray(segments, dtype=np.float64):
        left = _graph_key(segment[:2])
        right = _graph_key(segment[2:])
        length = float(np.linalg.norm(segment[2:] - segment[:2]))
        graph[left].append((right, length))
        graph[right].append((left, length))
    components = []
    visited: set[tuple[float, float]] = set()
    for start in graph:
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        nodes = 0
        doubled_length = 0.0
        while stack:
            node = stack.pop()
            nodes += 1
            for neighbor, length in graph[node]:
                doubled_length += length
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        components.append({"node_count": nodes, "length_m": doubled_length * 0.5})
    components.sort(key=lambda item: (-item["length_m"], -item["node_count"]))
    return {
        "node_count": len(graph),
        "component_count": len(components),
        "components": components,
        "total_length_m": float(sum(item["length_m"] for item in components)),
    }


def _legacy_simplified_segments(lines: list[RoadLine], tolerance: float) -> np.ndarray:
    simplified = []
    for line in lines:
        coords = np.asarray(
            LineString(line.coords).simplify(tolerance, preserve_topology=False).coords,
            dtype=np.float64,
        )
        simplified.extend(
            [float(a[0]), float(a[1]), float(b[0]), float(b[1])]
            for a, b in zip(coords[:-1], coords[1:])
            if np.linalg.norm(b - a) > 1e-9
        )
    return np.asarray(simplified, dtype=np.float64)


def _topology_simplified_segments(
    lines: list[RoadLine],
    tolerance: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    occurrences: dict[tuple[float, float, int], list[tuple[int, int]]] = defaultdict(list)
    degree: Counter[tuple[float, float, int]] = Counter()
    for line_index, line in enumerate(lines):
        for vertex_index, point in enumerate(line.coords):
            key = _node_key(point)
            occurrences[key].append((line_index, vertex_index))
        for left, right in zip(line.coords[:-1], line.coords[1:]):
            left_key = _node_key(left)
            right_key = _node_key(right)
            if left_key != right_key:
                degree[left_key] += 1
                degree[right_key] += 1

    protected = [{0, len(line.coords) - 1} for line in lines]
    junctions: set[tuple[float, float, int]] = set()
    for key, positions in occurrences.items():
        distinct_lines = {line_index for line_index, _vertex_index in positions}
        if degree[key] != 2 or len(distinct_lines) > 1:
            if degree[key] > 2:
                junctions.add(key)
            canonical = np.asarray(key[:2], dtype=np.float64)
            for line_index, vertex_index in positions:
                protected[line_index].add(vertex_index)
                lines[line_index].coords[vertex_index] = canonical

    segments: list[list[float]] = []
    for line, indices in zip(lines, protected):
        ordered = sorted(indices)
        for start, stop in zip(ordered[:-1], ordered[1:]):
            section = line.coords[start : stop + 1]
            coords = np.asarray(
                LineString(section).simplify(tolerance, preserve_topology=False).coords,
                dtype=np.float64,
            )
            segments.extend(
                [float(a[0]), float(a[1]), float(b[0]), float(b[1])]
                for a, b in zip(coords[:-1], coords[1:])
                if np.linalg.norm(b - a) > 1e-9
            )
    result = np.asarray(segments, dtype=np.float64)
    if result.ndim != 2 or result.shape[1] != 4 or not np.isfinite(result).all():
        raise ValueError("topology-preserving road simplification produced invalid segments")

    protected_keys = {
        _node_key(lines[line_index].coords[vertex_index])
        for line_index, indices in enumerate(protected)
        for vertex_index in indices
    }
    output_endpoints = {
        _node_key(point)
        for segment in result
        for point in (segment[:2], segment[2:])
    }
    lost = {key for key in protected_keys if _node_key(np.asarray(key[:2])) not in output_endpoints}
    if lost:
        raise ValueError(f"road simplification lost protected nodes (lost_nodes={len(lost)})")

    raw_stats = _component_stats(_raw_segments(lines))
    simplified_stats = _component_stats(result)
    if simplified_stats["component_count"] != raw_stats["component_count"]:
        raise ValueError(
            "road simplification changed topology "
            f"(raw_components={raw_stats['component_count']}, "
            f"simplified_components={simplified_stats['component_count']})"
        )
    diagnostics = {
        "raw_segment_count": int(sum(max(0, len(line.coords) - 1) for line in lines)),
        "raw_node_count": raw_stats["node_count"],
        "raw_component_count": raw_stats["component_count"],
        "raw_total_length_m": raw_stats["total_length_m"],
        "protected_node_count": len(protected_keys),
        "junction_node_count": len(junctions),
        "simplified_node_count": simplified_stats["node_count"],
        "simplified_component_count": simplified_stats["component_count"],
        "simplified_total_length_m": simplified_stats["total_length_m"],
    }
    return result, diagnostics


def build_road_product(
    osm_roads_path: Path,
    output_segments_path: Path | None,
    output_voronoi_path: Path | None,
    reference_geotiff_path: Path,
    target_shape: tuple[int, int],
    road_dp_tolerance_m: float,
    road_resolution_m: float = 1.0,
    chunk_points: int = 8192,
) -> tuple[np.ndarray, np.ndarray, dict]:
    osm_roads_path = Path(osm_roads_path)
    reference_geotiff_path = Path(reference_geotiff_path)
    if not osm_roads_path.exists():
        raise FileNotFoundError(osm_roads_path)
    if not reference_geotiff_path.exists():
        raise FileNotFoundError(reference_geotiff_path)
    if len(target_shape) != 2:
        raise ValueError("target_shape must have length 2")
    height, width = (int(target_shape[0]), int(target_shape[1]))
    if height <= 0 or width <= 0 or road_resolution_m <= 0 or road_dp_tolerance_m < 0:
        raise ValueError("road target shape/resolution/tolerance parameters are invalid")

    with rasterio.open(reference_geotiff_path) as ref:
        if ref.crs is None:
            raise ValueError(f"reference GeoTIFF has no CRS: {reference_geotiff_path}")
        ref_crs = ref.crs
        ref_bounds = ref.bounds
        ref_transform = ref.transform
        ref_raw_shape = (ref.height, ref.width)

    x_scale = width / (ref_bounds.right - ref_bounds.left)
    y_scale = height / (ref_bounds.top - ref_bounds.bottom)
    if x_scale <= 0 or y_scale <= 0:
        raise ValueError("reference GeoTIFF bounds are invalid")
    simplify_tolerance_grid = road_dp_tolerance_m * 0.5 * (x_scale + y_scale)

    raw = json.loads(osm_roads_path.read_text(encoding="utf-8"))
    transformer = Transformer.from_crs("EPSG:4326", ref_crs, always_xy=True)
    lines = _project_lines(raw, transformer, ref_bounds, x_scale, y_scale)
    segments, topology = _topology_simplified_segments(lines, simplify_tolerance_grid)
    road_segments_local = np.asarray(segments, dtype=np.float32)
    road_voronoi = _compute_segment_voronoi(road_segments_local, height, width, road_resolution_m, chunk_points)
    metadata = {
        "source_path": str(osm_roads_path),
        "reference_geotiff_path": str(reference_geotiff_path),
        "reference_crs": str(ref_crs),
        "reference_bounds": {
            "left": float(ref_bounds.left),
            "right": float(ref_bounds.right),
            "bottom": float(ref_bounds.bottom),
            "top": float(ref_bounds.top),
        },
        "reference_transform": list(ref_transform)[:6],
        "reference_raw_shape": list(ref_raw_shape),
        "shape": [height, width],
        "road_resolution_m": road_resolution_m,
        "road_dp_tolerance_m": road_dp_tolerance_m,
        "road_dp_tolerance_grid": float(simplify_tolerance_grid),
        "simplification_method": "protected_junction_sections_douglas_peucker",
        "x_scale_grid_per_crs_unit": float(x_scale),
        "y_scale_grid_per_crs_unit": float(y_scale),
        "n_segments": int(len(road_segments_local)),
        "raw_feature_count": int(len(raw.get("features", []))),
        "raw_linestring_count": len(lines),
        "osm_node_ids_available": False,
        "topology_evidence": "shared_source_coordinates; unverified_geometric_crossings_are_not_noded",
        "unverified_geometric_crossings_connected": False,
        **topology,
        "local_coord_convention": LOCAL_COORD_CONVENTION,
    }
    if output_segments_path is not None:
        output_segments_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_segments_path, road_segments_local)
        write_json(output_segments_path.with_suffix(".json"), metadata)
    if output_voronoi_path is not None:
        save_array_product(output_voronoi_path, road_voronoi, metadata)
    return road_segments_local, road_voronoi, metadata


if njit is not None:

    @njit(cache=True, parallel=True)
    def _segment_voronoi_numba(seg, height, width, resolution):
        """Nearest segment id at each cell center. Ties keep the smaller id."""

        n = seg.shape[0]
        ax = seg[:, 0]
        ay = seg[:, 1]
        bx = seg[:, 2]
        by = seg[:, 3]
        abx = bx - ax
        aby = by - ay
        denom = abx * abx + aby * aby
        labels = np.empty((height, width), np.int64)
        for y in prange(height):
            py = np.float32((y + 0.5) * resolution)
            for x in range(width):
                px = np.float32((x + 0.5) * resolution)
                best_i = np.int64(0)
                best_d = np.float32(1e38)
                for i in range(n):
                    t = ((px - ax[i]) * abx[i] + (py - ay[i]) * aby[i]) / denom[i]
                    if t < 0.0:
                        t = np.float32(0.0)
                    elif t > 1.0:
                        t = np.float32(1.0)
                    dx = px - (ax[i] + t * abx[i])
                    dy = py - (ay[i] + t * aby[i])
                    dist2 = dx * dx + dy * dy
                    if dist2 < best_d:
                        best_d = dist2
                        best_i = i
                labels[y, x] = best_i
        return labels

else:  # pragma: no cover
    _segment_voronoi_numba = None


def _compute_segment_voronoi(
    segments: np.ndarray,
    height: int,
    width: int,
    resolution_m: float,
    chunk_points: int,
) -> np.ndarray:
    if segments.ndim != 2 or segments.shape[1] != 4:
        raise ValueError("segments must have shape [N_seg, 4]")
    seg = np.ascontiguousarray(segments, dtype=np.float32)
    denom = np.sum((seg[:, 2:4] - seg[:, 0:2]) ** 2, axis=1)
    if np.any(denom <= 0):
        raise ValueError("road segments contain zero-length segment")
    if _segment_voronoi_numba is not None and seg.shape[0] > 0:
        return _segment_voronoi_numba(seg, int(height), int(width), np.float32(resolution_m))
    return _compute_segment_voronoi_numpy(seg, height, width, resolution_m, chunk_points)


def _compute_segment_voronoi_numpy(
    seg: np.ndarray,
    height: int,
    width: int,
    resolution_m: float,
    chunk_points: int,
) -> np.ndarray:
    a = seg[:, 0:2]
    b = seg[:, 2:4]
    ab = b - a
    denom = np.sum(ab * ab, axis=1)
    xs = (np.arange(width, dtype=np.float32) + 0.5) * np.float32(resolution_m)
    ys = (np.arange(height, dtype=np.float32) + 0.5) * np.float32(resolution_m)
    grid_x, grid_y = np.meshgrid(xs, ys)
    points = np.column_stack([grid_x.ravel(), grid_y.ravel()]).astype(np.float32)
    labels = np.empty(points.shape[0], dtype=np.int64)
    for start in range(0, points.shape[0], chunk_points):
        p = points[start : start + chunk_points]
        ap = p[:, None, :] - a[None, :, :]
        t = np.sum(ap * ab[None, :, :], axis=2) / denom[None, :]
        t = np.clip(t, 0.0, 1.0)
        proj = a[None, :, :] + t[:, :, None] * ab[None, :, :]
        diff = p[:, None, :] - proj
        dist2 = np.sum(diff * diff, axis=2)
        labels[start : start + len(p)] = np.argmin(dist2, axis=1)
    return labels.reshape(height, width)
