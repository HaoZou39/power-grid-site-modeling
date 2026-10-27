"""Exact first-occurrence archive, CPU verification and Pareto extraction."""

import time
import numpy as np
from algorithms.common.pareto import extract_feasible_pareto_front
from modeling.routing.evaluator import RouteEvaluator, tower_cache_budget
from modeling.routing.types import OBJECTIVE_NAMES
from .types import RoutingResult


def archive_result(problem, config, budget, bounds, expansions, generation,
                   initialization_evaluations, execution, report, reporter):
    records, recorded_times = budget.records, budget.times
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
    return RoutingResult(routes, evaluations, pareto, len(records), bounds.lower, bounds.initial_upper,
                         bounds.upper, expansions, budget.stop_reason, generation, initialization_evaluations, execution,
                         np.array([item[2] for item in unique.values()]), np.array([item[3] for item in unique.values()]))
