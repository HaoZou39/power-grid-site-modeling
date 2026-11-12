"""Synthetic 256 m scene for one real CUDA run. It is not an engineering dataset."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from modeling.routing.types import RoutingFrame

SIZE = 256
ORIGIN_X = 221000.0
ORIGIN_Y = 3046000.0
ROAD_Y = 30.0


def frame() -> RoutingFrame:
    return RoutingFrame("EPSG:32651", (1, 0, ORIGIN_X, 0, -1, ORIGIN_Y), SIZE, SIZE)


def write_scene(root: Path, name: str, revision: str) -> Path:
    scene = root / name
    scene.mkdir(parents=True)
    shape = (SIZE, SIZE)
    columns = np.arange(SIZE, dtype=np.float32)
    dem = np.full(shape, 20, np.float32) + columns * np.float32(0.002)
    np.save(scene / "dem_1m.npy", dem)
    np.save(scene / "landuse_1m.npy", np.zeros(shape, np.uint8))
    np.save(scene / "obstacle_mask_1m.npy", np.zeros(shape, np.uint8))
    np.save(scene / "road_segments_local.npy", np.array([[0, ROAD_Y, SIZE - 1, ROAD_Y]], np.float32))
    np.save(scene / "road_segment_kind.npy", np.zeros(1, np.int8))
    np.save(scene / "road_voronoi_1m.npy", np.zeros(shape, np.int64))
    np.save(scene / "demand_points.npy", np.array([[128, 128]], np.float32))
    np.save(scene / "protected_farmland_mask_1m.npy", np.zeros(shape, dtype=bool))
    (scene / "data_metadata.json").write_text(json.dumps({
        "scene_revision": revision,
        "coordinate_units": "utm_m",
        "dem": {
            "reference_crs": "EPSG:32651",
            "target_transform": [1, 0, ORIGIN_X, 0, -1, ORIGIN_Y],
            "shape": [SIZE, SIZE],
        },
    }), encoding="utf-8")
    (scene / "scene.json").write_text("{}\n", encoding="utf-8")
    return scene


def site_plan(setback: float) -> dict:
    return {
        "rect_w_m": 77.0, "rect_h_m": 51.5,
        "field_policy": "allowed", "mountain_policy": "allowed",
        "field_cost": 0.5, "include_demand": False, "diagonal_access": True,
        "road_setback_m": setback, "water_setback_m": 0, "highway_setback_m": 0,
        "elevation_enabled": False, "elevation_draft": "",
        "exclusion_zones": [], "feasible_zones": [],
        "origin": {"x": 128.0, "y": ROAD_Y},
    }


def routing_algorithm() -> dict:
    # 规划正文拒绝冒号，cuda:0 只能在提交时的 algorithm 覆盖里冻结。
    return {
        "search_strategy": "pilot_reference",
        "evolution_backend": "tensor",
        "evaluation_backend": "tensor",
        "devices": ["cuda:0"],
        "popsize": 16,
        "max_generations": 2,
        "max_evaluations": 64,
        "reference_count": 1,
        "evaluation_batch_size": 16,
        "gpu_memory_budget_mib": 8192,
        "seed": 7,
        "pilot": {"initialization_budget_factor": 2, "local_budget_factor": 2, "global_budget_factor": 1},
    }


def routing_plan() -> dict:
    grid = frame()
    start, end = grid.to_wgs84([30, 128]), grid.to_wgs84([220, 128])
    saved = {key: value for key, value in routing_algorithm().items() if key != "devices"}
    return {
        "start": {"lng": f"{start[0]:.8f}", "lat": f"{start[1]:.8f}"},
        "end": {"lng": f"{end[0]:.8f}", "lat": f"{end[1]:.8f}"},
        "max_span_m": "250", "tower_radius_m": "2", "max_turn_deg": "90",
        "road_setback_m": "0", "highway_setback_m": "0",
        "no_tower_zones": [], "no_cross_zones": [],
        "algorithm_overrides": saved,
    }
