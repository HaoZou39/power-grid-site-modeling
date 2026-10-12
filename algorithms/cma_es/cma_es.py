"""研究入口使用的单目标搜索。

`CmaEsSearch` 先把三个目标收成一个标量，再调用 `cma` 库。权重和切比雪夫写在这个类里。
实验文件的读写留在 `cma_es_main.py`。决策界面不使用这个搜索。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch

from config.project_config import AlgorithmCommonConfig, CMAESConfig, ModelingConfig
from algorithms.common.search import SiteSearch
from algorithms.common.scalarization import (
    OBJECTIVE_NAMES,
    compute_normalization_from_samples,
    generate_weight_grid,
    normalize_weight_vector,
    scalarize_tchebycheff_numpy as scalarize_tchebycheff,
)
from algorithms.common.weiszfeld import compute_demand_ideal_value
from modeling.evaluator import compute_hard_constraints, evaluate_site_objectives
from modeling.context import SiteProblemContext, soft_obstacle_tensor
from modeling.pose import decode_raw_pose

CMAESProblem = SiteProblemContext


@dataclass(frozen=True)
class CMAESResult:
    normalization: dict[str, float | int]
    runs: list[dict[str, Any]]
    solutions: list[dict[str, Any]]


def evaluate_raw_pose_batch(
    problem: CMAESProblem,
    modeling: ModelingConfig,
    raw_pose_batch: np.ndarray,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    raw = torch.as_tensor(raw_pose_batch, dtype=torch.float32, device=problem.device)
    with torch.no_grad():
        pose = decode_raw_pose(raw, problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m)
    return evaluate_pose_batch(problem, modeling, pose)


def evaluate_pose_batch(
    problem: CMAESProblem,
    modeling: ModelingConfig,
    pose_batch: np.ndarray | torch.Tensor,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Decoded `[N, 3]` poses in 1 m local meters, not raw search genes."""

    pose = torch.as_tensor(pose_batch, dtype=torch.float32, device=problem.device)
    with torch.no_grad():
        objectives_t = evaluate_site_objectives(
            problem.dem_tensor,
            soft_obstacle_tensor(problem),
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


class CmaEsSearch(SiteSearch):
    """把目标向量收成标量后再运行 CMA-ES。

    改权重网格或切比雪夫时改 `search`。不要把这些写进 `SiteSearch`。
    """

    algorithm_name = "cma_es"

    def __init__(
        self,
        common: AlgorithmCommonConfig,
        config: CMAESConfig,
        weights: list[np.ndarray] | None = None,
    ) -> None:
        self.common = common
        self.config = config
        self.weights = weights

    def search(self, problem: Any, modeling: Any) -> CMAESResult:
        common = self.common
        config = self.config
        weights = self.weights
        try:
            import cma
        except ImportError as exc:
            raise ImportError("CMA-ES requires the 'cma' package. Install it in the torch311 environment.") from exc
        if config.algorithm_name != self.algorithm_name:
            raise ValueError(f"algorithm_name must be {self.algorithm_name!r}, got {config.algorithm_name!r}")
        if config.popsize <= 0 or config.sigma0 <= 0 or config.max_iters <= 0 or config.restarts_per_weight <= 0:
            raise ValueError("popsize, sigma0, max_iters, and restarts_per_weight must be positive")
        normalization = compute_normalization(problem, modeling, common)
        weight_vectors = weights if weights is not None else generate_weight_grid(common.weight_grid_step, common.min_weight)
        runs: list[dict[str, Any]] = []
        solutions: list[dict[str, Any]] = []
        run_id = 0
        for weight_index, weight in enumerate(weight_vectors):
            w = normalize_weight_vector(weight, common.min_weight)
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
                    scalars = scalarize_tchebycheff(
                        objectives,
                        w,
                        normalization,
                        common.obstacle_penalty_scale,
                        common.scalarization_eps,
                    )
                    es.tell(candidates.tolist(), scalars.tolist())
                    idx = int(np.argmin(scalars))
                    if float(scalars[idx]) < best_scalar:
                        best_scalar = float(scalars[idx])
                        best_raw = candidates[idx].astype(np.float64)
                    iterations += 1
                if best_raw is None:
                    raise RuntimeError("CMA-ES produced no candidates")
                pose, objectives = evaluate_raw_pose_batch(problem, modeling, best_raw[None, :])
                scalar = float(
                    scalarize_tchebycheff(
                        objectives,
                        w,
                        normalization,
                        common.obstacle_penalty_scale,
                        common.scalarization_eps,
                    )[0]
                )
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


def run_cma_es_search(
    problem: CMAESProblem,
    modeling: ModelingConfig,
    common: AlgorithmCommonConfig,
    config: CMAESConfig,
    weights: list[np.ndarray] | None = None,
) -> CMAESResult:
    """Search one scene by constructing the CMA-ES subclass."""

    return CmaEsSearch(common, config, weights).search(problem, modeling)
