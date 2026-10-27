"""Original adaptive multi-trial mutation with task-local geometry and streams."""

import numpy as np
from .runtime import dedup_path


def mutate(current, state, window):
    path = state.adapter.path(current.route)
    if len(path) <= 2 or not window.remaining:
        return current
    best = current
    index = state.adapter.python_rng.randint(1, len(path) - 2)
    radius = state.neighborhood_radius(path, index)
    base = path[index].copy()
    previous, following = path[index - 1], path[index + 1]
    for _ in range(max(1, state.core.mutation_tries)):
        if not window.remaining:
            break
        state.checkpoint()
        angle = float(state.adapter.numpy_rng.uniform(0., 2. * np.pi))
        distance = float(state.adapter.numpy_rng.uniform(state.core.mutation_min_fraction, 1.) * radius)
        state.count("mutation_draws")
        moved = base + distance * np.array([np.cos(angle), np.sin(angle)])
        projection = max(state.core.projection_min_radius, round(radius / state.scale)) * state.scale
        moved = state.project(moved, projection, prefer_clearance=state.core.mutation_clearance_bias)
        if not state.evaluator.span_allowed(previous, moved) or not state.evaluator.span_allowed(moved, following):
            continue
        points = path.copy()
        points[index] = moved
        points = dedup_path(points)
        if len(points) < 2 or not state.valid_path(points):
            continue
        candidate = state.score(state.adapter.route(points), window)
        if candidate is None:
            break
        state.count("mutation_evaluations")
        if state.better(best, candidate):
            best = candidate
            state.count("mutation_accepts")
    return best
