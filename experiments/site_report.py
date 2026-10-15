"""Read-only construction report for one already chosen site. It does not run a search."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from experiments.constraint_mask import compose_constraint_masks, policy_from_form, polygons_from_form
from modeling.access_path import DEFAULT_ACCESS_SLOPE_LIMIT_DEG, access_warning
from modeling.construction_cost import TerrainHaulCost
from modeling.footprint_terrain import footprint_terrain
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
    obstacle_mask: np.ndarray | None = None,
    allow_unreachable: bool = False,
    constraint_form: dict[str, object] | None = None,
) -> dict[str, object]:
    from experiments.scene_store import ensure_scene_readable

    directory = Path(scene_dir)
    ensure_scene_readable(directory)
    dem = np.load(directory / "dem_1m.npy")
    segments = np.load(directory / "road_segments_local.npy")
    ensure_scene_readable(directory)
    slope = footprint_max_slope_deg(dem, (x, y, theta), rect_w_m, rect_h_m)
    if obstacle_mask is not None and constraint_form is not None:
        raise ValueError("obstacle_mask and constraint_form cannot both be provided")
    if constraint_form is not None:
        obstacle_mask = site_report_hard_mask(directory, constraint_form)
    elif obstacle_mask is None:
        mask_path = directory / "obstacle_mask_1m.npy"
        if not mask_path.is_file():
            raise FileNotFoundError(f"场景 {directory.name} 缺少 obstacle_mask_1m.npy，无法计算进站路径")
        obstacle_mask = np.load(mask_path)
    if obstacle_mask.shape != dem.shape:
        raise ValueError("obstacle mask must match the DEM shape")
    buildable = obstacle_mask == 0
    haul = TerrainHaulCost()
    report: dict[str, object] = {
        "footprint_slope_deg": slope,
        "slope_limit_deg": slope_limit_deg,
        "access_rise_m": None,
        "access_slope_deg": None,
        "access_warning": False,
        "road_haul_m": None,
        "offroad_haul_m": None,
        "haul_rise_m": None,
        "haul_path": None,
    }
    try:
        approach = haul.approach((x, y), segments, dem, buildable)
        report.update({
            "access_rise_m": approach["access_rise_m"],
            "access_slope_deg": approach["max_slope_deg"],
            "access_warning": access_warning(float(approach["max_slope_deg"]), access_slope_limit_deg),
            "offroad_haul_m": approach["offroad_m"],
            "haul_rise_m": approach["access_rise_m"],
            "haul_path": approach["points"],
        })
        if origin is not None:
            route = haul.route(origin, (x, y), segments, dem, buildable)
            report.update({
                "road_haul_m": route["road_m"],
                "offroad_haul_m": route["offroad_m"],
                "haul_rise_m": route["access_rise_m"],
                "haul_path": route["points"],
            })
    except ValueError as exc:
        if not allow_unreachable:
            raise
        report["access_error"] = str(exc)
    return report


def site_report_hard_mask(scene_dir: str | Path, constraint_form: dict[str, object]) -> np.ndarray:
    """Compose the report mask with the same policy and polygon helpers as a search."""

    directory = Path(scene_dir)
    landuse_path = directory / "landuse_1m.npy"
    if not landuse_path.is_file():
        raise FileNotFoundError(f"scene {directory.name} is missing landuse_1m.npy")
    landuse = np.load(landuse_path)
    hard, _soft = compose_constraint_masks(
        landuse,
        polygons_from_form(constraint_form),
        policy_from_form(constraint_form),
        polygons_from_form(constraint_form, "feasible_zones"),
    )
    return hard


def build_footprint_terrain(
    scene_dir: str | Path,
    x: float,
    y: float,
    theta: float,
    rect_w_m: float,
    rect_h_m: float,
) -> dict[str, object]:
    directory = Path(scene_dir)
    dem = np.load(directory / "dem_1m.npy")
    landuse = np.load(directory / "landuse_1m.npy")
    return footprint_terrain(dem, landuse, (x, y, theta), rect_w_m, rect_h_m)
