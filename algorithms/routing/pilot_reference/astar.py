"""Frozen A* heap/relaxation flow with explicit metric geometry callbacks."""

import heapq
import math

import numpy as np

from algorithms.common.nsga2 import Individual, select_population
from modeling.routing.geometry import sample_dem
from ..postprocess import prune_reference

DIRECTIONS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))


def astar_grid(shape, start, end, *, allowed, distance, edge_allowed=lambda a, b: True,
               neighbors=None, checkpoint=None, expanded=None):
    height, width = shape
    if not (0 <= start[0] < width and 0 <= start[1] < height and 0 <= end[0] < width and 0 <= end[1] < height):
        return None
    heap = [(distance(start, end), 0., *start)]
    previous, costs, visited = {}, {start: 0.}, set()
    while heap:
        _, current, x, y = heapq.heappop(heap)
        node = (x, y)
        if node in visited:
            continue
        visited.add(node)
        if checkpoint is not None and len(visited) % 64 == 0:
            checkpoint()
        if expanded is not None:
            expanded()
        if node == end:
            path = [node]
            while node in previous:
                node = previous[node]
                path.append(node)
            return path[::-1]
        candidates = neighbors(node) if neighbors else ((x + dx, y + dy) for dx, dy in DIRECTIONS)
        for target in candidates:
            nx, ny = target
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if target not in {start, end} and not allowed(target):
                continue
            if not edge_allowed(node, target):
                continue
            tentative = current + distance(node, target)
            if tentative + 1e-12 < costs.get(target, math.inf):
                costs[target], previous[target] = tentative, node
                heapq.heappush(heap, (tentative + distance(target, end), tentative, nx, ny))
    return None


def metric_astar(state, step):
    problem = state.problem
    if step in state.planner_paths:
        state.count("astar_cache_hits")
        path = state.planner_paths[step]
        return None if path is None else path.copy()
    width, height = math.ceil(problem.frame.width / step), math.ceil(problem.frame.height / step)
    start = (min(width - 1, int(problem.start[0] // step)), min(height - 1, int(problem.start[1] // step)))
    end = (min(width - 1, int(problem.end[0] // step)), min(height - 1, int(problem.end[1] // step)))
    state.count("astar_attempts")
    if start == end:
        return np.vstack([problem.start, problem.end]) if state.evaluator.span_allowed(problem.start, problem.end) else None
    points, valid = {}, {}

    def point(node):
        if node not in points:
            if node == start:
                xy = problem.start
            elif node == end:
                xy = problem.end
            else:
                origin = np.array(node) * step
                xy = (origin + np.minimum(origin + step, [problem.frame.width, problem.frame.height])) / 2
            points[node] = np.r_[xy, sample_dem(problem.dem, np.asarray(xy).reshape(1, 2))[0]]
        return points[node]

    def allowed(node):
        if node not in valid:
            valid[node] = state.adapter.tower_allowed(point(node)[:2])
        return valid[node]

    def distance(a, b):
        return float(np.linalg.norm(point(a) - point(b)))

    def neighbors(node):
        hops = min(max(width, height), math.ceil(problem.constraints.max_span_m / step) + 1)
        for dx, dy in DIRECTIONS:
            for hop in range(1, hops + 1):
                target = (node[0] + dx * hop, node[1] + dy * hop)
                if not (0 <= target[0] < width and 0 <= target[1] < height):
                    break
                yield target

    path = astar_grid((height, width), start, end, allowed=allowed, distance=distance,
        edge_allowed=lambda a, b: state.evaluator.span_allowed(point(a)[:2], point(b)[:2]),
        neighbors=neighbors, checkpoint=state.checkpoint, expanded=lambda: state.count("astar_expanded_nodes"))
    if path is None:
        state.planner_paths[step] = None
        state.count("astar_failures")
        return None
    state.count("astar_successes")
    result = np.array([point(node)[:2] for node in path])
    state.planner_paths[step] = result.copy()
    return result


def append_astar_seeds(initial, state):
    config, bounds = state.config, initial.bounds
    window = state.budget.window("initialization", max(0, config.pilot.initialization_budget_factor * config.popsize
                                                      - len(state.budget.records)))
    added = []
    seen = {route.towers.tobytes() for route, _ in initial.candidates}
    for multiplier in state.core.astar_scales:
        if not window.remaining:
            break
        state.checkpoint("正在生成多尺度 DEM 三维 A* 种子")
        path = metric_astar(state, config.navigation_step_m * multiplier)
        if path is None:
            continue
        candidate = state.score(state.adapter.route(path), window)
        if candidate is None:
            break
        if not candidate.evaluation.is_feasible:
            state.count("astar_infeasible_seeds")
            continue
        def score(route):
            value = state.score(route, window)
            return None if value is None else value.evaluation
        route, _ = prune_reference(candidate.route, candidate.evaluation, score, state.problem)
        candidate = state.lookup(route)
        if candidate.key in seen:
            state.count("astar_duplicate_seeds")
            continue
        seen.add(candidate.key)
        state.count("astar_unique_feasible_seeds")
        added.append(candidate)
    if added:
        bounds.upper = bounds.initial_upper = max(bounds.upper, max(len(c.route.towers) for c in added))
        initial.population = select_population(initial.population + [Individual(c.route.towers, c.evaluation.objectives,
                                                c.evaluation.violation) for c in added], config.popsize)
        initial.candidates.extend((c.route, c.evaluation) for c in added)
