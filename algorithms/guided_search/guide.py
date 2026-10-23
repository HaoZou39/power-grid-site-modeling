"""前期梯度引导。

用距离场的插值，加上脚印平整度，把初始种群推进可行区域。需求距离默认不进入这个和。
这一段的和只做引导，不参加后来的支配比较，也不使用直线道路距离。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from algorithms.guided_search.initialization import sample_initial_population
from modeling.evaluator import evaluate_site_objectives
from modeling.haul_field import HaulField, haul_column_names
from modeling.haul_model import UNREACHABLE_M, sample_center_field, torch_field
from modeling.pose import compute_safe_margin, decode_raw_pose


def guide_initial_population(
    problem: Any,
    modeling: Any,
    config: Any,
    field: HaulField,
    pose_bounds: tuple[float, float, float, float] | None = None,
    *,
    allowed_mask: np.ndarray | None = None,
) -> np.ndarray:
    """返回引导若干步之后的 raw pose，shape 为 `[popsize, 3]`。"""

    if config.guide_steps < 0 or config.guide_lr <= 0 or config.refine_sigma <= 0:
        raise ValueError("guide_steps must be non-negative, and guide_lr and refine_sigma must be positive")
    if allowed_mask is None:
        from modeling.context import building_hard_mask

        allowed_mask = building_hard_mask(problem) == 0
    bounds = initialization_bounds(problem, modeling, pose_bounds)
    feasible = getattr(problem, "initialization_feasible_zones", ())
    exclusions = getattr(problem, "initialization_exclusion_zones", ())

    def allowed_centers(raw_values):
        from matplotlib.path import Path

        with torch.no_grad():
            values = torch.as_tensor(raw_values, dtype=torch.float32, device=problem.device)
            pose = decode_raw_pose(values, problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m, pose_bounds)
            xy = pose[:, :2].cpu().numpy()
        cells = xy.astype(np.intp)
        valid = allowed_mask[cells[:, 1], cells[:, 0]].copy()
        if feasible:
            valid &= np.logical_or.reduce([Path(ring).contains_points(xy) for ring in feasible])
        for ring in exclusions:
            valid &= ~Path(ring).contains_points(xy)
        return valid

    raw_np = sample_initial_population(
        int(config.popsize), int(config.seed), str(config.initialization), float(config.sigma0),
        allowed_mask=allowed_mask, pose_bounds=bounds,
        center_filter=allowed_centers if feasible or exclusions else None,
    )
    if int(config.guide_steps) == 0:
        return raw_np
    raw = torch.tensor(raw_np, dtype=torch.float32, device=problem.device, requires_grad=True)
    packed = pack_haul_guidance(field, problem.device, float(config.guide_obstacle_penalty))
    optimizer = torch.optim.Adam([raw], lr=float(config.guide_lr))
    scales = None
    for _step in range(int(config.guide_steps)):
        optimizer.zero_grad()
        loss, scales = guidance_loss(
            problem,
            modeling,
            raw,
            packed,
            scales,
            bool(config.include_demand),
            pose_bounds,
        )
        loss.sum().backward()
        previous = raw.detach().clone()
        optimizer.step()
        with torch.no_grad():
            valid = torch.as_tensor(allowed_centers(raw), device=raw.device)
            raw[~valid] = previous[~valid]
    return raw.detach().cpu().numpy().astype(np.float64)


def initialization_bounds(
    problem: Any, modeling: Any,
    pose_bounds: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float]:
    decode_raw_pose(torch.zeros((1, 3)), problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m, pose_bounds)
    margin = compute_safe_margin(modeling.rect_w_m, modeling.rect_h_m)
    return pose_bounds if pose_bounds is not None else (
        margin, problem.dem.shape[1] - 1 - margin, margin, problem.dem.shape[0] - 1 - margin,
    )


_FIELD_ARRAY = {
    "offroad_haul_m": "offroad_m",
    "haul_rise_m": "access_rise_m",
    "road_haul_m": "road_m",
}


def guidance_terms(
    problem: Any,
    modeling: Any,
    raw_pose: torch.Tensor,
    packed: dict[str, torch.Tensor],
    scales: dict[str, float],
    include_demand: bool = False,
) -> dict[str, torch.Tensor]:
    """可微的引导项。直线道路距离在别处计算，不放进这里。"""

    pose, objectives = _decision_forward(problem, modeling, raw_pose)
    return _terms_from(pose, objectives, packed, scales, include_demand)


def guidance_loss(
    problem: Any,
    modeling: Any,
    raw_pose: torch.Tensor,
    packed: dict[str, torch.Tensor],
    scales: dict[str, float] | None,
    include_demand: bool = False,
    pose_bounds: tuple[float, float, float, float] | None = None,
) -> tuple[torch.Tensor, dict[str, float]]:
    """返回加总后的引导损失，以及用来归一化的尺度。这个和只用于引导。"""

    pose, objectives = _decision_forward(problem, modeling, raw_pose, pose_bounds)
    if scales is None:
        scales = _scales_from(objectives, packed, include_demand)
    terms = _terms_from(pose, objectives, packed, scales, include_demand)
    total = torch.zeros(raw_pose.shape[0], dtype=raw_pose.dtype, device=raw_pose.device)
    for value in terms.values():
        total = total + value
    return total, scales


def _decision_forward(
    problem: Any,
    modeling: Any,
    raw_pose: torch.Tensor,
    pose_bounds: tuple[float, float, float, float] | None = None,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """一次前向，得到位姿以及脚印平整度、需求距离和软障碍。"""

    pose = decode_raw_pose(raw_pose, problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m, pose_bounds)
    objectives = evaluate_site_objectives(
        problem.dem_tensor,
        _soft_obstacle(problem),
        problem.road_segments_tensor,
        problem.road_voronoi_tensor,
        problem.demand_points_tensor,
        problem.demand_weights_tensor,
        pose,
        modeling.rect_w_m,
        modeling.rect_h_m,
        modeling.soft_mask_sharpness,
    )
    return pose, objectives


def _terms_from(
    pose: torch.Tensor,
    objectives: dict[str, torch.Tensor],
    packed: dict[str, torch.Tensor],
    scales: dict[str, float],
    include_demand: bool,
) -> dict[str, torch.Tensor]:
    x = pose[:, 0]
    y = pose[:, 1]
    terms = {
        "dem_soft": objectives["dem_soft"] / scales["dem_soft"],
        "obstacle_soft": packed["penalty"] * objectives["obstacle_soft"],
    }
    if include_demand:
        terms["demand_distance"] = objectives["demand_distance"] / scales["demand_distance"]
    for name in haul_column_names("road_haul_m" in packed):
        terms[name] = sample_center_field(packed[name], x, y) / scales[name]
    return terms


def _scales_from(
    objectives: dict[str, torch.Tensor],
    packed: dict[str, torch.Tensor],
    include_demand: bool,
) -> dict[str, float]:
    scales = {
        "dem_soft": _positive_scale(objectives["dem_soft"].detach().cpu().numpy()),
    }
    if include_demand:
        scales["demand_distance"] = _positive_scale(objectives["demand_distance"].detach().cpu().numpy())
    for name in haul_column_names("road_haul_m" in packed):
        scales[name] = _positive_scale(packed[name].detach().cpu().numpy(), ignore=_sentinel_mask(packed[name]))
    return scales


def _sentinel_mask(values: torch.Tensor) -> np.ndarray:
    return values.detach().cpu().numpy() >= UNREACHABLE_M


def _positive_scale(values: np.ndarray, ignore: np.ndarray | None = None) -> float:
    picked = np.asarray(values, dtype=np.float64).reshape(-1)
    if ignore is not None:
        picked = picked[~np.asarray(ignore, dtype=bool).reshape(-1)]
    picked = picked[np.isfinite(picked)]
    if picked.size == 0:
        return 1.0
    return float(max(np.percentile(np.abs(picked), 95.0), 1e-6))


def pack_haul_guidance(field: HaulField, device: torch.device, obstacle_penalty: float) -> dict[str, torch.Tensor]:
    names = haul_column_names(field.road_m is not None)
    packed = {
        "penalty": torch.tensor(obstacle_penalty, dtype=torch.float32, device=device),
    }
    for name in names:
        values = getattr(field, _FIELD_ARRAY[name])
        packed[name] = torch_field(values, field.reachable).to(device)
    return packed


def _soft_obstacle(problem: Any) -> torch.Tensor:
    from modeling.context import soft_obstacle_tensor

    return soft_obstacle_tensor(problem)
