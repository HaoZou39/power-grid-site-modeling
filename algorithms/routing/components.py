"""Explicit Python-only search composition, shared by builtins and experiments."""

from dataclasses import dataclass
from typing import Callable
from .initial_population import initialize_population
from .numpy_search import evolve as numpy_evolve


@dataclass(frozen=True)
class SearchComponents:
    initializer: Callable
    driver: Callable


def tensor_driver(evaluator, config, initial, budget, rng, report, **operators):
    if config.evolution_backend != "tensor":
        raise ValueError("tensor routing driver requires evolution_backend=tensor")
    from .tensor_search import evolve
    window = budget.window("offspring", config.max_evaluations)
    return evolve(evaluator, config, initial.bounds, budget.records, window.evaluate_many, report, entries=initial.candidates, **operators)


def builtin_components(config):
    if config.search_strategy == "pilot_reference" and (config.pilot.initialization_mode == "hybrid" or any(name != "rrt" for name in config.pilot.enabled_mechanisms)):
        from .pilot_reference.driver import initialize, evolve
        return SearchComponents(initialize, evolve)
    drivers = {"numpy": numpy_evolve, "tensor": tensor_driver}
    if config.evolution_backend not in drivers:
        raise ValueError(f"unsupported routing evolution backend: {config.evolution_backend}")
    return SearchComponents(initialize_population, drivers[config.evolution_backend])
