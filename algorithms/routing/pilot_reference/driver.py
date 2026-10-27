"""Independent CPU composition for incrementally migrated PILOT control flow."""

from dataclasses import dataclass, replace
import time

from algorithms.common.nsga2 import nondominated_sort
from modeling.routing.types import Route

from ..initial_population import InitialPopulation, initialize_population
from ..numpy_search import evolve as baseline_evolve
from .adapter import PilotAdapter
from .runtime import RunState


@dataclass
class PilotInitialPopulation(InitialPopulation):
    run_state: RunState


def initialize(evaluator, config, rng, budget, report):
    state = RunState(PilotAdapter(evaluator, config.seed), config, budget, report)
    hybrid = config.pilot.initialization_mode == "hybrid"
    base_config = replace(config, pilot=replace(config.pilot, initialization_mode="legacy", enabled_mechanisms=[])) if hybrid else config
    initial = initialize_population(evaluator, base_config, rng, budget, report, pilot_adapter=state.adapter)
    state.diagnostics.update(initial.diagnostics or {})
    state.remember()
    state.diagnostics["implementation"] = "pilot_cpu"
    result = PilotInitialPopulation(initial.population, initial.bounds, state.diagnostics, initial.candidates, state)
    if hybrid:
        from .hybrid import initialize_hybrid
        initialize_hybrid(result, state)
    elif "astar" in config.pilot.enabled_mechanisms:
        from .astar import append_astar_seeds
        append_astar_seeds(result, state)
    return result


def evolve(evaluator, config, initial, budget, rng, report):
    if set(config.pilot.enabled_mechanisms) <= {"cpu_driver", "rrt", "astar"}:
        return baseline_evolve(evaluator, config, initial, budget, rng, report)
    from .population import parent_pair, individual, survivors
    from .variation import offspring
    state, bounds = initial.run_state, initial.bounds
    population = initial.population
    global_enabled = "global_injection" in config.pilot.enabled_mechanisms
    if global_enabled:
        from .global_search import inject_population, update_survival
        state.stagnation = update_survival(population, {})
    window = budget.window("offspring", config.max_evaluations)
    expansions, generation = [], 0
    elapsed = {"ranking_s": 0., "variation_and_repair_s": 0.}
    while budget.remaining and population:
        generation += 1
        expanded = bounds.expand(generation, config)
        if expanded:
            expansions.append({"generation": generation, "upper": bounds.upper, "evaluations": len(budget.records)})
            if bounds.probe_upper is not None:
                expansions[-1]["probe_upper"] = bounds.probe_upper
        started = time.perf_counter()
        nondominated_sort(population)
        elapsed["ranking_s"] += time.perf_counter() - started
        children = []
        for index in range(config.popsize):
            if not window.remaining:
                break
            a, b = parent_pair(population, state)
            first = state.lookup(Route(population[a].genes))
            second = state.lookup(Route(population[b].genes))
            target = (bounds.probe_upper if bounds.probe_upper is not None else bounds.upper) if expanded and index == 0 else None
            started, evaluation_before = time.perf_counter(), budget.evaluation_s
            candidate = offspring(first, second, bounds, state, window, target_count=target)
            elapsed["variation_and_repair_s"] += time.perf_counter() - started - (budget.evaluation_s - evaluation_before)
            children.append(individual(candidate))
            state.count("offspring_submitted")
        started = time.perf_counter()
        population = survivors(population + children, config.popsize, state)
        elapsed["ranking_s"] += time.perf_counter() - started
        if "elite_local_search" in config.pilot.enabled_mechanisms:
            from .local_search import local_due, refine_population
            if local_due(generation, state.core):
                state.diagnostics.setdefault("local_generations", []).append(generation)
                population = refine_population(population, bounds, state)
        if global_enabled:
            population = inject_population(population, bounds, state)
            state.stagnation = update_survival(population, state.stagnation)
        report("evolution", f"PILOT CPU 第 {generation} 代，已评价 {len(budget.records)}/{config.max_evaluations}")
    if global_enabled:
        state.diagnostics["survival_max"] = max(state.stagnation.values(), default=0)
    state.diagnostics.update(node_checks=state.adapter.node_checks, edge_checks=state.adapter.edge_checks)
    return expansions, elapsed, generation
