"""Post-survival refinement of feasible boundary and sparse-front elites."""

import math
import numpy as np

from algorithms.common.nsga2 import nondominated_sort
from modeling.routing.types import Route
from .population import finite_crowding, individual, survivors
from .refinement import vns
from .variation import encode_candidate


def feasible_front(population):
    indices = [i for i, item in enumerate(population) if item.violation <= 0]
    if not indices:
        return []
    fronts = nondominated_sort([population[i] for i in indices])
    return [indices[i] for i in fronts[0]]


def elite_indices(population, core, popsize):
    front = feasible_front(population)
    if not front:
        return [], set()
    objectives = np.array([item.objectives for item in population])
    boundary = sorted({front[int(np.argmin(objectives[front, j]))] for j in range(objectives.shape[1])})
    pool = [i for i in front if i not in boundary]
    count = min(len(pool), max(core.sparse_min_elites, math.ceil(core.sparse_fraction * len(front))))
    order = np.argsort(-np.array([finite_crowding(population[i].crowding) for i in pool]))
    sparse = [pool[i] for i in order[:count]]
    priority = boundary + sparse
    exhaustive = set(priority)
    if core.local_include_rest:
        priority.extend(i for i in front if i not in exhaustive)
    count = min(len(priority), max(core.local_min_elites, math.ceil(popsize * core.local_fraction)))
    return priority[:count], exhaustive


def local_due(generation, core):
    return (generation - 1) % core.local_search_interval == 0


def refine_population(population, bounds, state):
    priority, exhaustive = elite_indices(population, state.core, state.config.popsize)
    if not priority or not state.budget.remaining:
        return population
    state.count("local_calls")
    state.count("local_selected_elites", len(priority))
    start = len(state.budget.records)
    limit = min(state.budget.remaining, state.config.pilot.local_budget_factor * state.config.popsize)
    additions = []
    for position, index in enumerate(priority):
        remaining = min(state.budget.remaining, limit - (len(state.budget.records) - start))
        if remaining <= 0:
            break
        quota = math.ceil(remaining / (len(priority) - position))
        current = state.lookup(Route(population[index].genes))
        state.count("local_refined_elites")
        # Reserve one full evaluation for the post-resampling acceptance check.
        candidate = vns(current, state, state.budget.window("local_search", max(0, quota - 1)),
                        exhaustive=index in exhaustive)
        if not state.better(current, candidate):
            continue
        state.count("local_raw_accepts")
        route = encode_candidate(candidate, len(current.route.towers), bounds, state)
        if np.array_equal(route.towers, candidate.route.towers):
            encoded = candidate
            state.count("local_encoded_reuses")
        else:
            encoded = state.score(route, state.budget.window("local_search", 1))
            if encoded is not None:
                state.mark(encoded, "local_encoding")
        if encoded is not None and state.better(current, encoded):
            additions.append(individual(encoded))
            state.count("local_encoded_accepts")
    state.count("local_evaluations", len(state.budget.records) - start)
    if not additions:
        return population
    selected = survivors(population + additions, state.config.popsize, state)
    keys = {item.genes.tobytes() for item in selected}
    state.count("local_surviving_proposals", sum(item.genes.tobytes() in keys for item in additions))
    return selected
