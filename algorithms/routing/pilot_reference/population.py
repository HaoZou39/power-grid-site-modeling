"""Neutral PILOT parent selection and adapters to shared NSGA-II mathematics."""

import numpy as np
from algorithms.common.nsga2 import Individual, nondominated_sort, select_population


def individual(candidate):
    return Individual(candidate.route.towers, candidate.evaluation.objectives, candidate.evaluation.violation)


def finite_crowding(value):
    return float(np.nan_to_num(value, nan=-1., posinf=1e9))


def tournament_index(population, state):
    if len(population) <= 1:
        return 0
    a, b = state.adapter.python_rng.sample(range(len(population)), 2)
    first, second = population[a], population[b]
    if (first.violation <= 0) != (second.violation <= 0):
        return a if first.violation <= 0 else b
    if first.violation > 0 and second.violation > 0:
        if first.violation < second.violation - state.core.cv_tolerance:
            return a
        if second.violation < first.violation - state.core.cv_tolerance:
            return b
        return a
    if first.rank != second.rank:
        return a if first.rank < second.rank else b
    ca, cb = finite_crowding(first.crowding), finite_crowding(second.crowding)
    if ca > cb + state.core.crowding_tolerance:
        return a
    if cb > ca + state.core.crowding_tolerance:
        return b
    return a if state.adapter.python_rng.random() < .5 else b


def parent_pair(population, state):
    a, b = tournament_index(population, state), tournament_index(population, state)
    if "distinct_parents" in state.config.pilot.enabled_mechanisms and len(population) > 1:
        tries = 0
        while b == a and tries < state.core.parent_retries:
            b = tournament_index(population, state)
            tries += 1
            state.count("parent_retries")
    state.count("parent_pairs")
    state.count("same_parent_pairs", int(a == b))
    return a, b


def survivors(population, size, state):
    return select_population(population, size)
