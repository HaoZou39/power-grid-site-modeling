"""Read-only comparison of raw, legacy, and topology-preserving road networks."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from shapely.geometry import LineString

from config.project_config import load_project_config
from data_tools.traffic_tool import (
    _component_stats,
    _legacy_simplified_segments,
    _node_key,
    _project_lines,
    _raw_segments,
    _topology_simplified_segments,
)
from modeling.logistics_cost import RoadNetwork


def _endpoint_degrees(segments: np.ndarray) -> Counter:
    degree: Counter = Counter()
    for segment in segments:
        degree[_node_key(segment[:2])] += 1
        degree[_node_key(segment[2:])] += 1
    return degree


def _legacy_records(lines, tolerance: float):
    records = []
    for line in lines:
        coords = np.asarray(
            LineString(line.coords).simplify(tolerance, preserve_topology=False).coords,
            dtype=np.float64,
        )
        for left, right in zip(coords[:-1], coords[1:]):
            if np.linalg.norm(right - left) > 1e-9:
                records.append((np.asarray([*left, *right]), line.source_id, line.level))
    return records


def _cross_component_intersections(records, network: RoadNetwork) -> list[dict[str, Any]]:
    found = []
    for left in range(len(records)):
        first = LineString(np.asarray(records[left][0]).reshape(2, 2))
        for right in range(left + 1, len(records)):
            if network.segment_components[left] == network.segment_components[right]:
                continue
            intersection = first.intersection(LineString(np.asarray(records[right][0]).reshape(2, 2)))
            if intersection.geom_type != "Point" or intersection.is_empty:
                continue
            found.append({
                "x": float(intersection.x),
                "y": float(intersection.y),
                "left_source": records[left][1],
                "right_source": records[right][1],
                "left_level": records[left][2],
                "right_level": records[right][2],
            })
    return found


def topology_report(config_path: str | Path) -> dict[str, Any]:
    config = load_project_config(config_path)
    raw = json.loads(Path(config.data.osm_roads_path).read_text(encoding="utf-8"))
    from rasterio.coords import BoundingBox
    from rasterio.transform import Affine, array_bounds
    frame = config.data.target_grid
    height, width = frame["height"], frame["width"]
    bounds = BoundingBox(*array_bounds(height, width, Affine(*frame["transform"])))
    transformer = Transformer.from_crs("EPSG:4326", frame["crs"], always_xy=True)
    x_scale = 1 / frame["transform"][0]
    y_scale = -1 / frame["transform"][4]
    tolerance = config.data.road_dp_tolerance_m * 0.5 * (x_scale + y_scale)
    lines = _project_lines(raw, transformer, bounds, x_scale, y_scale, config.data.road_kind_rules)
    original = _raw_segments(lines)
    legacy = _legacy_simplified_segments(lines, tolerance)
    repaired, kinds, diagnostics = _topology_simplified_segments(lines, tolerance)

    raw_degree = _endpoint_degrees(original)
    legacy_degree = _endpoint_degrees(legacy)
    repaired_degree = _endpoint_degrees(repaired)
    junctions = {node for node, degree in raw_degree.items() if degree > 2}
    lost = {node: raw_degree[node] - legacy_degree[node] for node in junctions if legacy_degree[node] < raw_degree[node]}
    still_lost = {
        node: raw_degree[node] - repaired_degree[node]
        for node in junctions
        if repaired_degree[node] < raw_degree[node]
    }
    records = _legacy_records(lines, tolerance)
    legacy_network = RoadNetwork(legacy)
    report = {
        "raw_feature_count": len(raw.get("features", [])),
        "raw_linestring_count": len(lines),
        "raw": {"segment_count": len(original), **_component_stats(original)},
        "legacy": {"segment_count": len(legacy), **_component_stats(legacy)},
        "repaired": {"segment_count": len(repaired), **_component_stats(repaired)},
        "true_junction_count": len(junctions),
        "protected_node_count": diagnostics["protected_node_count"],
        "legacy_lost_junction_count": len(lost),
        "legacy_lost_connection_incidence_count": int(sum(lost.values())),
        "repaired_lost_junction_count": len(still_lost),
        "unexpected_component_merges": max(
            0,
            _component_stats(original)["component_count"] - _component_stats(repaired)["component_count"],
        ),
        "legacy_cross_component_intersections": _cross_component_intersections(records, legacy_network),
    }
    return report


def scene_origin_report(
    scene_dir: str | Path,
    longitude: float,
    latitude: float,
    with_gates: bool,
) -> dict[str, Any]:
    scene = Path(scene_dir)
    metadata = json.loads((scene / "road_segments_local.json").read_text(encoding="utf-8"))
    map_x, map_y = Transformer.from_crs(
        "EPSG:4326",
        metadata["reference_crs"],
        always_xy=True,
    ).transform(longitude, latitude)
    bounds = metadata["reference_bounds"]
    origin = (
        (map_x - bounds["left"]) * metadata["x_scale_grid_per_crs_unit"],
        (bounds["top"] - map_y) * metadata["y_scale_grid_per_crs_unit"],
    )
    segments = np.load(scene / "road_segments_local.npy")
    network = RoadNetwork(segments)
    nearest = network.project(origin)
    result = {
        "origin_local": origin,
        "nearest_road_gap_m": nearest.gap_m,
        "nearest_segment_id": nearest.edge,
        "component_id": network.component(nearest),
        "component_count": network.component_count,
    }
    if with_gates:
        from experiments.constraint_mask import compose_constraint_masks, policy_from_form
        from modeling.haul_field import build_haul_field

        hard_mask, _soft_mask = compose_constraint_masks(
            np.load(scene / "landuse_1m.npy"),
            [],
            policy_from_form({"field_policy": "allowed", "mountain_policy": "allowed"}),
        )
        field = build_haul_field(
            np.load(scene / "dem_1m.npy"),
            hard_mask == 0,
            segments,
            origin,
        )
        result.update({
            "gate_count": field.gate_count,
            "reachable_gate_count": field.reachable_gate_count,
            "unreachable_gate_count": field.unreachable_gate_count,
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/default_config.json")
    parser.add_argument("--scene-dir")
    parser.add_argument("--origin-lon", type=float, default=120.193987)
    parser.add_argument("--origin-lat", type=float, default=27.500968)
    parser.add_argument("--with-gates", action="store_true")
    args = parser.parse_args()
    report = topology_report(args.config)
    if args.scene_dir:
        report["scene_origin"] = scene_origin_report(
            args.scene_dir,
            args.origin_lon,
            args.origin_lat,
            args.with_gates,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
