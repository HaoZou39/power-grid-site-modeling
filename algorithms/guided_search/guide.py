"""前期梯度引导。

用距离场的插值，加上脚印平整度，把初始种群推进可行区域。需求距离默认不进入这个和。
这一段的和只做引导，不参加后来的支配比较，也不使用直线道路距离。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from config.project_config import AlgorithmCommonConfig
from modeling.evaluator import evaluate_site_objectives
from modeling.haul_field import HaulField, haul_column_names
from modeling.haul_model import UNREACHABLE_M, sample_center_field, torch_field
from modeling.pose import decode_raw_pose


def guide_initial_population(
    problem: Any,
    modeling: Any,
    config: Any,
    field: HaulField,
    pose_bounds: tuple[float, float, float, float] | None = None,
) -> np.ndarray:
    """返回引导若干步之后的 raw pose，shape 为 `[popsize, 3]`。"""

    if config.guide_steps < 0 or config.guide_lr <= 0 or config.refine_sigma <= 0:
        raise ValueError("guide_steps must be non-negative, and guide_lr and refine_sigma must be positive")
    rng = np.random.default_rng(int(config.seed))
    raw_np = rng.normal(0.0, float(config.sigma0), size=(int(config.popsize), 3)).astype(np.float32)
    if int(config.guide_steps) == 0:
        return raw_np
    raw = torch.tensor(raw_np, dtype=torch.float32, device=problem.device, requires_grad=True)
    packed = pack_haul_guidance(field, problem.device)
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
            bool(getattr(config, "include_demand", False)),
            pose_bounds,
        )
        loss.sum().backward()
        optimizer.step()
    return raw.detach().cpu().numpy().astype(np.float64)


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


def pack_haul_guidance(field: HaulField, device: torch.device) -> dict[str, torch.Tensor]:
    names = haul_column_names(field.road_m is not None)
    packed = {
        "penalty": torch.tensor(AlgorithmCommonConfig().obstacle_penalty_scale, dtype=torch.float32, device=device),
    }
    for name in names:
        values = getattr(field, _FIELD_ARRAY[name])
        packed[name] = torch_field(values, field.reachable).to(device)
    return packed


LOCAL_MODES = ("gradient", "neighbor", "blend", "crowding")


def worst_objective_index(values: np.ndarray) -> np.ndarray:
    """每个人归一化之后最大的那一项。值越大越差。"""

    if values.ndim != 2 or values.shape[0] == 0:
        raise ValueError("values must have shape [N, K]")
    span = np.maximum(values.max(axis=0) - values.min(axis=0), 1e-6)
    normalized = (values - values.min(axis=0)) / span
    return np.argmax(normalized, axis=1)


def best_on_objective(values: np.ndarray, column: int) -> int:
    """这一项上目标值最小的个体。"""

    if column < 0 or column >= values.shape[1]:
        raise ValueError("objective column is outside the value matrix")
    return int(np.argmin(values[:, column]))


def local_step_size(step: int, steps: int, start: float, end: float) -> float:
    """局部搜索的学习率。一步时保持起点，多步时线性降到终点。"""

    if steps <= 1:
        return float(start)
    weight = step / (steps - 1)
    return float(start + (end - start) * weight)


def local_polish(
    genes: np.ndarray,
    evaluate: Any,
    problem: Any,
    modeling: Any,
    config: Any,
    field: HaulField,
    pose_bounds: tuple[float, float, float, float] | None = None,
) -> np.ndarray:
    """在进化之后对每个人走几步。方向是自身梯度、他人，或两者相加。"""

    mode = str(config.local_mode)
    if mode not in LOCAL_MODES:
        raise ValueError(f"local_mode must be one of {LOCAL_MODES}, got {mode!r}")
    steps = int(config.local_steps)
    if steps <= 0:
        return np.asarray(genes, dtype=np.float64)
    if float(config.local_lr) <= 0 or float(config.local_lr_end) <= 0:
        raise ValueError("local_lr and local_lr_end must be positive")
    raw = torch.tensor(np.asarray(genes, dtype=np.float32), dtype=torch.float32, device=problem.device)
    include_demand = bool(getattr(config, "include_demand", False))
    names = (("dem_soft", "demand_distance") if include_demand else ("dem_soft",)) + haul_column_names(field.road_m is not None)
    packed = pack_haul_guidance(field, problem.device)
    beta = 0.0 if mode == "gradient" else float(config.local_beta)
    use_gradient = mode in {"gradient", "blend"}
    for step in range(steps):
        learning_rate = local_step_size(step, steps, config.local_lr, config.local_lr_end)
        values, _violation = evaluate(raw.detach().cpu().numpy())
        worst = worst_objective_index(values)
        crowding = _crowding(values) if mode == "crowding" else None
        neighbor = _neighbor_hat(raw.detach(), values, worst, crowding)
        grad_hat = (
            _gradient_hat(raw, names, worst, problem, modeling, packed, pose_bounds)
            if use_gradient
            else torch.zeros_like(raw)
        )
        if mode == "gradient":
            direction = -grad_hat
        elif mode in {"neighbor", "crowding"}:
            direction = neighbor
        else:
            direction = -grad_hat + beta * neighbor
        raw = (raw.detach() + learning_rate * direction).detach()
    return raw.cpu().numpy().astype(np.float64)


def _gradient_hat(
    raw: torch.Tensor,
    names: tuple[str, ...],
    worst: np.ndarray,
    problem: Any,
    modeling: Any,
    packed: dict[str, torch.Tensor],
    pose_bounds: tuple[float, float, float, float] | None = None,
) -> torch.Tensor:
    leaf = raw.detach().requires_grad_(True)
    pose, objectives = _decision_forward(problem, modeling, leaf, pose_bounds)
    chosen = torch.zeros((), dtype=leaf.dtype, device=leaf.device)
    for index, column in enumerate(worst):
        chosen = chosen + _objective_column(names[int(column)], pose, objectives, packed)[index]
    chosen.backward()
    if leaf.grad is None:
        return torch.zeros_like(raw)
    grad = leaf.grad.detach()
    norm = grad.norm(dim=1, keepdim=True).clamp_min(1e-8)
    return grad / norm


def _objective_column(
    name: str,
    pose: torch.Tensor,
    objectives: dict[str, torch.Tensor],
    packed: dict[str, torch.Tensor],
) -> torch.Tensor:
    if name in {"dem_soft", "demand_distance"}:
        return objectives[name]
    return sample_center_field(packed[name], pose[:, 0], pose[:, 1])


def _neighbor_hat(
    raw: torch.Tensor,
    values: np.ndarray,
    worst: np.ndarray,
    crowding: np.ndarray | None,
) -> torch.Tensor:
    genes = raw.detach()
    direction = torch.zeros_like(genes)
    for index, column in enumerate(worst):
        if crowding is None:
            target = best_on_objective(values, int(column))
        else:
            target = _less_crowded(crowding, index)
        if target == index:
            continue
        delta = genes[target] - genes[index]
        norm = delta.norm().clamp_min(1e-8)
        direction[index] = delta / norm
    return direction


def _less_crowded(crowding: np.ndarray, index: int) -> int:
    score = np.where(np.isfinite(crowding), crowding, 1e12)
    better = np.flatnonzero(score > score[index] + 1e-12)
    if len(better) == 0:
        return index
    return int(better[np.argmax(score[better])])


def _crowding(values: np.ndarray) -> np.ndarray:
    from algorithms.guided_search.search import Individual, nondominated_sort

    people = [Individual(np.zeros(1), row.astype(np.float64), 0.0) for row in values]
    nondominated_sort(people)
    return np.array([person.crowding for person in people], dtype=np.float64)


def _soft_obstacle(problem: Any) -> torch.Tensor:
    from modeling.context import soft_obstacle_tensor

    return soft_obstacle_tensor(problem)
