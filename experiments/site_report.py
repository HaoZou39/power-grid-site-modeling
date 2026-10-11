"""Read-only construction report for one already chosen site. It does not run a search."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from modeling.access_path import DEFAULT_ACCESS_SLOPE_LIMIT_DEG, access_warning
from modeling.construction_cost import TerrainHaulCost
from modeling.slope import DEFAULT_SLOPE_LIMIT_DEG, footprint_max_slope_deg


def build_site_report(
    scene_dir: str | Path,
    x: float,
    y: float,
    theta: float,
    rect_w_m: float,
    rect_h_m: float,
    origin: tuple[float, float] | None = None,
    slope_limit_deg: float = DEFAULT_SLOPE_LIMIT_DEG,
    access_slope_limit_deg: float = DEFAULT_ACCESS_SLOPE_LIMIT_DEG,
) -> dict[str, object]:
    directory = Path(scene_dir)
    dem = np.load(directory / "dem_1m.npy")
    segments = np.load(directory / "road_segments_local.npy")
    slope = footprint_max_slope_deg(dem, (x, y, theta), rect_w_m, rect_h_m)
    mask_path = directory / "obstacle_mask_1m.npy"
    if not mask_path.is_file():
        raise FileNotFoundError(f"场景 {directory.name} 缺少 obstacle_mask_1m.npy，无法计算进场路径")
    buildable = np.load(mask_path) == 0
    haul = TerrainHaulCost()
    approach = haul.approach((x, y), segments, dem, buildable)
    report: dict[str, object] = {
        "footprint_slope_deg": slope,
        "slope_limit_deg": slope_limit_deg,
        "access_rise_m": approach["access_rise_m"],
        "access_slope_deg": approach["max_slope_deg"],
        "access_warning": access_warning(float(approach["max_slope_deg"]), access_slope_limit_deg),
        "road_haul_m": None,
        "offroad_haul_m": approach["offroad_m"],
        "haul_rise_m": approach["access_rise_m"],
        "haul_path": approach["points"],
    }
    if origin is not None:
        route = haul.route(origin, (x, y), segments, dem, buildable)
        report["road_haul_m"] = route["road_m"]
        report["offroad_haul_m"] = route["offroad_m"]
        report["haul_rise_m"] = route["access_rise_m"]
        report["haul_path"] = route["points"]
    return report
