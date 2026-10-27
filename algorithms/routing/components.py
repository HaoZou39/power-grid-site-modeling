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
    from .tensor_search import evolve
    window = budget.window("offspring", config.max_evaluations)
    return evolve(evaluator, config, initial.bounds, budget.records, window.evaluate_many, report, **operators)


def builtin_components(config):
    drivers = {"numpy": numpy_evolve, "tensor": tensor_driver}
    if config.evolution_backend not in drivers:
        raise ValueError(f"unsupported routing evolution backend: {config.evolution_backend}")
    return SearchComponents(initialize_population, drivers[config.evolution_backend])
