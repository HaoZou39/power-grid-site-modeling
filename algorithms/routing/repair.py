"""Tower occupancy and span repairs shared by initialization and evolution."""

import numpy as np
from config.project_config import RoutingConfig
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.geometry import DISTANCE_TOL_M
from modeling.routing.types import Route

def repair_towers(route: Route, evaluator: RouteEvaluator, config: RoutingConfig, rng: np.random.Generator) -> Route:
    problem, radius = evaluator.problem, evaluator.problem.constraints.tower_radius_m
    upper = np.array([problem.frame.width - radius, problem.frame.height - radius])
    if np.any(upper < radius):
        return route
    towers = route.towers.copy()
    for index, point in enumerate(towers):
        if evaluator.tower_allowed(point):
            continue
        for _ in range(config.repair_attempts):
            candidate = np.clip(point + rng.normal(0, config.mutation_scale * problem.constraints.max_span_m, 2), radius, upper)
            if evaluator.tower_allowed(candidate):
                towers[index] = candidate
                break
    return Route(towers)

def repair_reference_spans(route: Route, evaluator: RouteEvaluator, config: RoutingConfig, rng: np.random.Generator) -> Route:
    for _ in range(config.repair_attempts):
        points = route.points(evaluator.problem.start, evaluator.problem.end)
        lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
        index = int(np.argmax(lengths))
        if lengths[index] <= evaluator.problem.constraints.max_span_m + DISTANCE_TOL_M:
            break
        towers = np.insert(route.towers, index, (points[index] + points[index + 1]) / 2, axis=0)
        route = repair_towers(Route(towers), evaluator, config, rng)
    return route
