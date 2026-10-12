"""Read-only construction report for one already chosen site. It does not run a search."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

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
    obstacle_mask: np.ndarray | None = None,
    allow_unreachable: bool = False,
) -> dict[str, object]:
    directory = Path(scene_dir)
    dem = np.load(directory / "dem_1m.npy")
    segments = np.load(directory / "road_segments_local.npy")
    slope = footprint_max_slope_deg(dem, (x, y, theta), rect_w_m, rect_h_m)
    if obstacle_mask is None:
        mask_path = directory / "obstacle_mask_1m.npy"
        if not mask_path.is_file():
            raise FileNotFoundError(f"场景 {directory.name} 缺少 obstacle_mask_1m.npy，无法计算进场路径")
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


def build_precise_site_report(
    scene_dir: str | Path,
    x: float,
    y: float,
    theta: float,
    rect_w_m: float,
    rect_h_m: float,
    form: dict[str, object],
    device: torch.device,
    soft_mask_sharpness: float,
    origin: tuple[float, float] | None = None,
) -> dict[str, object]:
    """Evaluate one explicit pose with the same model and masks as a search."""

    from experiments.constraint_mask import compose_constraint_masks, polygons_from_form, policy_from_form
    from experiments.problem_context import context_from_arrays, with_constraint_masks
    from modeling.context import soft_obstacle_tensor
    from modeling.evaluator import compute_hard_constraints, evaluate_site_objectives

    directory = Path(scene_dir)
    arrays = {
        "dem": np.load(directory / "dem_1m.npy"),
        "obstacle_mask": np.load(directory / "obstacle_mask_1m.npy"),
        "road_segments": np.load(directory / "road_segments_local.npy"),
        "road_voronoi": np.load(directory / "road_voronoi_1m.npy"),
        "demand_points": np.load(directory / "demand_points.npy"),
    }
    landuse_path = directory / "landuse_1m.npy"
    if not landuse_path.is_file():
        raise FileNotFoundError(f"场景 {directory.name} 缺少 landuse_1m.npy，无法按用地类别合成约束")
    landuse = np.load(landuse_path)
    exclusions = polygons_from_form(form)
    feasible = polygons_from_form(form, "feasible_zones")
    hard_mask, soft_mask = compose_constraint_masks(landuse, exclusions, policy_from_form(form), feasible)
    problem = with_constraint_masks(context_from_arrays(arrays, device), hard_mask, soft_mask)
    pose_batch = torch.tensor([[x, y, theta]], dtype=torch.float32, device=device)
    with torch.no_grad():
        objectives = evaluate_site_objectives(
            problem.dem_tensor,
            soft_obstacle_tensor(problem),
            problem.road_segments_tensor,
            problem.road_voronoi_tensor,
            problem.demand_points_tensor,
            problem.demand_weights_tensor,
            pose_batch,
            rect_w_m,
            rect_h_m,
            soft_mask_sharpness,
        )
        hard = compute_hard_constraints(
            problem.dem,
            problem.obstacle_mask,
            pose_batch,
            rect_w_m,
            rect_h_m,
            device=str(device),
        )
    report = build_site_report(
        directory,
        x,
        y,
        theta,
        rect_w_m,
        rect_h_m,
        origin,
        obstacle_mask=hard_mask,
        allow_unreachable=True,
    )
    report.update({name: _single_value(name, value) for name, value in objectives.items()})
    report.update({name: _single_value(name, value) for name, value in hard.items()})
    return report


def _single_value(name: str, value: torch.Tensor) -> float | bool:
    if value.shape != (1,):
        raise ValueError(f"{name} must have shape [1], got {tuple(value.shape)}")
    item = value.detach().cpu().item()
    return bool(item) if name == "is_feasible" else float(item)
