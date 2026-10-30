"""PILOT nearest-waypoint crossover and evaluated offspring assembly."""

import numpy as np

from modeling.routing.types import Route
from .hybrid import sample_route


def crossover(first, second, state, window):
    curr_a, curr_b = state.adapter.path(first.route), state.adapter.path(second.route)
    best = second if state.better(first, second) else first
    if len(curr_a) <= 2 or len(curr_b) <= 2:
        return best
    candidate_pairs = []
    for i in range(1, len(curr_a) - 1):
        d2 = np.sum((curr_b[1:-1] - curr_a[i]) ** 2, axis=1)
        j = 1 + int(np.argmin(d2))
        candidate_pairs.append((float(np.min(d2)), i, j))
    candidate_pairs.sort(key=lambda item: item[0])
    improved = False
    for _, i, j in candidate_pairs[:max(1, state.core.crossover_max_pairs)]:
        if not window.remaining:
            break
        state.count("crossover_pairs")
        if not state.evaluator.span_allowed(curr_a[i], curr_b[j]):
            continue
        for raw in (np.vstack([curr_a[:i + 1], curr_b[j:]]), np.vstack([curr_b[:j + 1], curr_a[i:]])):
            state.count("crossover_raw_candidates")
            clean = state.sanitize(raw)
            if not state.valid_path(clean):
                continue
            candidate = state.score(state.adapter.route(clean), window)
            if candidate is None:
                break
            state.mark(candidate, "crossover")
            state.count("crossover_evaluations")
            if state.better(best, candidate):
                best, improved = candidate, True
                state.count("crossover_accepts")
        if improved:
            break
    return best


def encode_candidate(best, hint, bounds, state):
    clean = state.sanitize(state.adapter.path(best.route))
    desired = min(bounds.upper, max(bounds.lower, hint))
    route = sample_route(clean, desired, state)
    if not state.valid_path(state.adapter.path(route)):
        natural = min(bounds.upper, max(bounds.lower, len(clean) - 2))
        route = sample_route(clean, natural, state)
    return route


def offspring(first, second, bounds, state, window, *, target_count=None):
    start_index = len(state.budget.records)
    best = second if state.better(first, second) else first
    hint = len(best.route.towers)
    mechanisms = state.config.pilot.enabled_mechanisms
    if "nearby_crossover" in mechanisms and state.adapter.python_rng.random() < state.core.crossover_probability:
        state.count("crossover_calls")
        candidate = crossover(first, second, state, window)
        if state.better(best, candidate):
            best = candidate
    if "path_mutation" in mechanisms and state.adapter.python_rng.random() < state.core.mutation_probability:
        from .mutation import mutate
        state.count("mutation_calls")
        candidate = mutate(best, state, window)
        if state.better(best, candidate):
            best = candidate
    if "shorten" in mechanisms or "smooth" in mechanisms:
        from .refinement import shorten, smooth
        for name, operation in (("shorten", shorten), ("smooth", smooth)):
            if name not in mechanisms:
                continue
            state.count(name + "_calls")
            candidate = operation(best, state, window)
            if state.better(best, candidate):
                best = candidate
    route = encode_candidate(best, hint if target_count is None else target_count, bounds, state)
    completed = state.candidates.get(route.towers.tobytes())
    if completed is not None and completed.evaluation_index >= start_index:
        state.count("evaluated_offspring_reuses")
        return completed
    checked = state.score(route, window)
    if checked is not None:
        state.mark(checked, "offspring_encoding")
        return checked
    # Only complete in-range states may survive a truncated internal call.
    if bounds.lower <= len(best.route.towers) <= bounds.upper:
        return best
    return first
