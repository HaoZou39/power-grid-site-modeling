"""Original scalar/NumPy NSGA-II operators and random stream."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from .evolution import generation_sigma
from algorithms.common.nsga2 import Individual, dominates, nondominated_sort, tournament as _tournament, select_population as _select

EvaluateBatch = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]


def _offspring(rng: np.random.Generator, population: list[Individual], sigma: float) -> np.ndarray:
    children = []
    for _ in range(len(population)):
        first = _tournament(rng, population)
        second = _tournament(rng, population)
        child = 0.5 * (first.genes + second.genes) if rng.random() < 0.9 else first.genes.copy()
        children.append(child + rng.normal(0.0, sigma, size=child.shape))
    return np.stack(children).astype(np.float64)


def _evaluate(evaluate: EvaluateBatch, genes: np.ndarray) -> list[Individual]:
    objectives, violation = evaluate(genes)
    if objectives.shape != (genes.shape[0], objectives.shape[1]) or violation.shape != (genes.shape[0],):
        raise ValueError("evaluate must return one objective row and one violation per candidate")
    if objectives.shape[1] < 1:
        raise ValueError("evaluate must return at least one objective")
    return [
        Individual(genes[index].copy(), objectives[index].astype(np.float64), float(violation[index]))
        for index in range(genes.shape[0])
    ]


def run_evolution(
    evaluate: EvaluateBatch,
    *,
    popsize: int,
    generations: int,
    seed: int,
    sigma: float,
    n_var: int = 3,
    initial: np.ndarray | None = None,
    on_generation: Callable[[int, int], None] | None = None,
    anneal_last: int = 0,
    anneal_sigma_end: float | None = None,
    step_control: Any | None = None,
) -> list[Individual]:
    """Evolve one population. ``evaluate`` returns objectives and constraint violation."""

    if popsize < 4 or generations < 1 or sigma <= 0 or n_var < 1:
        raise ValueError("popsize must be at least 4, generations at least 1, and sigma positive")
    rng = np.random.default_rng(seed)
    if initial is None:
        genes = rng.normal(0.0, sigma, size=(popsize, n_var))
    else:
        genes = np.asarray(initial, dtype=np.float64)
        if genes.shape != (popsize, n_var):
            raise ValueError(f"initial population must have shape [{popsize}, {n_var}]")
    population = _evaluate(evaluate, genes)
    nondominated_sort(population)
    for generation in range(generations):
        step_sigma = step_control.sigma if step_control is not None else generation_sigma(
            generation, generations, sigma, anneal_last, anneal_sigma_end
        )
        children = _evaluate(evaluate, _offspring(rng, population, step_sigma))
        population = _select(population + children, popsize)
        nondominated_sort(population)
        if step_control is not None:
            step_control.observe(np.stack([person.objectives for person in population]))
        if on_generation is not None:
            on_generation(generation, generations)
    return population
