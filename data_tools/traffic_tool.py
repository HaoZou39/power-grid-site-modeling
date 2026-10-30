"""Project and simplify road centerlines into local coordinates and a Voronoi grid."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from .scene_coordinates import projection
from shapely.geometry import LineString, MultiLineString, shape

from .io_utils import LOCAL_COORD_CONVENTION, save_array_product, write_json
from .road_voronoi import (
    compute_segment_voronoi as _compute_segment_voronoi,
    _compute_segment_voronoi_numpy,
    resolve_voronoi_backend,
)


@dataclass(frozen=True)
class RoadLine:
    source_id: str
    part: int
    coords: np.ndarray
    level: int
    kind: int = 0


def _tag_is_true(value: Any) -> bool:
    return str(value).strip().lower() not in {"", "0", "false", "no", "none"}


def road_segment_kind(properties: dict[str, Any], rules: dict[str, Any]) -> int:
    if _tag_is_true(properties.get(rules["tunnel_truthy_field"])):
        return 3
    for name, kind in (("highway", 2), ("link", 1)):
        if any(properties.get(field) in values for field, values in rules[name].items()):
            return kind
    return 0


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
    transformer,
    ref_bounds: Any,
    x_scale: float,
    y_scale: float,
    kind_rules: dict[str, Any] | None = None,
) -> list[RoadLine]:
    if kind_rules is None:
        from config.project_config import load_default_config
        kind_rules = load_default_config().data.road_kind_rules
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
                kind=road_segment_kind(properties, kind_rules),
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
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
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
    kinds: list[int] = []
    for line, indices in zip(lines, protected):
        ordered = sorted(indices)
        for start, stop in zip(ordered[:-1], ordered[1:]):
            section = line.coords[start : stop + 1]
            coords = np.asarray(
                LineString(section).simplify(tolerance, preserve_topology=False).coords,
                dtype=np.float64,
            )
            before = len(segments)
            segments.extend(
                [float(a[0]), float(a[1]), float(b[0]), float(b[1])]
                for a, b in zip(coords[:-1], coords[1:])
                if np.linalg.norm(b - a) > 1e-9
            )
            kinds.extend([line.kind] * (len(segments) - before))
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
    return result, np.asarray(kinds, dtype=np.int8), diagnostics


def build_road_product(
    osm_roads_path: Path,
    output_segments_path: Path | None,
    output_voronoi_path: Path | None,
    reference_geotiff_path: Path | None,
    target_shape: tuple[int, int],
    road_dp_tolerance_m: float,
    road_resolution_m: float = 1.0,
    chunk_points: int = 8192,
    *,
    voronoi_backend: str = "auto",
    voronoi_device: str = "cuda",
    voronoi_chunk_points: int = 1048576,
    voronoi_segment_tile: int = 128,
    reference_frame: dict[str, Any] | None = None,
    kind_rules: dict[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    osm_roads_path = Path(osm_roads_path)
    if not osm_roads_path.exists():
        raise FileNotFoundError(osm_roads_path)
    if len(target_shape) != 2:
        raise ValueError("target_shape must have length 2")
    height, width = (int(target_shape[0]), int(target_shape[1]))
    if height <= 0 or width <= 0 or road_resolution_m <= 0 or road_dp_tolerance_m < 0:
        raise ValueError("road target shape/resolution/tolerance parameters are invalid")

    if reference_frame is None:
        if reference_geotiff_path is None or not Path(reference_geotiff_path).is_file():
            raise FileNotFoundError(reference_geotiff_path)
        with rasterio.open(reference_geotiff_path) as ref:
            if ref.crs is None:
                raise ValueError(f"reference GeoTIFF has no CRS: {reference_geotiff_path}")
            ref_crs = ref.crs
            ref_bounds = ref.bounds
            ref_transform = ref.transform
            ref_raw_shape = (ref.height, ref.width)
    else:
        from rasterio.coords import BoundingBox
        from rasterio.transform import Affine, array_bounds

        if reference_geotiff_path is not None:
            raise ValueError("supply either a reference GeoTIFF or a prepared frame")
        if (reference_frame["height"], reference_frame["width"]) != (height, width):
            raise ValueError("prepared reference frame and target shape differ")
        ref_crs = rasterio.crs.CRS.from_user_input(reference_frame["crs"])
        ref_transform = Affine(*reference_frame["transform"])
        if ref_transform.b != 0 or ref_transform.d != 0 or ref_transform.a <= 0 or ref_transform.e >= 0:
            raise ValueError("prepared road frame must have x rightward and y downward")
        ref_bounds = BoundingBox(*array_bounds(height, width, ref_transform))
        ref_raw_shape = (height, width)

    x_scale = width / (ref_bounds.right - ref_bounds.left)
    y_scale = height / (ref_bounds.top - ref_bounds.bottom)
    if x_scale <= 0 or y_scale <= 0:
        raise ValueError("reference GeoTIFF bounds are invalid")
    simplify_tolerance_grid = road_dp_tolerance_m * 0.5 * (x_scale + y_scale)

    raw = json.loads(osm_roads_path.read_text(encoding="utf-8"))
    transformer = projection("EPSG:4326", ref_crs)
    if kind_rules is None:
        from config.project_config import load_default_config
        kind_rules = load_default_config().data.road_kind_rules
    lines = _project_lines(raw, transformer, ref_bounds, x_scale, y_scale, kind_rules)
    segments, kinds, topology = _topology_simplified_segments(lines, simplify_tolerance_grid)
    road_segments_local = np.asarray(segments, dtype=np.float32)
    access_ids = np.flatnonzero(kinds == 0)
    if not len(access_ids):
        raise ValueError("road source must contain at least one access road")
    actual_backend = resolve_voronoi_backend(voronoi_backend, voronoi_device)
    road_voronoi = _compute_segment_voronoi(
        road_segments_local[access_ids], height, width, road_resolution_m, chunk_points,
        backend=actual_backend, device=voronoi_device,
        gpu_chunk_points=voronoi_chunk_points, segment_tile=voronoi_segment_tile,
    )
    road_voronoi = access_ids[road_voronoi].astype(np.int64)
    from uuid import uuid4
    metadata = {
        "road_product_id": uuid4().hex,
        "provider": "osm",
        "segment_kind_counts": {str(kind): int(np.count_nonzero(kinds == kind)) for kind in range(4)},
        "road_kind_rules": kind_rules,
        "voronoi_backend_requested": voronoi_backend,
        "voronoi_backend": actual_backend,
        "voronoi_device": str(voronoi_device) if actual_backend == "cuda" else "cpu",
        "voronoi_chunk_points": voronoi_chunk_points if actual_backend == "cuda" else chunk_points,
        "voronoi_segment_tile": voronoi_segment_tile if actual_backend == "cuda" else None,
        "source_path": str(osm_roads_path),
        "reference_geotiff_path": str(reference_geotiff_path) if reference_geotiff_path is not None else None,
        "reference_grid_source": "prepared_scene" if reference_frame is not None else "geotiff",
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
        np.save(output_segments_path.with_name("road_segment_kind.npy"), kinds)
        write_json(output_segments_path.with_suffix(".json"), metadata)
    if output_voronoi_path is not None:
        save_array_product(output_voronoi_path, road_voronoi, metadata)
    return road_segments_local, road_voronoi, kinds, metadata
