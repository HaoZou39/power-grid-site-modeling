"""Reference paths and tight initial tower ranges, without imposing a no-return rule."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Callable

import numpy as np
from shapely.geometry import LineString

from config.project_config import RoutingConfig
from modeling.routing.context import RoutingProblem
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.geometry import DISTANCE_TOL_M
from modeling.routing.types import Route, RouteEvaluation
from .navigation import tower_navigation_route
from .repair import repair_reference_spans, repair_towers
from .postprocess import prune_reference
from .ranges import TowerRange, minimum_towers

Evaluate = Callable[[Route], RouteEvaluation | None]


def distribute_towers(path: np.ndarray, max_span_m: float) -> Route:
    points = [path[0]]
    for start, end in zip(path[:-1], path[1:]):
        ratio = np.linalg.norm(end - start) / (max_span_m + DISTANCE_TOL_M)
        steps = max(1, math.ceil(np.nextafter(ratio, -math.inf)))
        points.extend(start + (end - start) * index / steps for index in range(1, steps + 1))
    return Route(np.asarray(points[1:-1]).reshape(-1, 2))


def navigation_path(problem: RoutingProblem, step: int) -> np.ndarray | None:
    if not problem.no_cross_zones:
        return None
    width, height = math.ceil(problem.frame.width / step), math.ceil(problem.frame.height / step)

    def point(node):
        return np.minimum(np.array(node, dtype=float) * step, [problem.frame.width, problem.frame.height])

    def clear(left, right):
        return not any(LineString([left, right]).intersects(zone) for zone in problem.no_cross_zones)

    start = tuple(np.rint(problem.start / step).astype(int))
    end = tuple(np.rint(problem.end / step).astype(int))
    if not clear(problem.start, point(start)) or not clear(point(end), problem.end):
        return None
    costs, previous = {start: 0.0}, {}
    queue = [(float(np.linalg.norm(point(start) - problem.end)), start)]
    closed = set()
    while queue:
        _, node = heapq.heappop(queue)
        if node in closed:
            continue
        if node == end:
            chain = [node]
            while chain[-1] != start:
                chain.append(previous[chain[-1]])
            path = np.vstack([problem.start, [point(item) for item in reversed(chain)], problem.end])
            return path[np.r_[True, np.linalg.norm(np.diff(path, axis=0), axis=1) > 0]]
        closed.add(node)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                target = (node[0] + dx, node[1] + dy)
                if (dx == dy == 0) or not (0 <= target[0] <= width and 0 <= target[1] <= height):
                    continue
                if not clear(point(node), point(target)):
                    continue
                cost = costs[node] + float(np.linalg.norm(point(target) - point(node)))
                if cost < costs.get(target, math.inf):
                    costs[target], previous[target] = cost, node
                    heapq.heappush(queue, (cost + float(np.linalg.norm(point(target) - problem.end)), target))
    return None


def reference_paths(problem: RoutingProblem, config: RoutingConfig):
    yield np.vstack([problem.start, problem.end])
    delta = problem.end - problem.start
    distance = float(np.linalg.norm(delta))
    normal = np.array([-delta[1], delta[0]]) / distance
    middle = (problem.start + problem.end) / 2
    lower, upper = -math.inf, math.inf
    radius = problem.constraints.tower_radius_m
    for axis, size in enumerate([problem.frame.width, problem.frame.height]):
        if normal[axis] != 0:
            limits = sorted([(radius - middle[axis]) / normal[axis], (size - radius - middle[axis]) / normal[axis]])
            lower, upper = max(lower, limits[0]), min(upper, limits[1])
    if lower <= upper and problem.constraints.max_turn_deg > 0:
        for offset in np.linspace(lower, upper, config.reference_count):
            control = middle + normal * offset
            spans = math.ceil(2 * max(np.linalg.norm(control - problem.start), np.linalg.norm(problem.end - control)) / problem.constraints.max_span_m)
            bends = math.ceil(4 * abs(offset) / (distance * math.radians(problem.constraints.max_turn_deg)))
            t = np.linspace(0, 1, max(2, spans, bends) + 1)[:, None]
            yield (1 - t) ** 2 * problem.start + 2 * (1 - t) * t * control + t ** 2 * problem.end
    path = navigation_path(problem, config.navigation_step_m)
    if path is not None:
        yield path


@dataclass
class InitialRoutes:
    routes: list[Route]
    lower: int
    upper: int
    valid_references: int


def initialize_routes(evaluator: RouteEvaluator, config: RoutingConfig, rng: np.random.Generator, evaluate: Evaluate,
                      *, checkpoint: Callable[[], None] | None = None) -> InitialRoutes:
    routes, feasible_counts = [], []

    def candidates():
        for path in reference_paths(evaluator.problem, config):
            route = repair_towers(distribute_towers(path, evaluator.problem.constraints.max_span_m), evaluator, config, rng)
            yield repair_reference_spans(route, evaluator, config, rng)
        if not feasible_counts:
            route = tower_navigation_route(evaluator, config.navigation_step_m, checkpoint=checkpoint)
            if route is not None:
                yield route

    for route in candidates():
        result = evaluate(route)
        if result is None:
            break
        if result.is_feasible:
            route, result = prune_reference(route, result, evaluate, evaluator.problem)
            feasible_counts.append(len(route.towers))
        routes.append(route)
    lower = minimum_towers(evaluator.problem)
    # Failed references still carry useful geometry for constraint-first evolution.
    counts = feasible_counts or [len(route.towers) for route in routes]
    return InitialRoutes(routes, lower, max(counts, default=lower), len(feasible_counts))
