"""Every-generation fresh proposals and consecutive continuous-route survival."""

import math
from modeling.routing.types import Route
from .hybrid import build_population
from .local_search import feasible_front
from .population import individual, survivors
from .variation import offspring


def update_survival(population, previous):
    return {item.genes.tobytes(): previous.get(item.genes.tobytes(), 0) + 1 for item in population}


def inject_population(population, bounds, state):
    front = feasible_front(population)
    dominated = [i for i in range(len(population)) if i not in front]
    if not dominated or not state.budget.remaining:
        return population
    state.count("global_calls")
    target = max(state.core.global_min_new, math.ceil(state.config.popsize * state.core.global_fraction))
    stagnant = [i for i in dominated if state.stagnation.get(population[i].genes.tobytes(), 0) >= state.core.stagnation_limit]
    window = state.budget.window("global_search", state.config.pilot.global_budget_factor * state.config.popsize)
    random_count = max(1, target // 2)
    parents = [state.lookup(Route(p.genes)) for p in population]
    additions = build_population(state, bounds, window, random_count, include_astar=False, include_rrt=True,
                                fallback=parents, anchor_for_fill=True, category="global")
    state.count("global_random_submitted", len(additions))
    pool = front
    if len(pool) < 2:
        feasible = [i for i, p in enumerate(population) if p.violation <= 0]
        pool = feasible if len(feasible) > 1 else list(range(len(population)))
    for _ in range(max(0, target - random_count)):
        if not window.remaining:
            break
        if len(pool) >= 2:
            a, b = state.adapter.numpy_rng.choice(pool, size=2, replace=False)
        else:
            a = b = pool[0]
        additions.append(offspring(parents[a], parents[b], bounds, state, window))
        state.count("global_offspring_submitted")
    remove = set(stagnant[:min(len(stagnant), len(additions))])
    state.count("global_stagnant_removed", len(remove))
    base = [p for i, p in enumerate(population) if i not in remove]
    added = [individual(c) for c in additions]
    selected = survivors(base + added, state.config.popsize, state)
    new_keys = {p.genes.tobytes() for p in selected} - {p.genes.tobytes() for p in population}
    state.count("global_new_survivors", len(new_keys))
    state.count("global_evaluations", window.used)
    return selected
