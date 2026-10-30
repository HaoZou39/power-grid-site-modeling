"""Keep processed seed provenance separate from internal evaluation trials."""

import numpy as np

from algorithms.common.nsga2 import Individual, select_population
from modeling.routing.types import Route
from ..operators import offspring


def seed_population(reference_routes, rrt_routes, bounds, evaluator, config, window, *, variation=None):
    variation = offspring if variation is None else variation
    values = {route.towers.tobytes(): checked for route, checked in window.history}

    def candidates(routes):
        unique = {route.towers.tobytes(): route for route in routes
                  if bounds.lower <= len(route.towers) <= bounds.upper}
        return [Individual(route.towers, values[key].objectives, values[key].violation)
                for key, route in unique.items()]

    reference, rrt = candidates(reference_routes), candidates(rrt_routes)
    stats = {"reference_upper": bounds.probe_upper if bounds.probe_upper is not None else bounds.initial_upper,
             "initial_reused_slots": 0, "initial_fill_evaluations": 0}
    if config.pilot.initialization_mode == "pruned":
        population = select_population(reference + rrt, config.popsize)
        rrt_keys = {item.genes.tobytes() for item in rrt}
        stats["initial_rrt_slots"] = sum(item.genes.tobytes() in rrt_keys for item in population)
    else:
        rng = np.random.default_rng(config.seed)
        quota = min(len(rrt), config.popsize // config.pilot.rrt_population_divisor)
        if not reference:
            reference, rrt, quota = rrt, [], 0
        if not reference:
            raise RuntimeError("initialization produced no evaluated seed in the tower range")
        population = []
        used = window.used
        for source, size in [(reference, config.popsize - quota), (rrt, quota)]:
            if not size:
                continue
            feasible = [item for item in source if item.violation <= 0]
            source = feasible or source
            chosen = select_population(source, size)
            seen = {item.genes.tobytes() for item in chosen}
            while len(chosen) < size:
                first, second = [source[int(rng.integers(len(source)))] for _ in range(2)]
                child = variation(Route(first.genes), Route(second.genes), evaluator, config, rng,
                                  bounds.lower, bounds.upper)
                checked = window.evaluate(child)
                if checked is None:
                    break
                if child.towers.tobytes() not in seen and (checked.is_feasible or not feasible):
                    seen.add(child.towers.tobytes())
                    chosen.append(Individual(child.towers, checked.objectives, checked.violation))
            while len(chosen) < size:
                item = source[len(chosen) % len(source)]
                chosen.append(Individual(item.genes, item.objectives, item.violation))
            population.extend(chosen)
        stats["initial_fill_evaluations"] = window.used - used
        stats["initial_rrt_slots"] = quota
    stats["initial_population_size"] = len(population)
    stats["initial_unique_population"] = len({item.genes.tobytes() for item in population})
    stats["initial_reused_slots"] = len(population) - stats["initial_unique_population"]
    return population, stats
