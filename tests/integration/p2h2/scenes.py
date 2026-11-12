"""Small UTM scenes for the isolated API process."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from modeling.routing.types import RoutingFrame


def frame(origin_x: float) -> RoutingFrame:
    return RoutingFrame("EPSG:32651", (1, 0, origin_x, 0, -1, 3046000), 8, 8)


def write_scene(root: Path, name: str, origin_x: float, revision: str) -> None:
    scene = root / name
    scene.mkdir(parents=True, exist_ok=True)
    shape = (8, 8)
    grid = frame(origin_x)
    arrays = {
        "dem_1m.npy": np.ones(shape, np.float32),
        "landuse_1m.npy": np.zeros(shape, np.uint8),
        "obstacle_mask_1m.npy": np.zeros(shape, np.uint8),
        "road_segments_local.npy": np.array([[0, 1, 6, 1]], np.float32),
        "road_segment_kind.npy": np.zeros(1, np.int8),
        "road_voronoi_1m.npy": np.zeros(shape, np.int64),
        "demand_points.npy": np.array([[1.0, 1.0]], np.float32),
        "protected_farmland_mask_1m.npy": np.zeros(shape, dtype=bool),
    }
    for filename, array in arrays.items():
        np.save(scene / filename, array)
    (scene / "data_metadata.json").write_text(json.dumps({
        "scene_revision": revision,
        "dem": {"reference_crs": grid.crs, "target_transform": list(grid.transform), "shape": [8, 8]},
    }), encoding="utf-8")
    (scene / "scene.json").write_text("{}\n", encoding="utf-8")


def site(width: float, setback: float, zone: float, policy: str) -> dict:
    return {
        "rect_w_m": width, "rect_h_m": 18, "field_policy": policy, "mountain_policy": "allowed",
        "field_cost": 0.5, "include_demand": False, "diagonal_access": True,
        "road_setback_m": setback, "water_setback_m": 0, "highway_setback_m": 0,
        "elevation_enabled": False, "elevation_draft": "",
        "exclusion_zones": [{"id": f"z{int(zone * 10)}", "points": [[zone, zone], [zone + 1, zone], [zone + 1, zone + 1]]}],
        "feasible_zones": [], "origin": {"x": zone, "y": 1.5},
    }


def routing(origin_x: float, start: list[float], end: list[float], span: str) -> dict:
    grid = frame(origin_x)
    start_wgs, end_wgs = grid.to_wgs84(start), grid.to_wgs84(end)
    return {
        "start": {"lng": f"{start_wgs[0]:.8f}", "lat": f"{start_wgs[1]:.8f}"},
        "end": {"lng": f"{end_wgs[0]:.8f}", "lat": f"{end_wgs[1]:.8f}"},
        "max_span_m": span, "tower_radius_m": "0.4", "max_turn_deg": "90",
        "road_setback_m": "0", "highway_setback_m": "0", "no_tower_zones": [], "no_cross_zones": [],
        "algorithm_overrides": {"popsize": 8, "max_generations": 1, "max_evaluations": 8, "reference_count": 1},
    }
