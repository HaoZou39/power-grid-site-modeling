"""Evaluation-budgeted NSGA-II on variable-length tower sequences."""

from __future__ import annotations

from typing import Callable
import time

import numpy as np

from algorithms.common.nsga2 import Individual, nondominated_sort, select_population, tournament
from algorithms.common.pareto import extract_feasible_pareto_front
from config.project_config import RoutingConfig
from modeling.routing.context import RoutingProblem
from modeling.routing.evaluator import RouteEvaluator, tower_cache_budget
from modeling.routing.types import OBJECTIVE_NAMES, Route, RouteEvaluation
from .initialization import TowerRange, initialize_routes
from .operators import offspring
from .evaluation_budget import EvaluationBudget
from .types import RoutingResult


def routing_search(problem: RoutingProblem, config: RoutingConfig,
                   reporter: Callable[[float, str, str], None] | None = None) -> RoutingResult:
    from modeling.routing.evaluation_session import evaluation_session
    search_started = time.perf_counter()
    with evaluation_session(problem, config) as evaluator:
        return _routing_search(problem, config, reporter, evaluator, search_started)


def _routing_search(problem, config, reporter, evaluator, search_started):
    rng = np.random.default_rng(config.seed)
    budget = EvaluationBudget(evaluator, config.max_evaluations, search_started)
    records, recorded_times = budget.records, budget.times
    mode = config.pilot.initialization_mode
    pilot_enabled = config.search_strategy == "pilot_reference" and (bool(config.pilot.enabled_mechanisms) or mode != "legacy")
    initialization = budget.window("initialization", config.pilot.initialization_budget_factor * config.popsize
                                   if pilot_enabled else config.max_evaluations)
    offspring_budget = budget.window("offspring", config.max_evaluations)
    stage_times = {"evaluator_setup_s": time.perf_counter() - search_started, "evaluation_s": 0.,
                   "initialization_s": 0., "ranking_s": 0., "variation_and_repair_s": 0.}

    def report(stage: str, message: str):
        if reporter:
            reporter(len(records) / config.max_evaluations, stage, message)

    def evaluate_many(routes):
        return offspring_budget.evaluate_many(routes)

    def evaluate(route: Route) -> RouteEvaluation | None:
        return initialization.evaluate(route)

    report("initialization", "正在生成参考线路与初始塔数范围（CPU）")
    started = time.perf_counter()
    initial = initialize_routes(evaluator, config, rng, evaluate,
        checkpoint=lambda: report("initialization", "正在搜索满足塔基与档距的绕行参考线（CPU）"))
    reference_routes, reference_upper = initial.routes.copy(), initial.upper
    pilot_initialization = {} if mode != "legacy" else None
    if "rrt" in config.pilot.enabled_mechanisms:
        from .pilot_reference.adapter import PilotAdapter
        from .pilot_reference.rrt import append_rrt_seeds
        seed_window = initialization
        if mode != "legacy":
            reserve = max(0, config.popsize - len(reference_routes)) if mode in {"balanced", "bounded"} else 0
            seed_window = budget.window("initialization", max(0, initialization.limit - len(records) - reserve))
        pilot_initialization = append_rrt_seeds(initial, PilotAdapter(evaluator, config.seed), config, seed_window,
            checkpoint=lambda: report("initialization", "正在生成 RRT 绕行种子（CPU）"))
    bounds = TowerRange(initial.lower, initial.upper, initial.upper)
    if mode != "legacy":
        from .pilot_reference.initialization import seed_population
        initialization = budget.window("initialization", max(0, initialization.limit - len(records)))
        if mode == "bounded":
            bounds.probe_upper = reference_upper
        population, stats = seed_population(reference_routes, initial.routes[len(reference_routes):],
                                            bounds, evaluator, config, initialization)
        pilot_initialization.update(stats, reference_upper=reference_upper)
    else:
        population = [Individual(route.towers, value.objectives, value.violation)
                      for route, value in records if bounds.lower <= len(route.towers) <= bounds.upper]
    if not population:
        base = Route(np.linspace(problem.start, problem.end, bounds.lower + 2)[1:-1])
        checked = evaluate(base)
        if checked is not None:
            population = [Individual(base.towers, checked.objectives, checked.violation)]
    if population:
        population = select_population(population, config.popsize)
    stage_times["initialization_s"] = time.perf_counter() - started
    initialization_evaluations = len(records)
    expansions, generation = [], 0
    active_devices = config.devices if config.evaluation_backend == "tensor" else (config.devices[:1] if config.evolution_backend == "tensor" else ["cpu"])
    execution = {"search_strategy": config.search_strategy, "enabled_mechanisms": list(config.pilot.enabled_mechanisms),
                 "evolution_backend": config.evolution_backend, "evaluation_backend": config.evaluation_backend,
                 "devices": active_devices, "requested_devices": config.devices, "dtype": "float64"}
    if config.search_strategy == "pilot_reference":
        from .pilot_reference.adapter import source_identity
        execution["pilot_source"] = source_identity()
        if pilot_initialization is not None:
            execution["pilot_initialization"] = pilot_initialization
    if config.evolution_backend == "tensor" and population:
        from .tensor_search import evolve
        expansions, tensor_times, generation = evolve(evaluator, config, bounds, records, evaluate_many, report)
        stage_times.update({name: value for name, value in tensor_times.items() if name != "evaluation_s"})
    while config.evolution_backend == "numpy" and len(records) < config.max_evaluations and population:
        generation += 1
        expanded = bounds.expand(generation, config)
        if expanded:
            expansions.append({"generation": generation, "upper": bounds.upper, "evaluations": len(records)})
            if bounds.probe_upper is not None:
                expansions[-1]["probe_upper"] = bounds.probe_upper
        started = time.perf_counter()
        nondominated_sort(population)
        stage_times["ranking_s"] += time.perf_counter() - started
        children = []
        for index in range(config.popsize):
            first, second = tournament(rng, population), tournament(rng, population)
            # Boundary probes run even after finding a feasible low-tower solution.
            target = (bounds.probe_upper if bounds.probe_upper is not None else bounds.upper) if expanded and index == 0 else None
            started = time.perf_counter()
            child = offspring(Route(first.genes), Route(second.genes), evaluator, config, rng,
                              bounds.lower, bounds.upper, target_count=target)
            stage_times["variation_and_repair_s"] += time.perf_counter() - started
            checked = offspring_budget.evaluate(child)
            if checked is None:
                break
            children.append(Individual(child.towers, checked.objectives, checked.violation))
        started = time.perf_counter()
        population = select_population(population + children, config.popsize)
        stage_times["ranking_s"] += time.perf_counter() - started
        report("evolution", f"第 {generation} 代，已评价 {len(records)}/{config.max_evaluations}，塔数范围 {bounds.lower}–{bounds.upper}（CPU）")
    stage_times["evaluation_s"] = budget.evaluation_s
    execution["phase_evaluations"] = budget.counts
    execution["timings"] = stage_times
    unique = {}
    for index, (route, value) in enumerate(records):
        unique.setdefault(route.towers.tobytes(), (route, value, index + 1, recorded_times[index]))
    routes = [item[0] for item in unique.values()]
    evaluations = [item[1] for item in unique.values()]
    feasible_indices = [i for i, item in enumerate(evaluations) if item.is_feasible]
    report("validation", "正在用 CPU 精确评价器逐条复核可行线路")
    started = time.perf_counter()
    reference = RouteEvaluator(problem).cache_geometry_checks(tower_cache_budget(problem, config.context_cache_mib))
    for position, index in enumerate(feasible_indices):
        if reporter is not None and position % config.evaluation_batch_size == 0:
            report("validation", f"CPU复核可行线路 {position}/{len(feasible_indices)}")
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
    if any(name.startswith("cuda:") for name in active_devices):
        import torch
        execution["gpu_memory"] = {name: {"peak_allocated_mib": torch.cuda.max_memory_allocated(name) / 1024**2,
            "peak_reserved_mib": torch.cuda.max_memory_reserved(name) / 1024**2} for name in active_devices}
    return RoutingResult(routes, evaluations, pareto, len(records), bounds.lower, bounds.initial_upper,
                         bounds.upper, expansions, "evaluation_budget", generation, initialization_evaluations, execution,
                         np.array([item[2] for item in unique.values()]), np.array([item[3] for item in unique.values()]))
