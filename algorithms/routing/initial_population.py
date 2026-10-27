"""Initialization assembly; returns evaluated seeds without owning evolution."""

from dataclasses import dataclass
import numpy as np
from algorithms.common.nsga2 import Individual, select_population
from modeling.routing.types import Route
from .initialization import initialize_routes
from .ranges import TowerRange


@dataclass
class InitialPopulation:
    population: list[Individual]
    bounds: TowerRange
    diagnostics: dict | None


def initialize_population(evaluator, config, rng, budget, report, *, reference_initializer=None, fill_variation=None):
    reference_initializer = initialize_routes if reference_initializer is None else reference_initializer
    problem, records = evaluator.problem, budget.records
    mode = config.pilot.initialization_mode
    pilot_enabled = config.search_strategy == "pilot_reference" and (bool(config.pilot.enabled_mechanisms) or mode != "legacy")
    initialization = budget.window("initialization", config.pilot.initialization_budget_factor * config.popsize
                                   if pilot_enabled else config.max_evaluations)

    def evaluate(route):
        return initialization.evaluate(route)

    report("initialization", "正在生成参考线路与初始塔数范围（CPU）")
    initial = reference_initializer(evaluator, config, rng, evaluate,
        checkpoint=lambda: report("initialization", "正在搜索满足塔基与档距的绕行参考线（CPU）"))
    reference_routes, reference_upper = initial.routes.copy(), initial.upper
    pilot_initialization = {} if mode != "legacy" else None
    if "rrt" in config.pilot.enabled_mechanisms:
        from .pilot_reference.adapter import PilotAdapter
        from .pilot_reference.rrt import append_rrt_seeds
        seed_window = initialization
        if mode != "legacy":
            reserve = max(0, config.popsize - len(reference_routes)) if mode in {"balanced", "bounded"} else 0
            seed_window = budget.window("initialization", max(0, initialization.limit - len(records) - reserve))
        pilot_initialization = append_rrt_seeds(initial, PilotAdapter(evaluator, config.seed), config, seed_window,
            checkpoint=lambda: report("initialization", "正在生成 RRT 绕行种子（CPU）"))
    bounds = TowerRange(initial.lower, initial.upper, initial.upper)
    if mode != "legacy":
        from .pilot_reference.initialization import seed_population
        initialization = budget.window("initialization", max(0, initialization.limit - len(records)))
        if mode == "bounded":
            bounds.probe_upper = reference_upper
        population, stats = seed_population(reference_routes, initial.routes[len(reference_routes):],
                                            bounds, evaluator, config, initialization, variation=fill_variation)
        pilot_initialization.update(stats, reference_upper=reference_upper)
    else:
        population = [Individual(route.towers, value.objectives, value.violation)
                      for route, value in records if bounds.lower <= len(route.towers) <= bounds.upper]
    if not population:
        base = Route(np.linspace(problem.start, problem.end, bounds.lower + 2)[1:-1])
        checked = evaluate(base)
        if checked is not None:
            population = [Individual(base.towers, checked.objectives, checked.violation)]
    if population:
        population = select_population(population, config.popsize)
    return InitialPopulation(population, bounds, pilot_initialization)
