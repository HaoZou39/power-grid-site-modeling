"""PILOT's single-tree RRT flow, with continuous metric geometry callbacks.

Source: frozen path_planners.py::_rrt_path and _build_astar_rrt_population.
The coarse-cell rounding, legacy encoding and A* fallback are deliberately absent.
"""

import numpy as np

from ..initialization import prune_reference


def _backtrack(nodes, parents, index):
    path = []
    while index >= 0:
        path.append(nodes[index])
        index = parents[index]
    return np.asarray(path[::-1], dtype=float)


def rrt_path(start, end, upper, *, max_iters, goal_bias, min_step, max_step,
             python_rng, numpy_rng, sample_free, extension_allowed, checkpoint=None, stats=None):
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
        prefix = _backtrack(nodes[:node_count], parents[:node_count], nearest_idx)
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
        if window.used >= window.limit or len(window.budget.records) >= window.budget.total_limit:
            break
        stats["rrt_attempts"] += 1
        path = rrt_path(problem.start, problem.end, upper,
            max_iters=cfg.rrt_iterations_per_span * (initial.lower + 1), goal_bias=cfg.rrt_goal_bias,
            min_step=cfg.rrt_min_step_ratio * limit, max_step=limit,
            python_rng=adapter.python_rng, numpy_rng=adapter.numpy_rng, sample_free=sample_free,
            extension_allowed=adapter.extension_allowed, checkpoint=checkpoint, stats=stats)
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
