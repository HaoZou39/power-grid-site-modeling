"""A reference tower path whose edges may cross land that cannot host a tower."""

import heapq
import math
from typing import Callable

import numpy as np
from shapely.geometry import LineString

from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.geometry import DISTANCE_TOL_M
from modeling.routing.types import Route


def tower_navigation_route(evaluator: RouteEvaluator, step_m: float,
                           *, checkpoint: Callable[[], None] | None = None) -> Route | None:
    problem = evaluator.problem
    radius = problem.constraints.tower_radius_m
    limit = problem.constraints.max_span_m + DISTANCE_TOL_M
    step = max(float(step_m), 2 * radius)
    size = np.floor((np.array([problem.frame.width, problem.frame.height]) - 2 * radius) / step).astype(int) + 1

    def point(node):
        return np.array(node) * step + radius

    def clear(left, right):
        return not problem.no_cross_zones or not any(
            LineString([left, right]).intersects(zone) for zone in problem.no_cross_zones)

    if checkpoint:
        checkpoint()
    if np.linalg.norm(problem.end - problem.start) <= limit and clear(problem.start, problem.end):
        return Route(np.empty((0, 2)))
    if np.any(size < 1):
        return None
    reach = int(limit // step)
    reach_x, reach_y = min(reach, int(size[0]) - 1), min(reach, int(size[1]) - 1)
    offsets = [(x, y, math.hypot(x, y) * step)
               for x in range(-reach_x, reach_x + 1) for y in range(-reach_y, reach_y + 1)
               if 0 < math.hypot(x, y) * step <= limit]
    allowed = {}

    def tower_allowed(node):
        if not (0 <= node[0] < size[0] and 0 <= node[1] < size[1]):
            return False
        if node not in allowed:
            allowed[node] = evaluator.tower_allowed(point(node))
        return allowed[node]

    costs, previous, queue = {}, {}, []
    base = np.floor((problem.start - radius) / step).astype(int)
    # Endpoints connect to all nearby legal nodes, even when their own land is blocked.
    for x in range(max(0, base[0] - reach - 1), min(size[0], base[0] + reach + 2)):
        for y in range(max(0, base[1] - reach - 1), min(size[1], base[1] + reach + 2)):
            node = (x, y)
            position = point(node)
            distance = float(np.linalg.norm(position - problem.start))
            if 0 < distance <= limit and tower_allowed(node) and clear(problem.start, position):
                costs[node], previous[node] = distance, None
                heapq.heappush(queue, (distance + float(np.linalg.norm(position - problem.end)), distance, node))
    closed = set()
    while queue:
        _, cost, node = heapq.heappop(queue)
        if node in closed:
            continue
        position = point(node)
        if np.linalg.norm(position - problem.end) <= limit and clear(position, problem.end):
            chain = [node]
            while previous[chain[-1]] is not None:
                chain.append(previous[chain[-1]])
            towers = np.array([point(item) for item in reversed(chain)])
            if np.array_equal(towers[-1], problem.end):
                towers = towers[:-1]
            return Route(towers)
        closed.add(node)
        if checkpoint and len(closed) % 256 == 0:
            checkpoint()
        for dx, dy, distance in offsets:
            target, candidate_cost = (node[0] + dx, node[1] + dy), cost + distance
            if target in closed or candidate_cost >= costs.get(target, math.inf) or not tower_allowed(target):
                continue
            target_point = point(target)
            if not clear(position, target_point):
                continue
            costs[target], previous[target] = candidate_cost, node
            heapq.heappush(queue, (candidate_cost + float(np.linalg.norm(target_point - problem.end)), candidate_cost, target))
    return None
