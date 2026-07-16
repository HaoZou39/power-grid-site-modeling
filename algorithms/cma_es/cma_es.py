from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch

from config.project_config import CMAESConfig, ModelingConfig
from modeling.evaluator import compute_hard_constraints, evaluate_site_objectives
from modeling.pose import decode_raw_pose

from .weiszfeld import compute_demand_ideal_value

OBJECTIVE_NAMES = ("dem_soft", "road_distance", "demand_distance")


@dataclass(frozen=True)
class CMAESProblem:
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
class CMAESResult:
    normalization: dict[str, float | int]
    runs: list[dict[str, Any]]
    solutions: list[dict[str, Any]]


def normalize_weight_vector(weights: np.ndarray, min_weight: float) -> np.ndarray:
    w = np.asarray(weights, dtype=np.float64)
    if w.shape != (3,):
        raise ValueError(f"weights must have shape [3], got {w.shape}")
    if not np.isfinite(w).all() or np.any(w < 0):
        raise ValueError("weights must be finite and non-negative")
    if min_weight < 0:
        raise ValueError("min_weight must be non-negative")
    if min_weight > 0:
        w = np.maximum(w, min_weight)
    total = float(w.sum())
    if total <= 0:
        raise ValueError("weights sum must be positive")
    return w / total


def generate_weight_grid(weight_grid_step: float, min_weight: float) -> list[np.ndarray]:
    if weight_grid_step <= 0 or weight_grid_step > 1:
        raise ValueError("weight_grid_step must be in (0, 1]")
    n = int(round(1.0 / weight_grid_step))
    if not np.isclose(n * weight_grid_step, 1.0, rtol=0.0, atol=1e-8):
        raise ValueError("weight_grid_step must evenly divide 1.0")
    out: list[np.ndarray] = []
    for i in range(n + 1):
        for j in range(n + 1 - i):
            k = n - i - j
            raw = np.array([i, j, k], dtype=np.float64) / float(n)
            out.append(normalize_weight_vector(raw, min_weight))
    return out


def scalarize_tchebycheff(
    objectives: dict[str, np.ndarray],
    weights: np.ndarray,
    normalization: dict[str, float | int],
    obstacle_penalty_scale: float,
) -> np.ndarray:
    if obstacle_penalty_scale < 0:
        raise ValueError("obstacle_penalty_scale must be non-negative")
    values = []
    for objective_name, short_name in zip(OBJECTIVE_NAMES, ("dem", "road", "demand"), strict=True):
        objective = np.asarray(objectives[objective_name], dtype=np.float64)
        ideal = float(normalization[f"ideal_{short_name}"])
        scale = float(normalization[f"scale_{short_name}"])
        if scale <= 0:
            raise ValueError(f"scale_{short_name} must be positive")
        values.append(np.maximum(0.0, (objective - ideal) / scale))
    stacked = np.stack(values, axis=1)
    obstacle = np.asarray(objectives["obstacle_soft"], dtype=np.float64)
    return np.max(stacked * weights[None, :], axis=1) + obstacle_penalty_scale * obstacle


def evaluate_raw_pose_batch(
    problem: CMAESProblem,
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
    problem: CMAESProblem,
    modeling: ModelingConfig,
    config: CMAESConfig,
) -> dict[str, float | int]:
    if config.normalization_samples <= 0:
        raise ValueError("normalization_samples must be positive")
    rng = np.random.default_rng(config.seed)
    raw = rng.normal(size=(config.normalization_samples, 3)).astype(np.float32)
    _, objectives = evaluate_raw_pose_batch(problem, modeling, raw)
    demand_ideal = compute_demand_ideal_value(
        problem.demand_points,
        problem.demand_weights,
        config.weiszfeld_max_iters,
        config.weiszfeld_tol,
        config.weiszfeld_eps,
    )
    ideals = {"dem": 0.0, "road": 0.0, "demand": demand_ideal}
    scales: dict[str, float] = {}
    for objective_name, short_name in zip(OBJECTIVE_NAMES, ("dem", "road", "demand"), strict=True):
        delta = np.maximum(0.0, objectives[objective_name] - ideals[short_name])
        scale = float(np.percentile(delta, config.normalization_scale_percentile))
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError(f"normalization scale for {objective_name} must be positive")
        scales[short_name] = scale
    return {
        "ideal_dem": ideals["dem"],
        "ideal_road": ideals["road"],
        "ideal_demand": ideals["demand"],
        "scale_dem": scales["dem"],
        "scale_road": scales["road"],
        "scale_demand": scales["demand"],
        "scale_percentile": float(config.normalization_scale_percentile),
        "normalization_samples": int(config.normalization_samples),
        "normalization_seed": int(config.seed),
    }


def _solution_record(
    run_id: int,
    weights: np.ndarray,
    raw_pose: np.ndarray,
    pose: np.ndarray,
    scalar: float,
    objectives: dict[str, np.ndarray],
    hard: dict[str, torch.Tensor],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
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


def run_cma_es_search(
    problem: CMAESProblem,
    modeling: ModelingConfig,
    config: CMAESConfig,
    weights: list[np.ndarray] | None = None,
) -> CMAESResult:
    try:
        import cma
    except ImportError as exc:
        raise ImportError("CMA-ES requires the 'cma' package. Install it in the torch311 environment.") from exc
    if config.algorithm_name != "cma_es":
        raise ValueError(f"algorithm_name must be 'cma_es', got {config.algorithm_name!r}")
    if config.popsize <= 0 or config.sigma0 <= 0 or config.max_iters <= 0 or config.restarts_per_weight <= 0:
        raise ValueError("popsize, sigma0, max_iters, and restarts_per_weight must be positive")
    normalization = compute_normalization(problem, modeling, config)
    weight_vectors = weights if weights is not None else generate_weight_grid(config.weight_grid_step, config.min_weight)
    runs: list[dict[str, Any]] = []
    solutions: list[dict[str, Any]] = []
    run_id = 0
    for weight_index, weight in enumerate(weight_vectors):
        w = normalize_weight_vector(weight, config.min_weight)
        for restart in range(config.restarts_per_weight):
            run_seed = int(config.seed + 1000 * weight_index + restart)
            es = cma.CMAEvolutionStrategy(
                [0.0, 0.0, 0.0],
                config.sigma0,
                {"popsize": config.popsize, "seed": run_seed, "verbose": -9},
            )
            best_raw: np.ndarray | None = None
            best_scalar = float("inf")
            iterations = 0
            while not es.stop() and iterations < config.max_iters:
                candidates = np.asarray(es.ask(), dtype=np.float32)
                _, objectives = evaluate_raw_pose_batch(problem, modeling, candidates)
                scalars = scalarize_tchebycheff(objectives, w, normalization, config.obstacle_penalty_scale)
                es.tell(candidates.tolist(), scalars.tolist())
                idx = int(np.argmin(scalars))
                if float(scalars[idx]) < best_scalar:
                    best_scalar = float(scalars[idx])
                    best_raw = candidates[idx].astype(np.float64)
                iterations += 1
            if best_raw is None:
                raise RuntimeError("CMA-ES produced no candidates")
            pose, objectives = evaluate_raw_pose_batch(problem, modeling, best_raw[None, :])
            scalar = float(scalarize_tchebycheff(objectives, w, normalization, config.obstacle_penalty_scale)[0])
            hard = compute_hard_constraints(
                problem.dem,
                problem.obstacle_mask,
                torch.as_tensor(pose, dtype=torch.float32, device=problem.device),
                modeling.rect_w_m,
                modeling.rect_h_m,
                device=str(problem.device),
            )
            runs.append(
                {
                    "run_id": run_id,
                    "weight_index": weight_index,
                    "restart": restart,
                    "seed": run_seed,
                    "weight_dem": float(w[0]),
                    "weight_road": float(w[1]),
                    "weight_demand": float(w[2]),
                    "iterations": iterations,
                    "best_scalar": scalar,
                    "stop": ";".join(sorted(es.stop().keys())),
                }
            )
            solutions.append(_solution_record(run_id, w, best_raw, pose[0], scalar, objectives, hard))
            run_id += 1
    return CMAESResult(normalization=normalization, runs=runs, solutions=solutions)
