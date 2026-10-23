"""决策界面使用的多目标搜索。

种群按支配关系进化，可行站址排在不可行站址前面。这里不使用目标权重。
决策搜索比较脚印平整度、进站长度和进站累计高差。需求点距离默认不参加支配比较，因为需求点仍是随机点；`include_demand` 为真时才加入。有进货原点时再加上沿路长度。到道路的直线距离仍会写入方案表，但不参加支配比较。
演化张量算子在 `tensor_nsga2.py`。目标公式仍在 `modeling/`。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

import numpy as np

from algorithms.common.search import SiteSearch
from modeling.haul_field import haul_column_names
from algorithms.guided_search.evolution import run_evolution, generation_sigma, resolve_evolution_backend, describe_evolution_runtime

# 直线道路距离 road_distance 不在此列。CMA-ES 仍使用 algorithms.common.scalarization.OBJECTIVE_NAMES。
# 没指定进货原点时不比较沿路长度。需求点距离默认不比较。进站相关列的顺序只写在 haul_column_names。
# 最终报告每批的方案数。各方案独立计算，只影响显存。
REPORT_BATCH = 4096


def guided_objective_names(include_road_haul: bool, include_demand: bool = False) -> tuple[str, ...]:
    head = ("dem_soft", "demand_distance") if include_demand else ("dem_soft",)
    return head + haul_column_names(include_road_haul)

class FrontStep:
    """前沿的超体积停住之后才缩小步长。还在明显变好时，步长保持不变。"""

    def __init__(self, sigma: float, shrink: float = 0.8, patience: int = 5, floor: float = 0.05) -> None:
        if sigma <= 0 or not 0 < shrink < 1 or patience < 1 or floor <= 0 or floor > sigma:
            raise ValueError("sigma and floor must be positive, shrink in (0, 1), and patience at least 1")
        self.sigma = float(sigma)
        self.shrink = float(shrink)
        self.patience = int(patience)
        self.floor = float(floor)
        self._stall = 0
        self._archive: list[np.ndarray] = []
        self._reference: np.ndarray | None = None
        self._best = 0.0

    def observe(self, objectives: np.ndarray) -> float:
        """记下这一代的目标。超体积连续多代没有明显增加时，把步长乘 shrink。"""

        rows = [row.copy() for row in np.asarray(objectives, dtype=np.float64) if np.isfinite(row).all()]
        self._archive = _pareto_rows(self._archive + rows)
        if self._reference is None:
            self._reference = _reference_box(self._archive)
            self._best = _hypervolume(self._archive, self._reference)
            return self.sigma
        score = _hypervolume(self._archive, self._reference)
        if score > self._best + max(1e-6, abs(self._best) * 1e-4):
            self._best = score
            self._stall = 0
        else:
            self._stall += 1
            if self._stall >= self.patience:
                self.sigma = max(self.floor, self.sigma * self.shrink)
                self._stall = 0
        return self.sigma


def _reference_box(rows: list[np.ndarray]) -> np.ndarray:
    stacked = np.stack(rows)
    span = np.maximum(stacked.max(axis=0) - stacked.min(axis=0), 1.0)
    return stacked.max(axis=0) + 0.1 * span


def _hypervolume(rows: list[np.ndarray], reference: np.ndarray) -> float:
    points = np.stack(rows)
    inside = points[np.all(points < reference, axis=1)]
    if len(inside) == 0:
        return 0.0
    return _hypervolume_recursive(inside, reference)


def _hypervolume_recursive(points: np.ndarray, reference: np.ndarray) -> float:
    kept = points[np.ones(len(points), dtype=bool)]
    mask = []
    for index, row in enumerate(points):
        others = np.delete(points, index, axis=0)
        dominated = len(others) > 0 and np.any(np.all(others <= row + 1e-8, axis=1) & np.any(others < row - 1e-8, axis=1))
        mask.append(not dominated)
    kept = points[np.asarray(mask, dtype=bool)]
    if len(kept) == 0:
        return 0.0
    if kept.shape[1] == 1:
        return float(reference[0] - np.min(kept[:, 0]))
    kept = kept[np.argsort(kept[:, -1], kind="mergesort")]
    total = 0.0
    previous = float(reference[-1])
    for index in range(len(kept) - 1, -1, -1):
        height = float(kept[index, -1])
        if height >= previous - 1e-12:
            continue
        total += (previous - height) * _hypervolume_recursive(kept[: index + 1, :-1], reference[:-1])
        previous = height
    return total


def _dominates_row(left: np.ndarray, right: np.ndarray) -> bool:
    return bool(np.all(left <= right + 1e-8) and np.any(left < right - 1e-8))


def _pareto_rows(rows: list[np.ndarray]) -> list[np.ndarray]:
    kept: list[np.ndarray] = []
    for row in rows:
        if any(_dominates_row(old, row) for old in rows if old is not row):
            continue
        if any(np.allclose(old, row, rtol=0.0, atol=1e-6) for old in kept):
            continue
        kept.append(row)
    return kept


@dataclass(frozen=True)
class GuidedSearchResult:
    normalization: dict[str, Any]
    solutions: list[dict[str, Any]]
    objective_names: tuple[str, ...] = ()


class GuidedSearch(SiteSearch):
    """比较脚印平整度、需求距离和进站运输量。

    `search` 是决策按钮调用的入口。支配规则在 `tensor_nsga2.py`。
    硬约束读取建模模块的 `constraint_violation`。进站路径没有通路时，该个体不可行。
    进化前用可微距离场做短程引导。支配比较仍用精确查表。
    """

    algorithm_name = "guided_search"

    def __init__(
        self,
        config: Any,
        origin: tuple[float, float] | None = None,
        pose_bounds: tuple[float, float, float, float] | None = None,
    ) -> None:
        self.config = config
        self.origin = None if origin is None else (float(origin[0]), float(origin[1]))
        self.pose_bounds = pose_bounds

    def search(
        self,
        problem: Any,
        modeling: Any,
        reporter: Callable[[float, str, str], None] | None = None,
        field: Any | None = None,
    ) -> GuidedSearchResult:
        import torch

        from modeling.pose import decode_raw_pose
        from modeling.tensor_evaluator import TensorSiteEvaluator
        from modeling.numpy_evaluator import NumpySiteEvaluator

        config = self.config
        if config.algorithm_name != self.algorithm_name:
            raise ValueError(f"algorithm_name must be {self.algorithm_name!r}, got {config.algorithm_name!r}")
        origin = self.origin
        backend = resolve_evolution_backend(str(config.evolution_backend), problem.device)
        execution = describe_evolution_runtime(str(config.evolution_backend), problem.dem_tensor.device)
        logging.getLogger("uvicorn.error").info(
            "guided_search.runtime execution=%s popsize=%s generations=%s",
            execution, config.popsize, config.generations,
        )

        def report(progress: float, stage: str, message: str) -> None:
            if reporter is not None:
                reporter(progress, stage, f"{execution}｜{message}")

        from modeling.haul_field import build_haul_field

        if field is None:
            report(0.35, "haul_field", "正在构建进站距离场（CPU）")
            field = build_haul_field(
                problem.dem,
                problem.obstacle_mask == 0,
                problem.road_segments,
                origin,
                diagonal=bool(config.diagonal_access),
                access_elevation_weight=float(config.access_elevation_weight),
            )
        # These fractions only drive UI progress, never search decisions.
        preparation = f"初始化与 {int(config.guide_steps)} 步 Adam 引导" if int(config.guide_steps) > 0 else "初始化种群"
        report(0.42, "initialization", f"距离场已就绪；正在{preparation}")
        from algorithms.guided_search.guide import guide_initial_population, initialization_bounds
        from algorithms.guided_search.initialization import resolve_initialization_method
        from modeling.context import building_hard_mask

        allowed = building_hard_mask(problem) == 0
        initialization = resolve_initialization_method(
            str(config.initialization), allowed, initialization_bounds(problem, modeling, self.pose_bounds),
            bool(getattr(problem, "initialization_feasible_zones", ()) or getattr(problem, "initialization_exclusion_zones", ())),
        )
        initialization_reason = "constrained_domain" if initialization != config.initialization else None
        report(0.42, "initialization", f"初始化方式 {initialization}；中心点限制在允许域内"
               + (f"（请求 {config.initialization}，约束域改用均匀采样）" if initialization_reason else ""))
        initial = guide_initial_population(problem, modeling, config, field, self.pose_bounds, allowed_mask=allowed)
        del allowed
        report(0.58, "search", "种群已就绪；正在准备演化")

        if backend == "tensor":
            evaluate = TensorSiteEvaluator(problem, modeling, field,
                include_demand=bool(config.include_demand),
                batch_size=int(config.evaluation_batch_size), pose_bounds=self.pose_bounds)
        else:
            evaluate = NumpySiteEvaluator(problem, modeling, field,
                include_demand=bool(config.include_demand), pose_bounds=self.pose_bounds)

        def on_generation(generation: int, total: int) -> None:
            report(0.58 + 0.27 * (generation + 1) / total, "search", f"已完成进化第 {generation + 1}/{total} 代")

        step_control = None
        if bool(config.adaptive_sigma) and int(config.anneal_last_generations) <= 0:
            step_control = FrontStep(
                float(config.refine_sigma),
                shrink=float(config.sigma_shrink),
                patience=int(config.sigma_patience),
                floor=float(config.sigma_floor),
            )
        final = run_evolution(
            evaluate,
            popsize=int(config.popsize),
            generations=int(config.generations),
            seed=int(config.seed),
            sigma=float(config.refine_sigma),
            initial=initial,
            backend=backend,
            device=problem.device,
            on_generation=on_generation,
            anneal_last=0 if step_control is not None else int(config.anneal_last_generations),
            anneal_sigma_end=float(config.anneal_sigma_end),
            step_control=step_control,
        )
        report(0.86, "report", "演化已结束；正在计算最终精确报告（含 CPU 计算）")
        raw = final
        with torch.no_grad():
            pose = decode_raw_pose(torch.as_tensor(raw, dtype=torch.float32, device=problem.device),
                                   problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m, self.pose_bounds)
        solutions = pose_records(problem, modeling, origin, pose.cpu().numpy().astype(np.float64), field=field, raw=raw)
        return GuidedSearchResult(
            normalization={
                "algorithm": self.algorithm_name,
                "uses_objective_weights": False,
                "popsize": int(config.popsize),
                "requested_evolution_backend": str(config.evolution_backend),
                "evolution_backend": backend,
                "device": str(problem.dem_tensor.device),
                "execution_description": execution,
                "backend_fallback_reason": "cpu_device" if backend != config.evolution_backend else None,
                "evaluation_batch_size": int(config.evaluation_batch_size),
                "requested_initialization": str(config.initialization),
                "initialization": initialization,
                "initialization_fallback_reason": initialization_reason,
                "generations": int(config.generations),
                "seed": int(config.seed),
            },
            solutions=solutions,
            objective_names=guided_objective_names(origin is not None, bool(config.include_demand)),
        )


def run_guided_search(
    problem: Any,
    modeling: Any,
    config: Any,
    origin: tuple[float, float] | None = None,
    reporter: Callable[[float, str, str], None] | None = None,
    field: Any | None = None,
    pose_bounds: tuple[float, float, float, float] | None = None,
) -> GuidedSearchResult:
    """Search one scene by constructing the guided-search subclass."""

    return GuidedSearch(config, origin, pose_bounds).search(problem, modeling, reporter, field=field)


def haul_objectives(
    dem: np.ndarray,
    buildable: np.ndarray,
    segments: np.ndarray,
    origin: tuple[float, float] | None,
    sites: np.ndarray,
    field: Any | None = None,
    diagonal: bool = False,
    access_elevation_weight: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """进站长度和进站累计高差。指定了原点时再加沿路长度。走不通记在第二项，不制造惩罚权重。"""

    from modeling.haul_field import build_haul_field, query_exact

    if field is None:
        field = build_haul_field(
            dem,
            buildable,
            segments,
            origin,
            diagonal=diagonal,
            access_elevation_weight=access_elevation_weight,
        )
    return query_exact(field, sites)


def pose_records(
    problem: Any,
    modeling: Any,
    origin: tuple[float, float] | None,
    pose: np.ndarray,
    field: Any | None = None,
    raw: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """方案表的一行行记录。pose 是解码后的 `[N, 3]` 局部米坐标；搜索外调整过的方案也走这里，口径和搜索一致。"""

    import torch

    from algorithms.cma_es.cma_es import evaluate_pose_batch
    from modeling.context import building_hard_mask
    from modeling.evaluator import compute_hard_constraints

    if len(pose) == 0:
        return []
    hard_mask = building_hard_mask(problem)
    poses, objective_parts, hard_parts = [], [], []
    for start in range(0, len(pose), REPORT_BATCH):
        part, part_objectives = evaluate_pose_batch(problem, modeling, pose[start:start + REPORT_BATCH])
        part_hard = compute_hard_constraints(
            problem.dem,
            hard_mask,
            torch.as_tensor(part, dtype=torch.float32, device=problem.device),
            modeling.rect_w_m,
            modeling.rect_h_m,
            problem.device,
        )
        poses.append(part)
        objective_parts.append(part_objectives)
        hard_parts.append({name: value.detach().cpu().numpy() for name, value in part_hard.items()})
    pose = np.concatenate(poses)
    objectives = {name: np.concatenate([part[name] for part in objective_parts]) for name in objective_parts[0]}
    hard = {name: np.concatenate([part[name] for part in hard_parts]) for name in hard_parts[0]}
    haul, blocked = haul_objectives(
        problem.dem,
        problem.obstacle_mask == 0,
        problem.road_segments,
        origin,
        pose[:, :2],
        field=field,
    )
    return [
        _solution_record(index, None if raw is None else raw[index], pose[index], objectives, hard, haul[index], bool(blocked[index]))
        for index in range(len(pose))
    ]


def _solution_record(
    index: int,
    raw_pose: np.ndarray | None,
    pose: np.ndarray,
    objectives: dict[str, np.ndarray],
    hard: dict[str, Any],
    haul: np.ndarray,
    haul_blocked: bool,
) -> dict[str, Any]:
    def item(name: str) -> float:
        return float(hard[name][index])

    return {
        "run_id": index,
        "weight_dem": "",
        "weight_road": "",
        "weight_demand": "",
        "raw_x": "" if raw_pose is None else float(raw_pose[0]),
        "raw_y": "" if raw_pose is None else float(raw_pose[1]),
        "raw_theta": "" if raw_pose is None else float(raw_pose[2]),
        "x": float(pose[0]),
        "y": float(pose[1]),
        "theta": float(pose[2]),
        "scalar": "",
        "dem_soft": float(objectives["dem_soft"][index]),
        "obstacle_soft": float(objectives["obstacle_soft"][index]),
        "road_distance": float(objectives["road_distance"][index]),
        "demand_distance": float(objectives["demand_distance"][index]),
        "road_haul_m": "" if len(haul) < 3 else float(haul[0]),
        "offroad_haul_m": float(haul[-2]),
        "haul_rise_m": float(haul[-1]),
        "dem_hard_var": item("dem_hard_var"),
        "dem_hard_range": item("dem_hard_range"),
        "obstacle_hard_count": item("obstacle_hard_count"),
        "obstacle_hard_ratio": item("obstacle_hard_ratio"),
        "is_feasible": bool(hard["is_feasible"][index]) and not haul_blocked,
    }
