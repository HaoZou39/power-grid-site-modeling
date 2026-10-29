"""Exact first-occurrence archive, CPU verification and Pareto extraction."""

import time
import numpy as np
from algorithms.common.pareto import extract_feasible_pareto_front
from modeling.routing.evaluator import RouteEvaluator, tower_cache_budget
from modeling.routing.types import OBJECTIVE_NAMES
from .types import RoutingResult


def _pareto_indices(evaluations):
    records = [{"index": i, "is_feasible": value.is_feasible, **dict(zip(OBJECTIVE_NAMES, value.objectives))}
               for i, value in enumerate(evaluations)]
    return [int(item["index"]) for item in extract_feasible_pareto_front(records, OBJECTIVE_NAMES)]


def merge_similar_front(routes, evaluations, pareto, distance_m):
    """Published front: most balanced first, drop routes whose every tower is within distance_m of a kept one."""
    if not pareto:
        return []
    values = np.array([evaluations[i].objectives for i in pareto], dtype=float)
    span = np.ptp(values, axis=0)
    score = ((values - values.min(axis=0)) / np.where(span > 0, span, 1.)).sum(axis=1)
    kept = []
    for position in np.argsort(score, kind="stable"):
        towers = routes[pareto[position]].towers
        if not any(len(routes[j].towers) == len(towers)
                   and np.all(np.linalg.norm(routes[j].towers - towers, axis=1) <= distance_m) for j in kept):
            kept.append(pareto[position])
    return sorted(kept)


def archive_result(problem, config, budget, bounds, expansions, generation,
                   initialization_evaluations, execution, report, reporter):
    records, recorded_times = budget.records, budget.times
    unique = {}
    for index, (route, value) in enumerate(records):
        unique.setdefault(route.towers.tobytes(), (route, value, index + 1, recorded_times[index]))
    routes = [item[0] for item in unique.values()]
    evaluations = [item[1] for item in unique.values()]
    # Search decisions stay on the search evaluator. Only the reported front is checked on CPU.
    pareto = _pareto_indices(evaluations)
    report("validation", "正在用 CPU 精确评价器复核最终帕累托线路")
    started = time.perf_counter()
    reference = RouteEvaluator(problem).cache_geometry_checks(tower_cache_budget(problem, config.context_cache_mib))
    seen = set()
    # 复核值替换后前沿只可能在容差内变动；新进入前沿的线路再补一轮复核。
    pending = list(pareto)
    while pending:
        for index in pending:
            seen.add(index)
            if reporter is not None and (len(seen) - 1) % config.evaluation_batch_size == 0:
                report("validation", f"CPU复核帕累托线路 {len(seen) - 1}/{len(pareto)}")
            checked = reference.evaluate(routes[index])
            if not checked.is_feasible or not np.allclose(checked.objectives, evaluations[index].objectives, rtol=1e-10, atol=1e-8):
                raise RuntimeError("final routing validation disagrees with search evaluation")
            evaluations[index] = checked.compact()
        pareto = _pareto_indices(evaluations)
        pending = [i for i in pareto if i not in seen]
    execution["validation_s"] = time.perf_counter() - started
    execution["validated_routes"] = len(seen)
    started = time.perf_counter()
    pareto = _pareto_indices(evaluations)
    published = merge_similar_front(routes, evaluations, pareto, config.front_merge_distance_m)
    execution["archive_s"] = time.perf_counter() - started
    return RoutingResult(routes, evaluations, pareto, len(records), bounds.lower, bounds.initial_upper,
                         bounds.upper, expansions, budget.stop_reason, generation, initialization_evaluations, execution,
                         np.array([item[2] for item in unique.values()]), np.array([item[3] for item in unique.values()]),
                         published)
