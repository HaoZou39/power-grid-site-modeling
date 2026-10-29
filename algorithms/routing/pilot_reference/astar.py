"""Frozen A* heap/relaxation flow with explicit metric geometry callbacks."""

import heapq
import math
from functools import lru_cache

import numpy as np
from numba import njit

from algorithms.common.nsga2 import Individual, select_population
from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
from modeling.routing.compiled_geometry import _placeable
from modeling.routing.geometry import DISTANCE_TOL_M, sample_dem
from ..postprocess import prune_reference

DIRECTIONS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
_DIRECTIONS = np.array(DIRECTIONS, dtype=np.int64)


# np.linalg.norm 走 OpenBLAS ddot，按 fma(z, z, fma(y, y, x * x)) 舍入；contract 让 LLVM 生成同一条 FMA 链。
@njit(cache=True, nogil=True, fastmath={"contract"})
def _norm3(dx, dy, dz):
    return math.sqrt(dx * dx + dy * dy + dz * dz)


@njit(cache=True, nogil=True, fastmath={"contract"})
def _norm2(dx, dy):
    return math.sqrt(dx * dx + dy * dy)


# RouteEvaluator.span_allowed 在 Python 里逐项相乘，没有 FMA。
@njit(cache=True, nogil=True)
def _length2(dx, dy):
    return dx * dx + dy * dy


@njit(cache=True, nogil=True)
def _astar_kernel(px, py, pz, start, end, hops, corridor, max_span, frame_w, frame_h,
                  blocked_distance, missing_distance, dem, blocked, radius):
    """Same heap order (f, g, x, y), neighbour order and relaxation as astar_grid with metric_astar callbacks."""
    height, width = px.shape
    allowed = np.full((height, width), -1, np.int8)
    costs = np.full((height, width), np.inf)
    visited = np.zeros((height, width), np.bool_)
    prev_x = np.full((height, width), -1, np.int64)
    prev_y = np.full((height, width), -1, np.int64)
    sx, sy, ex, ey = start[0], start[1], end[0], end[1]
    costs[sy, sx] = 0.
    heap = [(_norm3(px[sy, sx] - px[ey, ex], py[sy, sx] - py[ey, ex], pz[sy, sx] - pz[ey, ex]), 0., sx, sy)]
    expanded = checks = 0
    while len(heap):
        _, current, x, y = heapq.heappop(heap)
        if visited[y, x]:
            continue
        visited[y, x] = True
        expanded += 1
        if x == ex and y == ey:
            path = [(x, y)]
            while prev_x[y, x] >= 0:
                x, y = prev_x[y, x], prev_y[y, x]
                path.append((x, y))
            return path[::-1], expanded, checks
        for d in range(8):
            for hop in range(1, hops + 1):
                nx, ny = x + _DIRECTIONS[d, 0] * hop, y + _DIRECTIONS[d, 1] * hop
                if not (0 <= nx < width and 0 <= ny < height):
                    break
                fixed = (nx == sx and ny == sy) or (nx == ex and ny == ey)
                if not fixed:
                    if allowed[ny, nx] < 0:
                        checks += 1
                        allowed[ny, nx] = _placeable(blocked_distance, missing_distance, dem, blocked,
                                                     px[ny, nx], py[ny, nx], radius)
                    if allowed[ny, nx] == 0:
                        continue
                ax, ay, bx, by = px[y, x], py[y, x], px[ny, nx], py[ny, nx]
                if corridor:
                    length = _norm2(bx - ax, by - ay)
                    if not (0 < length <= max_span):
                        continue
                else:
                    inside = (ax >= 0 and ay >= 0 and bx >= 0 and by >= 0
                              and ax <= frame_w and ay <= frame_h and bx <= frame_w and by <= frame_h)
                    length2 = _length2(bx - ax, by - ay)
                    if not (inside and 0 < length2 <= max_span * max_span):
                        continue
                tentative = current + _norm3(ax - bx, ay - by, pz[y, x] - pz[ny, nx])
                if tentative + 1e-12 < costs[ny, nx]:
                    costs[ny, nx], prev_x[ny, nx], prev_y[ny, nx] = tentative, x, y
                    heapq.heappush(heap, (tentative + _norm3(bx - px[ey, ex], by - py[ey, ex], pz[ny, nx] - pz[ey, ex]),
                                          tentative, nx, ny))
    return [(sx, sy)][:0], expanded, checks


def _node_points(problem, step, width, height, start, end):
    """Cell-centre [x, y, z] per coarse node, with the exact endpoints on their own nodes; arrays are [height, width]."""
    origin_x, origin_y = np.meshgrid(np.arange(width) * step, np.arange(height) * step)
    xy = np.stack([(origin_x + np.minimum(origin_x + step, problem.frame.width)) / 2,
                   (origin_y + np.minimum(origin_y + step, problem.frame.height)) / 2], -1)
    xy[start[1], start[0]], xy[end[1], end[0]] = problem.start, problem.end
    z = sample_dem(problem.dem, xy.reshape(-1, 2)).reshape(height, width)
    return np.ascontiguousarray(xy[..., 0]), np.ascontiguousarray(xy[..., 1]), z


def _compiled_astar(state, step, width, height, start, end, hops, corridor):
    problem, evaluator = state.problem, state.evaluator
    px, py, pz = _node_points(problem, step, width, height, start, end)
    blocked_distance, missing_distance = evaluator._distance_fields()
    state.checkpoint()
    path, expanded, checks = _astar_kernel(
        px, py, pz, np.array(start, np.int64), np.array(end, np.int64), hops, corridor,
        problem.constraints.max_span_m + DISTANCE_TOL_M, float(problem.frame.width), float(problem.frame.height),
        blocked_distance, missing_distance, evaluator._dem, evaluator._blocked, float(problem.constraints.tower_radius_m))
    state.checkpoint()
    state.adapter.node_checks += checks
    state.count("astar_expanded_nodes", expanded)
    return None if not path else np.array([[px[y, x], py[y, x]] for x, y in path])


def astar_grid(shape, start, end, *, allowed, distance, edge_allowed=lambda a, b: True,
               neighbors=None, checkpoint=None, expanded=None):
    height, width = shape
    if not (0 <= start[0] < width and 0 <= start[1] < height and 0 <= end[0] < width and 0 <= end[1] < height):
        return None
    heap = [(distance(start, end), 0., *start)]
    previous, costs, visited = {}, {start: 0.}, set()
    fixed = {start, end}
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
            if target not in fixed and not allowed(target):
                continue
            if not edge_allowed(node, target):
                continue
            tentative = current + distance(node, target)
            if tentative + 1e-12 < costs.get(target, math.inf):
                costs[target], previous[target] = tentative, node
                heapq.heappush(heap, (tentative + distance(target, end), tentative, nx, ny))
    return None


def metric_astar(state, step, *, corridor=False):
    problem = state.problem
    cache_key = ("corridor", step) if corridor else step
    if cache_key in state.planner_paths:
        state.count("astar_cache_hits")
        path = state.planner_paths[cache_key]
        return None if path is None else path.copy()
    width, height = math.ceil(problem.frame.width / step), math.ceil(problem.frame.height / step)
    start = (min(width - 1, int(problem.start[0] // step)), min(height - 1, int(problem.start[1] // step)))
    end = (min(width - 1, int(problem.end[0] // step)), min(height - 1, int(problem.end[1] // step)))
    state.count("astar_attempts")
    if start == end:
        span = float(np.linalg.norm(problem.end - problem.start))
        connected = 0 < span <= problem.constraints.max_span_m + DISTANCE_TOL_M if corridor else state.evaluator.span_allowed(problem.start, problem.end)
        result = np.vstack([problem.start, problem.end]) if connected else None
        state.planner_paths[cache_key] = None if result is None else result.copy()
        state.count("astar_failures" if result is None else "astar_successes")
        return result
    hops = min(max(width, height), math.ceil(problem.constraints.max_span_m / step) + 1)
    # 人工多边形要用 Shapely 精确判断，留在下面的 Python 路径。
    if (type(state.evaluator) is CompiledRouteEvaluator and not problem.no_tower_zones
            and (corridor or not problem.no_cross_zones)):
        result = _compiled_astar(state, step, width, height, start, end, hops, corridor)
        state.planner_paths[cache_key] = None if result is None else result.copy()
        state.count("astar_failures" if result is None else "astar_successes")
        return result
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

    @lru_cache(maxsize=None)
    def distance(a, b):
        return float(np.linalg.norm(point(a) - point(b)))

    def neighbors(node):
        for dx, dy in DIRECTIONS:
            for hop in range(1, hops + 1):
                target = (node[0] + dx * hop, node[1] + dy * hop)
                if not (0 <= target[0] < width and 0 <= target[1] < height):
                    break
                yield target

    def edge_allowed(a, b):
        start_point, end_point = point(a)[:2], point(b)[:2]
        if corridor:
            return 0 < float(np.linalg.norm(end_point - start_point)) <= problem.constraints.max_span_m + DISTANCE_TOL_M
        return state.evaluator.span_allowed(start_point, end_point)

    path = astar_grid((height, width), start, end, allowed=allowed, distance=distance,
        edge_allowed=edge_allowed,
        neighbors=neighbors, checkpoint=state.checkpoint, expanded=lambda: state.count("astar_expanded_nodes"))
    if path is None:
        state.planner_paths[cache_key] = None
        state.count("astar_failures")
        return None
    state.count("astar_successes")
    result = np.array([point(node)[:2] for node in path])
    state.planner_paths[cache_key] = result.copy()
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
        path = metric_astar(state, config.navigation_step_m * multiplier, corridor=True)
        if path is None:
            continue
        candidate = state.score(state.adapter.route(path), window)
        if candidate is None:
            break
        if not candidate.evaluation.is_feasible:
            state.count("astar_infeasible_seeds")
            added.append(candidate)
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
    feasible = [c for c in added if c.evaluation.is_feasible]
    if feasible:
        bounds.upper = bounds.initial_upper = max(bounds.upper, max(len(c.route.towers) for c in feasible))
    if added:
        initial.population = select_population(initial.population + [Individual(c.route.towers, c.evaluation.objectives,
                                                c.evaluation.violation) for c in added], config.popsize)
        initial.candidates.extend((c.route, c.evaluation) for c in added)
