"""决策界面使用的多目标搜索。

种群按支配关系进化，可行站址排在不可行站址前面。这里不使用目标权重。
决策搜索比较脚印平整度、需求点距离、沿路长度、进场长度和进场高差。到道路的直线距离仍会写入方案表，但不参加支配比较。
改种群大小、交叉或变异时改这个文件。目标公式仍在 `modeling/`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from algorithms.common.search import SiteSearch
from modeling.haul_field import haul_column_names

# 直线道路距离 road_distance 不在此列。CMA-ES 仍使用 algorithms.common.scalarization.OBJECTIVE_NAMES。
# 没指定进货原点时不比较沿路长度。进场列的顺序只写在 haul_column_names。
def nsga2_objective_names(include_road_haul: bool) -> tuple[str, ...]:
    return ("dem_soft", "demand_distance") + haul_column_names(include_road_haul)

EvaluateBatch = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]


@dataclass
class Individual:
    genes: np.ndarray
    objectives: np.ndarray
    violation: float
    rank: int = 0
    crowding: float = 0.0


def dominates(left: Individual, right: Individual) -> bool:
    """Return whether left is preferred to right under constrained dominance."""

    left_ok = left.violation <= 0.0
    right_ok = right.violation <= 0.0
    if left_ok and not right_ok:
        return True
    if right_ok and not left_ok:
        return False
    if not left_ok and not right_ok and left.violation != right.violation:
        return left.violation < right.violation
    not_worse = bool(np.all(left.objectives <= right.objectives))
    better = bool(np.any(left.objectives < right.objectives))
    return not_worse and better


def _assign_crowding(population: list[Individual], front: list[int]) -> None:
    for index in front:
        population[index].crowding = 0.0
    if len(front) <= 2:
        for index in front:
            population[index].crowding = float("inf")
        return
    width = population[front[0]].objectives.shape[0]
    for objective in range(width):
        ordered = sorted(front, key=lambda index: population[index].objectives[objective])
        population[ordered[0]].crowding = float("inf")
        population[ordered[-1]].crowding = float("inf")
        span = population[ordered[-1]].objectives[objective] - population[ordered[0]].objectives[objective]
        if span <= 0.0:
            continue
        for place in range(1, len(ordered) - 1):
            previous = population[ordered[place - 1]].objectives[objective]
            following = population[ordered[place + 1]].objectives[objective]
            population[ordered[place]].crowding += (following - previous) / span


def nondominated_sort(population: list[Individual]) -> list[list[int]]:
    """Assign rank and crowding, and return fronts from best to worst."""

    count = len(population)
    dominated_by = [0] * count
    dominates_these: list[list[int]] = [[] for _ in range(count)]
    for left in range(count):
        for right in range(left + 1, count):
            if dominates(population[left], population[right]):
                dominates_these[left].append(right)
                dominated_by[right] += 1
            elif dominates(population[right], population[left]):
                dominates_these[right].append(left)
                dominated_by[left] += 1
    fronts: list[list[int]] = []
    current = [index for index, degree in enumerate(dominated_by) if degree == 0]
    rank = 0
    while current:
        for index in current:
            population[index].rank = rank
        _assign_crowding(population, current)
        fronts.append(current)
        nxt: list[int] = []
        for index in current:
            for other in dominates_these[index]:
                dominated_by[other] -= 1
                if dominated_by[other] == 0:
                    nxt.append(other)
        current = nxt
        rank += 1
    return fronts


def _tournament(rng: np.random.Generator, population: list[Individual]) -> Individual:
    left = population[int(rng.integers(len(population)))]
    right = population[int(rng.integers(len(population)))]
    left_wins = left.rank < right.rank or (left.rank == right.rank and left.crowding > right.crowding)
    return left if left_wins else right


def _offspring(rng: np.random.Generator, population: list[Individual], sigma: float) -> np.ndarray:
    children = []
    for _ in range(len(population)):
        first = _tournament(rng, population)
        second = _tournament(rng, population)
        child = 0.5 * (first.genes + second.genes) if rng.random() < 0.9 else first.genes.copy()
        children.append(child + rng.normal(0.0, sigma, size=child.shape))
    return np.stack(children).astype(np.float64)


def _select(combined: list[Individual], popsize: int) -> list[Individual]:
    chosen: list[int] = []
    for front in nondominated_sort(combined):
        if len(chosen) + len(front) <= popsize:
            chosen.extend(front)
            continue
        ordered = sorted(front, key=lambda index: combined[index].crowding, reverse=True)
        chosen.extend(ordered[: popsize - len(chosen)])
        break
    return [combined[index] for index in chosen]


def _evaluate(evaluate: EvaluateBatch, genes: np.ndarray) -> list[Individual]:
    objectives, violation = evaluate(genes)
    if objectives.shape != (genes.shape[0], objectives.shape[1]) or violation.shape != (genes.shape[0],):
        raise ValueError("evaluate must return one objective row and one violation per candidate")
    if objectives.shape[1] < 1:
        raise ValueError("evaluate must return at least one objective")
    return [
        Individual(genes[index].copy(), objectives[index].astype(np.float64), float(violation[index]))
        for index in range(genes.shape[0])
    ]


def run_nsga2(
    evaluate: EvaluateBatch,
    *,
    popsize: int,
    generations: int,
    seed: int,
    sigma: float,
    n_var: int = 3,
    initial: np.ndarray | None = None,
    on_generation: Callable[[int, int], None] | None = None,
    anneal_last: int = 0,
    anneal_sigma_end: float | None = None,
    step_control: FrontStep | None = None,
) -> list[Individual]:
    """Evolve one population. ``evaluate`` returns objectives and constraint violation."""

    if popsize < 4 or generations < 1 or sigma <= 0 or n_var < 1:
        raise ValueError("popsize must be at least 4, generations at least 1, and sigma positive")
    rng = np.random.default_rng(seed)
    if initial is None:
        genes = rng.normal(0.0, sigma, size=(popsize, n_var))
    else:
        genes = np.asarray(initial, dtype=np.float64)
        if genes.shape != (popsize, n_var):
            raise ValueError(f"initial population must have shape [{popsize}, {n_var}]")
    population = _evaluate(evaluate, genes)
    nondominated_sort(population)
    for generation in range(generations):
        step_sigma = step_control.sigma if step_control is not None else generation_sigma(
            generation, generations, sigma, anneal_last, anneal_sigma_end
        )
        children = _evaluate(evaluate, _offspring(rng, population, step_sigma))
        population = _select(population + children, popsize)
        nondominated_sort(population)
        if step_control is not None:
            step_control.observe(np.stack([person.objectives for person in population]))
        if on_generation is not None:
            on_generation(generation, generations)
    return population


def generation_sigma(
    generation: int,
    generations: int,
    sigma: float,
    anneal_last: int,
    anneal_sigma_end: float | None,
) -> float:
    """最后若干代把变异步长线性收到终点。之前的代保持原来的步长。"""

    if anneal_last <= 0 or anneal_sigma_end is None or generation < generations - anneal_last:
        return float(sigma)
    slot = generation - (generations - anneal_last)
    span = max(anneal_last - 1, 1)
    return float(sigma + (float(anneal_sigma_end) - sigma) * (slot / span))


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
class NSGA2Result:
    normalization: dict[str, Any]
    solutions: list[dict[str, Any]]
    objective_names: tuple[str, ...] = ()


class Nsga2Search(SiteSearch):
    """比较脚印平整度、需求距离和进场运输量。

    `search` 是决策按钮调用的入口。支配规则在本文件的 `dominates`。
    硬约束读取建模模块的 `constraint_violation`。进场没有通路时，该个体不可行。
    进化前用可微距离场做短程引导。支配比较仍用精确查表。
    """

    algorithm_name = "nsga2"

    def __init__(self, config: Any, origin: tuple[float, float] | None = None) -> None:
        self.config = config
        self.origin = None if origin is None else (float(origin[0]), float(origin[1]))

    def search(self, problem: Any, modeling: Any, reporter: Callable[[float, str, str], None] | None = None) -> NSGA2Result:
        import torch

        from algorithms.cma_es.cma_es import evaluate_raw_pose_batch
        from modeling.evaluator import compute_hard_constraints

        config = self.config
        if config.algorithm_name != self.algorithm_name:
            raise ValueError(f"algorithm_name must be {self.algorithm_name!r}, got {config.algorithm_name!r}")
        origin = self.origin
        from modeling.haul_field import build_haul_field

        field = build_haul_field(problem.dem, problem.obstacle_mask == 0, problem.road_segments, origin)
        if reporter is not None:
            # 0.42 和下面的 0.58 只推动界面进度，不参与搜索。
            reporter(0.42, "search", "进场距离场已建好")
        from algorithms.nsga2.guided_search import guide_initial_population

        initial = guide_initial_population(problem, modeling, config, field)
        if reporter is not None and int(config.guide_steps) > 0:
            reporter(0.58, "search", "梯度引导已结束")

        def evaluate(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            decoded, objectives = evaluate_raw_pose_batch(problem, modeling, raw.astype(np.float32))
            pose = torch.as_tensor(decoded, dtype=torch.float32, device=problem.device)
            hard = compute_hard_constraints(
                problem.dem,
                problem.obstacle_mask,
                pose,
                modeling.rect_w_m,
                modeling.rect_h_m,
                problem.device,
            )
            names = nsga2_objective_names(origin is not None)
            stacked = np.stack([objectives[name] for name in names if name in objectives], axis=1)
            haul, blocked = haul_objectives(
                problem.dem,
                problem.obstacle_mask == 0,
                problem.road_segments,
                origin,
                decoded[:, :2],
                field=field,
            )
            violation = hard["constraint_violation"].detach().cpu().numpy().astype(np.float64) + blocked
            return np.concatenate([stacked, haul], axis=1), violation

        def on_generation(generation: int, total: int) -> None:
            if reporter is not None:
                reporter(0.58 + 0.27 * (generation + 1) / total, "search", f"正在进化第 {generation + 1} 代")

        step_control = None
        if bool(config.adaptive_sigma) and int(config.anneal_last_generations) <= 0:
            step_control = FrontStep(
                float(config.refine_sigma),
                shrink=float(config.sigma_shrink),
                patience=int(config.sigma_patience),
                floor=float(config.sigma_floor),
            )
        final = run_nsga2(
            evaluate,
            popsize=int(config.popsize),
            generations=int(config.generations),
            seed=int(config.seed),
            sigma=float(config.refine_sigma),
            initial=initial,
            on_generation=on_generation,
            anneal_last=0 if step_control is not None else int(config.anneal_last_generations),
            anneal_sigma_end=float(config.anneal_sigma_end),
            step_control=step_control,
        )
        genes = np.stack([person.genes for person in final]).astype(np.float64)
        if int(config.local_steps) > 0:
            from algorithms.nsga2.guided_search import local_polish

            genes = local_polish(genes, evaluate, problem, modeling, config, field)
        raw = genes.astype(np.float32)
        pose, objectives = evaluate_raw_pose_batch(problem, modeling, raw)
        pose_tensor = torch.as_tensor(pose, dtype=torch.float32, device=problem.device)
        hard = compute_hard_constraints(
            problem.dem,
            problem.obstacle_mask,
            pose_tensor,
            modeling.rect_w_m,
            modeling.rect_h_m,
            problem.device,
        )
        haul, blocked = haul_objectives(
            problem.dem,
            problem.obstacle_mask == 0,
            problem.road_segments,
            origin,
            pose[:, :2],
            field=field,
        )
        solutions = [
            _solution_record(index, raw[index], pose[index], objectives, hard, haul[index], bool(blocked[index]))
            for index in range(len(final))
        ]
        return NSGA2Result(
            normalization={
                "algorithm": self.algorithm_name,
                "uses_objective_weights": False,
                "popsize": int(config.popsize),
                "generations": int(config.generations),
                "seed": int(config.seed),
            },
            solutions=solutions,
            objective_names=nsga2_objective_names(origin is not None),
        )


def run_nsga2_search(
    problem: Any,
    modeling: Any,
    config: Any,
    origin: tuple[float, float] | None = None,
    reporter: Callable[[float, str, str], None] | None = None,
) -> NSGA2Result:
    """Search one scene by constructing the NSGA-II subclass."""

    return Nsga2Search(config, origin).search(problem, modeling, reporter)


def haul_objectives(
    dem: np.ndarray,
    buildable: np.ndarray,
    segments: np.ndarray,
    origin: tuple[float, float] | None,
    sites: np.ndarray,
    field: Any | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """进场长度和高差。指定了原点时再加沿路长度。走不通记在第二项，不制造惩罚权重。"""

    from modeling.haul_field import build_haul_field, query_exact

    if field is None:
        field = build_haul_field(dem, buildable, segments, origin)
    return query_exact(field, sites)


def _solution_record(
    index: int,
    raw_pose: np.ndarray,
    pose: np.ndarray,
    objectives: dict[str, np.ndarray],
    hard: dict[str, Any],
    haul: np.ndarray,
    haul_blocked: bool,
) -> dict[str, Any]:
    def item(name: str) -> float:
        return float(hard[name][index].detach().cpu().item())

    return {
        "run_id": index,
        "weight_dem": "",
        "weight_road": "",
        "weight_demand": "",
        "raw_x": float(raw_pose[0]),
        "raw_y": float(raw_pose[1]),
        "raw_theta": float(raw_pose[2]),
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
        "is_feasible": bool(hard["is_feasible"][index].detach().cpu().item()) and not haul_blocked,
    }
