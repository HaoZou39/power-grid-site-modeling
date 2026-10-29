"""PILOT's single-tree RRT flow, with continuous metric geometry callbacks.

Source: frozen path_planners.py::_rrt_path and _build_astar_rrt_population.
The coarse-cell rounding, legacy encoding and A* fallback are deliberately absent.
"""

import math

import numpy as np
from numba import njit

from modeling.routing.compiled_geometry import _placeable
from modeling.routing.geometry import DISTANCE_TOL_M
from ..initialization import prune_reference
from .astar import _fma, _length2, _norm2


def corridor_extension_allowed(evaluator, points, target, *, fixed_endpoint=False):
    """Initialization growth: a new tower must be placeable and the step stays within max span."""
    points = np.asarray(points, dtype=float)
    target = np.asarray(target, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 1 or target.shape != (2,):
        raise ValueError("path prefix and target must contain 2D coordinates")
    if not (0 < np.linalg.norm(target - points[-1]) <= evaluator.problem.constraints.max_span_m + DISTANCE_TOL_M):
        return False
    if fixed_endpoint:
        if not np.array_equal(target, evaluator.problem.end):
            raise ValueError("fixed extension must end at the configured connection point")
        return True
    return bool(evaluator.tower_allowed(target))


def _backtrack(nodes, parents, index):
    path = []
    while index >= 0:
        path.append(nodes[index])
        index = parents[index]
    return np.asarray(path[::-1], dtype=float)


def rrt_path(start, end, upper, *, max_iters, goal_bias, min_step, max_step,
             python_rng, numpy_rng, sample_free, extension_allowed, checkpoint=None, stats=None,
             extension_requires_prefix=True):
    # Keep the tree in contiguous storage.  The old list representation rebuilt
    # a NumPy array from every node on every iteration before the nearest-node
    # reduction, which copied the whole tree repeatedly.
    start, end, upper = (np.asarray(value, dtype=float) for value in (start, end, upper))
    nodes = np.empty((max_iters + 2, 2), dtype=float)
    parents = np.empty(max_iters + 2, dtype=np.int64)
    nodes[0] = start
    parents[0] = -1
    node_count = 1
    for iteration in range(max_iters):
        if checkpoint is not None and iteration % 64 == 0:
            checkpoint()
        if stats is not None:
            stats["rrt_iterations"] += 1
        target = end if python_rng.random() < goal_bias else sample_free()
        if target is None:
            continue
        target = np.asarray(target, dtype=float)
        nearest_idx = int(np.argmin(np.sum((nodes[:node_count] - target) ** 2, axis=1)))
        nearest = nodes[nearest_idx]
        direction = target - nearest
        distance = float(np.linalg.norm(direction))
        if distance <= 1e-8:
            continue
        extend = float(numpy_rng.uniform(min_step, max_step))
        new_pt = np.clip(nearest + direction / distance * min(extend, distance), 0, upper)
        if np.linalg.norm(new_pt - nearest) <= 1e-8:
            continue
        # Corridor growth only validates the last edge. Avoid rebuilding the
        # complete parent chain for every attempted node; the full chain is
        # needed only after a route reaches the fixed endpoint.
        prefix = (_backtrack(nodes[:node_count], parents[:node_count], nearest_idx)
                  if extension_requires_prefix else nodes[nearest_idx:nearest_idx + 1])
        if np.array_equal(new_pt, end):
            if extension_allowed(prefix, end, fixed_endpoint=True):
                return np.vstack([prefix, end])
            continue
        if not extension_allowed(prefix, new_pt):
            continue
        nodes[node_count] = new_pt
        parents[node_count] = nearest_idx
        new_idx = node_count
        node_count += 1
        if np.linalg.norm(new_pt - end) <= max_step and extension_allowed(
                np.vstack([prefix, new_pt]), end, fixed_endpoint=True):
            nodes[node_count] = end
            parents[node_count] = new_idx
            node_count += 1
            return _backtrack(nodes[:node_count], parents[:node_count], node_count - 1)
    return None


# random.Random 与 RandomState 都是 MT19937；state 为 624 个字加当前位置，两者的 [0, 1) 双精度取法相同。
@njit(cache=True, nogil=True)
def _mt_random(state):
    words = np.empty(2, np.int64)
    for k in range(2):
        if state[624] >= 624:
            for i in range(624):
                y = (state[i] & 0x80000000) | (state[(i + 1) % 624] & 0x7fffffff)
                state[i] = state[(i + 397) % 624] ^ (y >> 1) ^ (0x9908b0df if y & 1 else 0)
            state[624] = 0
        y = state[state[624]]
        state[624] += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9d2c5680
        y ^= (y << 15) & 0xefc60000
        words[k] = y ^ (y >> 18)
    return ((words[0] >> 5) * 67108864.0 + (words[1] >> 6)) / 9007199254740992.0


@njit(cache=True, nogil=True)
def _extension_allowed(nodes, parents, last, tx, ty, fixed, corridor, max_span, frame_w, frame_h, min_gap,
                       max_turn, blocked_distance, missing_distance, dem, blocked, radius):
    """corridor_extension_allowed or RouteEvaluator.extension_allowed for the tree chain ending at `last`."""
    ax, ay = nodes[last, 0], nodes[last, 1]
    if corridor:
        length = _norm2(tx - ax, ty - ay)
        return 0 < length <= max_span and (fixed or _placeable(
            blocked_distance, missing_distance, dem, blocked, tx, ty, radius))
    if not (math.isfinite(ax) and math.isfinite(ay) and math.isfinite(tx) and math.isfinite(ty)
            and ax >= 0 and ay >= 0 and tx >= 0 and ty >= 0
            and ax <= frame_w and ay <= frame_h and tx <= frame_w and ty <= frame_h):
        return False
    if not 0 < _length2(tx - ax, ty - ay) <= max_span * max_span:
        return False
    if not fixed:
        if not _placeable(blocked_distance, missing_distance, dem, blocked, tx, ty, radius):
            return False
        if min_gap > 0:
            index = last
            while index > 0:
                if _length2(nodes[index, 0] - tx, nodes[index, 1] - ty) < min_gap * min_gap:
                    return False
                index = parents[index]
    if last > 0:
        px, py = ax - nodes[parents[last], 0], ay - nodes[parents[last], 1]
        cx, cy = tx - ax, ty - ay
        tiny = np.finfo(np.float64).tiny
        pn, cn = max(_norm2(px, py), tiny), max(_norm2(cx, cy), tiny)
        px, py, cx, cy = px / pn, py / pn, cx / cn, cy / cn
        if math.atan2(abs(px * cy - py * cx), _fma(py, cy, px * cx)) - max_turn > 1e-12:
            return False
    return True


@njit(cache=True, nogil=True)
def _rrt_kernel(nodes, parents, counts, python_state, numpy_state, begin, stop, end, upper, goal_bias,
                min_step, max_step, free_attempts, corridor, max_span, min_gap, max_turn,
                blocked_distance, missing_distance, dem, blocked, radius):
    """Iterations [begin, stop) of rrt_path; counts = [node_count, node_checks, edge_checks].

    Returns the iterations run and the tree node whose chain plus `end` is the path, or -1.
    """
    ex, ey, frame_w, frame_h = end[0], end[1], upper[0], upper[1]
    for iteration in range(begin, stop):
        if _mt_random(python_state) < goal_bias:
            tx, ty = ex, ey
        else:
            found = False
            for _ in range(free_attempts):
                tx = 0. + (frame_w - 0.) * _mt_random(python_state)
                ty = 0. + (frame_h - 0.) * _mt_random(python_state)
                counts[1] += 1
                if _placeable(blocked_distance, missing_distance, dem, blocked, tx, ty, radius):
                    found = True
                    break
            if not found:
                continue
        nearest, best = 0, np.inf
        for index in range(counts[0]):
            value = _length2(nodes[index, 0] - tx, nodes[index, 1] - ty)
            if value < best:
                nearest, best = index, value
        ax, ay = nodes[nearest, 0], nodes[nearest, 1]
        dx, dy = tx - ax, ty - ay
        distance = _norm2(dx, dy)
        if distance <= 1e-8:
            continue
        extend = min_step + (max_step - min_step) * _mt_random(numpy_state)
        step = min(extend, distance)
        nx = min(max(ax + dx / distance * step, 0.), frame_w)
        ny = min(max(ay + dy / distance * step, 0.), frame_h)
        if _norm2(nx - ax, ny - ay) <= 1e-8:
            continue
        args = (corridor, max_span, frame_w, frame_h, min_gap, max_turn,
                blocked_distance, missing_distance, dem, blocked, radius)
        counts[2] += 0 if corridor else 1
        if nx == ex and ny == ey:
            if _extension_allowed(nodes, parents, nearest, ex, ey, True, *args):
                return iteration + 1 - begin, nearest
            continue
        if not _extension_allowed(nodes, parents, nearest, nx, ny, False, *args):
            continue
        new = counts[0]
        nodes[new, 0], nodes[new, 1], parents[new] = nx, ny, nearest
        counts[0] += 1
        if _norm2(nx - ex, ny - ey) <= max_step:
            counts[2] += 0 if corridor else 1
            if _extension_allowed(nodes, parents, new, ex, ey, True, *args):
                return iteration + 1 - begin, new
    return stop - begin, -1


def compiled_rrt_path(adapter, upper, *, max_iters, goal_bias, min_step, max_step, free_attempts, corridor,
                      checkpoint=None, stats=None):
    """rrt_path with adapter tower/extension callbacks (strict) or corridor_extension_allowed, compiled."""
    problem, evaluator = adapter.problem, adapter.evaluator
    constraints = problem.constraints
    blocked_distance, missing_distance = evaluator._distance_fields()
    version, words, gauss = adapter.python_rng.getstate()
    python_state = np.array(words, np.int64)
    name, keys, position, has_gauss, cached = adapter.numpy_rng.get_state()
    numpy_state = np.append(keys.astype(np.int64), position)
    nodes = np.empty((max_iters + 2, 2), dtype=float)
    parents = np.empty(max_iters + 2, dtype=np.int64)
    nodes[0], parents[0] = problem.start, -1
    counts = np.array([1, 0, 0], np.int64)
    found = -1
    try:
        for begin in range(0, max_iters, 64):
            if checkpoint is not None:
                checkpoint()
            ran, found = _rrt_kernel(nodes, parents, counts, python_state, numpy_state, begin, min(begin + 64, max_iters),
                np.asarray(problem.end, dtype=float), np.asarray(upper, dtype=float), goal_bias, min_step, max_step,
                free_attempts, corridor, constraints.max_span_m + DISTANCE_TOL_M,
                2 * constraints.tower_radius_m - DISTANCE_TOL_M, math.radians(constraints.max_turn_deg),
                blocked_distance, missing_distance, evaluator._dem, evaluator._blocked, float(constraints.tower_radius_m))
            if stats is not None:
                stats["rrt_iterations"] += ran
            if found >= 0:
                break
    finally:
        adapter.python_rng.setstate((version, tuple(int(word) for word in python_state), gauss))
        adapter.numpy_rng.set_state((name, numpy_state[:624].astype(np.uint32), int(numpy_state[624]), has_gauss, cached))
        adapter.node_checks += int(counts[1])
        adapter.edge_checks += int(counts[2])
    return None if found < 0 else np.vstack([_backtrack(nodes, parents, found), problem.end])


def append_rrt_seeds(initial, adapter, config, window, *, checkpoint=None):
    """Add bounded, fully evaluated unique seeds without old fixed-count encoding."""
    cfg, problem = config.pilot, adapter.problem
    upper = np.array([problem.frame.width, problem.frame.height], dtype=float)
    limit = problem.constraints.max_span_m
    stats = {name: 0 for name in ("rrt_attempts", "rrt_iterations", "rrt_successes",
        "rrt_unique_feasible_seeds", "rrt_duplicate_seeds", "rrt_infeasible_seeds")}
    stats.update(rrt_removed_towers=0, rrt_towers_before=[], rrt_towers_after=[])
    target = min(max(config.popsize - len(initial.routes), 0),
                 max(cfg.rrt_seed_min, min(cfg.rrt_seed_max, config.popsize // cfg.rrt_population_divisor)))
    attempts = max(target * cfg.rrt_attempt_factor, cfg.rrt_min_attempts)
    seen = {route.towers.tobytes() for route in initial.routes}

    def sample_free():
        for _ in range(cfg.rrt_free_sample_attempts):
            point = np.array([adapter.python_rng.uniform(0, size) for size in upper])
            if adapter.tower_allowed(point):
                return point
        return None

    while stats["rrt_unique_feasible_seeds"] < target and stats["rrt_attempts"] < attempts:
        capped = window.budget.total_limit is not None and len(window.budget.records) >= window.budget.total_limit
        if window.used >= window.limit or capped:
            break
        stats["rrt_attempts"] += 1
        path = rrt_path(problem.start, problem.end, upper,
            max_iters=cfg.rrt_iterations_per_span * (initial.lower + 1), goal_bias=cfg.rrt_goal_bias,
            min_step=cfg.rrt_min_step_ratio * limit, max_step=limit,
            python_rng=adapter.python_rng, numpy_rng=adapter.numpy_rng, sample_free=sample_free,
            extension_allowed=lambda path, target, fixed_endpoint=False: corridor_extension_allowed(
                adapter.evaluator, path, target, fixed_endpoint=fixed_endpoint),
            checkpoint=checkpoint, stats=stats, extension_requires_prefix=False)
        if path is None:
            continue
        stats["rrt_successes"] += 1
        route = adapter.route(path)
        signature = route.towers.tobytes()
        if signature in seen:
            stats["rrt_duplicate_seeds"] += 1
            continue
        seen.add(signature)
        checked = window.evaluate(route)
        if checked is None:
            break
        if not checked.is_feasible:
            stats["rrt_infeasible_seeds"] += 1
            continue
        before = len(route.towers)
        if cfg.initialization_mode != "legacy":
            route, checked = prune_reference(route, checked, window.evaluate, problem)
            signature = route.towers.tobytes()
            if signature in {item.towers.tobytes() for item in initial.routes}:
                stats["rrt_duplicate_seeds"] += 1
                continue
        stats["rrt_removed_towers"] += before - len(route.towers)
        stats["rrt_towers_before"].append(before)
        stats["rrt_towers_after"].append(len(route.towers))
        initial.routes.append(route)
        initial.upper = max(initial.upper, len(route.towers))
        initial.valid_references += 1
        stats["rrt_unique_feasible_seeds"] += 1
    return {**stats, "node_checks": adapter.node_checks, "edge_checks": adapter.edge_checks}
