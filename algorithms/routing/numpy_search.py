"""CPU evolution driver, independent of initialization and archive writing."""

import time
from algorithms.common.nsga2 import Individual
from modeling.routing.types import Route
from .evaluation_budget import UNBOUNDED
from .operators import offspring
from .selection import numpy_selection
from .ranges import expand_range
from .types import EvaluatedCandidate


def generate_candidate(first, second, evaluator, config, rng, lower, upper, *, target_count, window, variation):
    route = variation(first, second, evaluator, config, rng, lower, upper, target_count=target_count)
    checked = window.evaluate(route)
    return None if checked is None else EvaluatedCandidate(route, checked)


def evolve(evaluator, config, initial, budget, rng, report, *, variation=None, selection=None,
           generate=None, range_policy=None):
    if config.evolution_backend != "numpy":
        raise ValueError("NumPy routing driver requires evolution_backend=numpy")
    variation = offspring if variation is None else variation
    selection = numpy_selection() if selection is None else selection
    generate = generate_candidate if generate is None else generate
    range_policy = expand_range if range_policy is None else range_policy
    population, bounds, records = initial.population, initial.bounds, budget.records
    offspring_budget = budget.window("offspring", UNBOUNDED)
    expansions, generation = [], 0
    stage_times = {"ranking_s": 0., "variation_and_repair_s": 0.}
    while generation < config.max_generations and population:
        generation += 1
        expanded = range_policy(bounds, generation, config)
        if expanded:
            expansions.append({"generation": generation, "upper": bounds.upper, "evaluations": len(records)})
            if bounds.probe_upper is not None:
                expansions[-1]["probe_upper"] = bounds.probe_upper
        started = time.perf_counter()
        selection.rank(population)
        stage_times["ranking_s"] += time.perf_counter() - started
        children = []
        for index in range(config.popsize):
            first, second = selection.parents(rng, population), selection.parents(rng, population)
            # Boundary probes run even after finding a feasible low-tower solution.
            target = (bounds.probe_upper if bounds.probe_upper is not None else bounds.upper) if expanded and index == 0 else None
            started = time.perf_counter()
            evaluation_before = budget.evaluation_s
            candidate = generate(Route(first.genes), Route(second.genes), evaluator, config, rng,
                                 bounds.lower, bounds.upper, target_count=target,
                                 window=offspring_budget, variation=variation)
            stage_times["variation_and_repair_s"] += time.perf_counter() - started - (budget.evaluation_s - evaluation_before)
            if candidate is None:
                break
            child, checked = candidate.route, candidate.evaluation
            children.append(Individual(child.towers, checked.objectives, checked.violation))
        started = time.perf_counter()
        population = selection.survivors(population + children, config.popsize)
        stage_times["ranking_s"] += time.perf_counter() - started
        budget.completed_generations = generation
        report("evolution", f"第 {generation}/{config.max_generations} 代，已评价 {len(records)} 次，塔数范围 {bounds.lower}–{bounds.upper}（CPU）")
    budget.stop_reason = "generation_limit"
    return expansions, stage_times, generation
