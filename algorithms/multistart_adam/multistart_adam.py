from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch

from algorithms.common.scalarization import (
    compute_normalization_from_samples,
    generate_weight_grid,
    normalize_weight_vector,
    scalarize_tchebycheff_numpy,
    scalarize_tchebycheff_torch,
)
from algorithms.common.weiszfeld import compute_demand_ideal_value
from config.project_config import AlgorithmCommonConfig, ModelingConfig, MultiStartAdamConfig
from modeling.evaluator import compute_hard_constraints, evaluate_site_objectives
from modeling.pose import decode_raw_pose


@dataclass(frozen=True)
class MultiStartAdamProblem:
    dem: np.ndarray
    obstacle_mask: np.ndarray
    road_segments: np.ndarray
    dem_tensor: torch.Tensor
    obstacle_tensor: torch.Tensor
    road_segments_tensor: torch.Tensor
    road_voronoi_tensor: torch.Tensor
    demand_points: np.ndarray
    demand_weights: np.ndarray | None
    demand_points_tensor: torch.Tensor
    demand_weights_tensor: torch.Tensor | None
    device: torch.device


@dataclass(frozen=True)
class MultiStartAdamResult:
    normalization: dict[str, float | int]
    runs: list[dict[str, Any]]
    solutions: list[dict[str, Any]]


def initialize_raw_pose_starts(starts_per_weight: int, seed: int, init_eps: float, device: torch.device) -> torch.Tensor:
    if starts_per_weight <= 0:
        raise ValueError("starts_per_weight must be positive")
    if not (0.0 < init_eps < 0.5):
        raise ValueError("init_eps must be in (0, 0.5)")
    generator = torch.Generator(device=device)
    generator.manual_seed(int(seed))
    u = torch.rand((starts_per_weight, 3), dtype=torch.float32, device=device, generator=generator)
    u = init_eps + (1.0 - 2.0 * init_eps) * u
    return torch.logit(u)


def evaluate_raw_pose_batch(
    problem: MultiStartAdamProblem,
    modeling: ModelingConfig,
    raw_pose_batch: np.ndarray,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    raw = torch.as_tensor(raw_pose_batch, dtype=torch.float32, device=problem.device)
    with torch.no_grad():
        pose = decode_raw_pose(raw, problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m)
        objectives_t = evaluate_site_objectives(
            problem.dem_tensor,
            problem.obstacle_tensor,
            problem.road_segments_tensor,
            problem.road_voronoi_tensor,
            problem.demand_points_tensor,
            problem.demand_weights_tensor,
            pose,
            modeling.rect_w_m,
            modeling.rect_h_m,
            modeling.soft_mask_sharpness,
        )
    objectives = {name: value.detach().cpu().numpy().astype(np.float64) for name, value in objectives_t.items()}
    return pose.detach().cpu().numpy().astype(np.float64), objectives


def compute_normalization(
    problem: MultiStartAdamProblem,
    modeling: ModelingConfig,
    common: AlgorithmCommonConfig,
) -> dict[str, float | int]:
    if common.normalization_samples <= 0:
        raise ValueError("normalization_samples must be positive")
    rng = np.random.default_rng(common.normalization_seed)
    raw = rng.normal(size=(common.normalization_samples, 3)).astype(np.float32)
    _, objectives = evaluate_raw_pose_batch(problem, modeling, raw)
    demand_ideal = compute_demand_ideal_value(
        problem.demand_points,
        problem.demand_weights,
        common.weiszfeld_max_iters,
        common.weiszfeld_tol,
        common.weiszfeld_eps,
    )
    return compute_normalization_from_samples(
        objectives,
        demand_ideal,
        common.normalization_scale_percentile,
        common.normalization_samples,
        common.normalization_seed,
    )


def _solution_record(
    run_id: int,
    preference_id: int,
    start_id: int,
    best_step: int,
    weights: np.ndarray,
    raw_pose: np.ndarray,
    pose: np.ndarray,
    scalar: float,
    objectives: dict[str, np.ndarray],
    hard: dict[str, torch.Tensor],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "preference_id": preference_id,
        "start_id": start_id,
        "best_step": best_step,
        "weight_dem": float(weights[0]),
        "weight_road": float(weights[1]),
        "weight_demand": float(weights[2]),
        "raw_x": float(raw_pose[0]),
        "raw_y": float(raw_pose[1]),
        "raw_theta": float(raw_pose[2]),
        "x": float(pose[0]),
        "y": float(pose[1]),
        "theta": float(pose[2]),
        "scalar": float(scalar),
        "dem_soft": float(objectives["dem_soft"][0]),
        "obstacle_soft": float(objectives["obstacle_soft"][0]),
        "road_distance": float(objectives["road_distance"][0]),
        "demand_distance": float(objectives["demand_distance"][0]),
        "dem_hard_var": float(hard["dem_hard_var"][0].detach().cpu().item()),
        "dem_hard_range": float(hard["dem_hard_range"][0].detach().cpu().item()),
        "obstacle_hard_count": float(hard["obstacle_hard_count"][0].detach().cpu().item()),
        "obstacle_hard_ratio": float(hard["obstacle_hard_ratio"][0].detach().cpu().item()),
        "is_feasible": bool(hard["is_feasible"][0].detach().cpu().item()),
    }


def _update_best(
    raw_pose_batch: torch.Tensor,
    scalar_per_start: torch.Tensor,
    step: int,
    best_scalar: torch.Tensor,
    best_raw_pose: torch.Tensor,
    best_step: torch.Tensor,
) -> None:
    with torch.no_grad():
        improved = scalar_per_start < best_scalar
        if torch.any(improved):
            best_scalar[improved] = scalar_per_start[improved].detach()
            best_raw_pose[improved] = raw_pose_batch[improved].detach().clone()
            best_step[improved] = int(step)


def _evaluate_scalar_torch(
    problem: MultiStartAdamProblem,
    modeling: ModelingConfig,
    raw_pose_batch: torch.Tensor,
    weights: np.ndarray,
    normalization: dict[str, float | int],
    common: AlgorithmCommonConfig,
) -> torch.Tensor:
    pose_batch = decode_raw_pose(raw_pose_batch, problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m)
    objectives = evaluate_site_objectives(
        problem.dem_tensor,
        problem.obstacle_tensor,
        problem.road_segments_tensor,
        problem.road_voronoi_tensor,
        problem.demand_points_tensor,
        problem.demand_weights_tensor,
        pose_batch,
        modeling.rect_w_m,
        modeling.rect_h_m,
        modeling.soft_mask_sharpness,
    )
    return scalarize_tchebycheff_torch(
        objectives,
        torch.as_tensor(weights, dtype=raw_pose_batch.dtype, device=raw_pose_batch.device),
        normalization,
        common.obstacle_penalty_scale,
        common.scalarization_eps,
    )


def run_multistart_adam_search(
    problem: MultiStartAdamProblem,
    modeling: ModelingConfig,
    common: AlgorithmCommonConfig,
    config: MultiStartAdamConfig,
    weights: list[np.ndarray] | None = None,
) -> MultiStartAdamResult:
    if config.algorithm_name != "multistart_adam":
        raise ValueError(f"algorithm_name must be 'multistart_adam', got {config.algorithm_name!r}")
    if config.starts_per_weight <= 0 or config.max_steps <= 0 or config.learning_rate <= 0:
        raise ValueError("starts_per_weight, max_steps, and learning_rate must be positive")
    normalization = compute_normalization(problem, modeling, common)
    weight_vectors = weights if weights is not None else generate_weight_grid(common.weight_grid_step, common.min_weight)
    runs: list[dict[str, Any]] = []
    solutions: list[dict[str, Any]] = []
    run_id = 0
    for weight_index, weight in enumerate(weight_vectors):
        w = normalize_weight_vector(weight, common.min_weight)
        preference_seed = int(config.seed + weight_index)
        raw_pose_batch = initialize_raw_pose_starts(
            config.starts_per_weight,
            preference_seed,
            config.init_eps,
            problem.device,
        ).requires_grad_(True)
        optimizer = torch.optim.Adam([raw_pose_batch], lr=config.learning_rate)
        best_scalar = torch.full((config.starts_per_weight,), float("inf"), dtype=torch.float32, device=problem.device)
        best_raw_pose = torch.empty_like(raw_pose_batch)
        best_step = torch.full((config.starts_per_weight,), -1, dtype=torch.long, device=problem.device)
        for step in range(config.max_steps):
            optimizer.zero_grad()
            scalar_per_start = _evaluate_scalar_torch(problem, modeling, raw_pose_batch, w, normalization, common)
            _update_best(raw_pose_batch, scalar_per_start, step, best_scalar, best_raw_pose, best_step)
            scalar_per_start.sum().backward()
            optimizer.step()
        with torch.no_grad():
            final_scalar = _evaluate_scalar_torch(problem, modeling, raw_pose_batch, w, normalization, common)
            _update_best(raw_pose_batch, final_scalar, config.max_steps, best_scalar, best_raw_pose, best_step)
        runs.append(
            {
                "preference_id": weight_index,
                "weight_index": weight_index,
                "seed": preference_seed,
                "starts_per_weight": int(config.starts_per_weight),
                "max_steps": int(config.max_steps),
                "learning_rate": float(config.learning_rate),
                "weight_dem": float(w[0]),
                "weight_road": float(w[1]),
                "weight_demand": float(w[2]),
                "best_scalar": float(best_scalar.min().detach().cpu().item()),
            }
        )
        best_raw_np = best_raw_pose.detach().cpu().numpy().astype(np.float64)
        pose, objectives = evaluate_raw_pose_batch(problem, modeling, best_raw_np)
        scalars = scalarize_tchebycheff_numpy(
            objectives,
            w,
            normalization,
            common.obstacle_penalty_scale,
            common.scalarization_eps,
        )
        hard = compute_hard_constraints(
            problem.dem,
            problem.obstacle_mask,
            torch.as_tensor(pose, dtype=torch.float32, device=problem.device),
            modeling.rect_w_m,
            modeling.rect_h_m,
            device=str(problem.device),
        )
        best_steps_np = best_step.detach().cpu().numpy().astype(np.int64)
        for start_id in range(config.starts_per_weight):
            row_objectives = {name: value[start_id : start_id + 1] for name, value in objectives.items()}
            row_hard = {name: value[start_id : start_id + 1] for name, value in hard.items()}
            solutions.append(
                _solution_record(
                    run_id,
                    weight_index,
                    start_id,
                    int(best_steps_np[start_id]),
                    w,
                    best_raw_np[start_id],
                    pose[start_id],
                    float(scalars[start_id]),
                    row_objectives,
                    row_hard,
                )
            )
            run_id += 1
    return MultiStartAdamResult(normalization=normalization, runs=runs, solutions=solutions)
