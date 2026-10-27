"""Budgeted reference simplification, separate from seed generation."""

from typing import Callable
import numpy as np
from modeling.routing.context import RoutingProblem
from modeling.routing.geometry import DISTANCE_TOL_M
from modeling.routing.types import Route, RouteEvaluation

Evaluate = Callable[[Route], RouteEvaluation | None]

def prune_reference(route: Route, result: RouteEvaluation, evaluate: Evaluate, problem: RoutingProblem) -> tuple[Route, RouteEvaluation]:
    index = 0
    while index < len(route.towers):
        points = route.points(problem.start, problem.end)
        if np.linalg.norm(points[index + 2] - points[index]) > problem.constraints.max_span_m + DISTANCE_TOL_M:
            index += 1
            continue
        shorter = Route(np.delete(route.towers, index, axis=0))
        checked = evaluate(shorter)
        if checked is None:
            break
        if checked.is_feasible and np.all(checked.objectives[1:] <= result.objectives[1:] + 1e-10):
            route, result = shorter, checked
        else:
            index += 1
    return route, result
