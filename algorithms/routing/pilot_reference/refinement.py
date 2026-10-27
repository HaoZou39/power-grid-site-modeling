"""PILOT shortening, angle smoothing and variable-neighborhood refinement."""

import numpy as np
from .runtime import dedup_path


def shorten(current, state, window):
    path = state.adapter.path(current.route)
    best = current
    if len(path) <= 3:
        return best
    for index in range(1, len(path) - 1):
        if not window.remaining:
            break
        state.checkpoint()
        if not state.evaluator.span_allowed(path[index - 1], path[index + 1]):
            continue
        points = np.delete(path, index, axis=0)
        candidate = state.score(state.adapter.route(points), window)
        if candidate is None:
            break
        state.count("shorten_evaluations")
        if state.better(best, candidate, target=1, margin=state.core.shorten_margin * state.scale):
            best = candidate
            state.count("shorten_accepts")
    return best


def smooth(current, state, window):
    path = state.adapter.path(current.route)
    if len(path) <= 2:
        return current
    if len(path) <= 3:
        indices = [1]
    else:
        normalized = path / state.scale
        first, second = normalized[1:-1] - normalized[:-2], normalized[2:] - normalized[1:-1]
        denominator = np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1) + 1e-8
        angles = np.arccos(np.clip(np.sum(first * second, axis=1) / denominator, -1., 1.))
        indices = (1 + np.argsort(-angles)).tolist()[:min(state.core.smooth_max_points, len(angles))]
    best = current
    for index in indices:
        previous, center, following = path[index - 1], path[index], path[index + 1]
        for proposal in (previous + state.core.smooth_previous_fraction * (center - previous),
                         center + state.core.smooth_next_fraction * (following - center)):
            if not window.remaining:
                return best
            state.checkpoint()
            radius = state.neighborhood_radius(path, index)
            projection = max(state.core.projection_min_radius, round(radius / state.scale)) * state.scale
            moved = state.project(proposal, projection, prefer_clearance=state.core.smooth_clearance_bias)
            points = path.copy()
            points[index] = moved
            points = dedup_path(points)
            if len(points) < 2 or not state.valid_path(points):
                continue
            candidate = state.score(state.adapter.route(points), window)
            if candidate is None:
                return best
            state.count("smooth_evaluations")
            if state.better(best, candidate, target=2, margin=state.core.smooth_margin):
                best = candidate
                state.count("smooth_accepts")
    return best


def vns(current, state, window, *, exhaustive=False):
    path = state.adapter.path(current.route)
    if len(path) <= 2 or not window.remaining:
        return current
    indices = list(range(1, len(path) - 1))
    if not exhaustive:
        state.adapter.python_rng.shuffle(indices)
        indices = indices[:min(state.core.vns_fast_points, len(indices))]
    best = current
    for index in indices:
        points = state.adapter.path(best.route)
        if index <= 0 or index >= len(points) - 1 or not window.remaining:
            continue
        radius = state.neighborhood_radius(points, index)
        reference_radius = radius / state.scale
        tries = (max(state.core.vns_exhaustive_min_tries, int(round(reference_radius))) if exhaustive else
                 max(state.core.vns_fast_min_tries, int(round(state.core.vns_fast_try_factor * reference_radius))))
        base = points[index].copy()
        local_best = best
        for _ in range(tries):
            points = state.adapter.path(local_best.route)
            if not window.remaining or index <= 0 or index >= len(points) - 1:
                break
            state.checkpoint()
            sigma = (state.core.vns_exhaustive_sigma if exhaustive else state.core.vns_fast_sigma) * radius
            delta = state.adapter.numpy_rng.normal(0., sigma, size=2)
            state.count("vns_draws")
            projection = max(state.core.projection_min_radius, round(reference_radius)) * state.scale
            moved = state.project(base + delta, projection, prefer_clearance=state.core.vns_clearance_bias)
            if not state.evaluator.span_allowed(points[index - 1], moved) or not state.evaluator.span_allowed(moved, points[index + 1]):
                continue
            original_size = len(points)
            candidate_points = points.copy()
            candidate_points[index] = moved
            candidate_points = dedup_path(candidate_points)
            if len(candidate_points) < 2:
                continue
            if len(candidate_points) != original_size and not state.valid_path(candidate_points):
                continue
            candidate = state.score(state.adapter.route(candidate_points), window)
            if candidate is None:
                break
            state.count("vns_evaluations")
            if state.better(local_best, candidate):
                local_best = candidate
                state.count("vns_accepts")
        best = local_best
    return best
