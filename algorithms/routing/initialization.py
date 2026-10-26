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

Evaluate = Callable[[Route], RouteEvaluation | None]


def minimum_towers(problem: RoutingProblem) -> int:
    ratio = np.linalg.norm(problem.end - problem.start) / (problem.constraints.max_span_m + DISTANCE_TOL_M)
    return max(0, math.ceil(np.nextafter(ratio, -math.inf)) - 1)


def distribute_towers(path: np.ndarray, max_span_m: float) -> Route:
    points = [path[0]]
    for start, end in zip(path[:-1], path[1:]):
        ratio = np.linalg.norm(end - start) / (max_span_m + DISTANCE_TOL_M)
        steps = max(1, math.ceil(np.nextafter(ratio, -math.inf)))
        points.extend(start + (end - start) * index / steps for index in range(1, steps + 1))
    return Route(np.asarray(points[1:-1]).reshape(-1, 2))


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


@dataclass
class InitialRoutes:
    routes: list[Route]
    lower: int
    upper: int
    valid_references: int


@dataclass
class TowerRange:
    lower: int
    initial_upper: int
    upper: int

    def expand(self, generation: int, config: RoutingConfig) -> bool:
        if generation < 1 or generation % config.expansion_interval:
            return False
        self.upper += config.expansion_step
        return True


def initialize_routes(evaluator: RouteEvaluator, config: RoutingConfig, rng: np.random.Generator, evaluate: Evaluate) -> InitialRoutes:
    routes, feasible_counts = [], []
    for path in reference_paths(evaluator.problem, config):
        route = repair_towers(distribute_towers(path, evaluator.problem.constraints.max_span_m), evaluator, config, rng)
        route = repair_reference_spans(route, evaluator, config, rng)
        result = evaluate(route)
        if result is None:
            break
        if result.is_feasible:
            route, result = prune_reference(route, result, evaluate, evaluator.problem)
            feasible_counts.append(len(route.towers))
        routes.append(route)
    lower = minimum_towers(evaluator.problem)
    return InitialRoutes(routes, lower, max(feasible_counts, default=lower), len(feasible_counts))
