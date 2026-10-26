"""Evaluation-budgeted NSGA-II on variable-length tower sequences."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
import time

import numpy as np

from algorithms.common.nsga2 import Individual, nondominated_sort, select_population, tournament
from algorithms.common.pareto import extract_feasible_pareto_front
from config.project_config import RoutingConfig
from modeling.routing.context import RoutingProblem
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import OBJECTIVE_NAMES, Route, RouteEvaluation
from .initialization import TowerRange, initialize_routes
from .operators import offspring


@dataclass
class RoutingResult:
    routes: list[Route]
    evaluations: list[RouteEvaluation]
    pareto_indices: list[int]
    evaluation_count: int
    lower: int
    initial_upper: int
    final_upper: int
    expansions: list[dict[str, int]]
    stop_reason: str
    execution: dict = field(default_factory=dict)


def routing_search(problem: RoutingProblem, config: RoutingConfig,
                   reporter: Callable[[float, str, str], None] | None = None) -> RoutingResult:
    if config.evaluation_backend == "tensor":
        from modeling.routing.tensor_evaluator import TensorRouteEvaluator
        evaluator = TensorRouteEvaluator(problem, config)
    elif config.evaluation_backend == "compiled_cpu":
        from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
        evaluator = CompiledRouteEvaluator(problem)
    else:
        evaluator = RouteEvaluator(problem)
    rng = np.random.default_rng(config.seed)
    records: list[tuple[Route, RouteEvaluation]] = []

    def report(stage: str, message: str):
        if reporter:
            reporter(len(records) / config.max_evaluations, stage, message)

    def evaluate_many(routes):
        routes = routes[:config.max_evaluations - len(records)]
        results = evaluator.evaluate_many(routes, details=False)
        records.extend(zip(routes, results))
        return results

    def evaluate(route: Route) -> RouteEvaluation | None:
        if len(records) >= config.max_evaluations:
            return None
        return evaluate_many([route])[0]

    report("initialization", "正在生成参考线路与初始塔数范围（CPU）")
    initial = initialize_routes(evaluator, config, rng, evaluate)
    bounds = TowerRange(initial.lower, initial.upper, initial.upper)
    population = [Individual(route.towers, value.objectives, value.violation)
                  for route, value in records if bounds.lower <= len(route.towers) <= bounds.upper]
    if not population:
        base = Route(np.linspace(problem.start, problem.end, bounds.lower + 2)[1:-1])
        checked = evaluate(base)
        if checked is not None:
            population = [Individual(base.towers, checked.objectives, checked.violation)]
    if population:
        population = select_population(population, config.popsize)
    expansions, generation = [], 0
    execution = {"evolution_backend": config.evolution_backend, "evaluation_backend": config.evaluation_backend,
                 "devices": config.devices, "dtype": "float64"}
    if config.evolution_backend == "tensor" and population:
        from .tensor_search import evolve
        expansions, execution["timings"] = evolve(evaluator, config, bounds, records, evaluate_many, report)
    while config.evolution_backend == "numpy" and len(records) < config.max_evaluations and population:
        generation += 1
        expanded = bounds.expand(generation, config)
        if expanded:
            expansions.append({"generation": generation, "upper": bounds.upper, "evaluations": len(records)})
        nondominated_sort(population)
        children = []
        for index in range(config.popsize):
            first, second = tournament(rng, population), tournament(rng, population)
            # Boundary probes run even after finding a feasible low-tower solution.
            target = bounds.upper if expanded and index == 0 else None
            child = offspring(Route(first.genes), Route(second.genes), evaluator, config, rng,
                              bounds.lower, bounds.upper, target_count=target)
            checked = evaluate(child)
            if checked is None:
                break
            children.append(Individual(child.towers, checked.objectives, checked.violation))
        population = select_population(population + children, config.popsize)
        report("evolution", f"第 {generation} 代，已评价 {len(records)}/{config.max_evaluations}，塔数范围 {bounds.lower}–{bounds.upper}（CPU）")
    unique: dict[bytes, tuple[Route, RouteEvaluation]] = {}
    for route, value in records:
        unique.setdefault(route.towers.tobytes(), (route, value))
    routes = [item[0] for item in unique.values()]
    evaluations = [item[1] for item in unique.values()]
    feasible_indices = [i for i, item in enumerate(evaluations) if item.is_feasible]
    report("validation", "正在用 CPU 精确评价器逐条复核可行线路")
    started = time.perf_counter()
    reference = RouteEvaluator(problem)
    for index in feasible_indices:
        checked = reference.evaluate(routes[index])
        if not checked.is_feasible or not np.allclose(checked.objectives, evaluations[index].objectives, rtol=1e-10, atol=1e-8):
            raise RuntimeError("final routing validation disagrees with search evaluation")
        evaluations[index] = checked.compact()
    execution["validation_s"] = time.perf_counter() - started
    started = time.perf_counter()
    front_records = [{"index": i, "is_feasible": value.is_feasible, **dict(zip(OBJECTIVE_NAMES, value.objectives))}
                     for i, value in enumerate(evaluations)]
    pareto = [int(item["index"]) for item in extract_feasible_pareto_front(front_records, OBJECTIVE_NAMES)]
    execution["archive_s"] = time.perf_counter() - started
    execution["boundary_rechecks"] = getattr(evaluator, "boundary_rechecks", 0)
    if any(name.startswith("cuda:") for name in config.devices):
        import torch
        execution["gpu_memory"] = {name: {"peak_allocated_mib": torch.cuda.max_memory_allocated(name) / 1024**2,
            "peak_reserved_mib": torch.cuda.max_memory_reserved(name) / 1024**2} for name in config.devices}
    return RoutingResult(routes, evaluations, pareto, len(records), bounds.lower, bounds.initial_upper,
                         bounds.upper, expansions, "evaluation_budget", execution)
