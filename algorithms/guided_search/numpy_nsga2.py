"""Original scalar/NumPy NSGA-II operators and random stream."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .evolution import generation_sigma

EvaluateBatch = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]


@dataclass
class Individual:
    genes: np.ndarray
    objectives: np.ndarray
    violation: float
    rank: int = 0
    crowding: float = 0.0


def dominates(left: Individual, right: Individual) -> bool:
    """Return whether left is preferred to right under constrained dominance."""

    left_ok = left.violation <= 0.0
    right_ok = right.violation <= 0.0
    if left_ok and not right_ok:
        return True
    if right_ok and not left_ok:
        return False
    if not left_ok and not right_ok and left.violation != right.violation:
        return left.violation < right.violation
    not_worse = bool(np.all(left.objectives <= right.objectives))
    better = bool(np.any(left.objectives < right.objectives))
    return not_worse and better


def _assign_crowding(population: list[Individual], front: list[int]) -> None:
    for index in front:
        population[index].crowding = 0.0
    if len(front) <= 2:
        for index in front:
            population[index].crowding = float("inf")
        return
    width = population[front[0]].objectives.shape[0]
    for objective in range(width):
        ordered = sorted(front, key=lambda index: population[index].objectives[objective])
        population[ordered[0]].crowding = float("inf")
        population[ordered[-1]].crowding = float("inf")
        span = population[ordered[-1]].objectives[objective] - population[ordered[0]].objectives[objective]
        if span <= 0.0:
            continue
        for place in range(1, len(ordered) - 1):
            previous = population[ordered[place - 1]].objectives[objective]
            following = population[ordered[place + 1]].objectives[objective]
            population[ordered[place]].crowding += (following - previous) / span


def nondominated_sort(population: list[Individual]) -> list[list[int]]:
    """Assign rank and crowding, and return fronts from best to worst."""

    count = len(population)
    dominated_by = [0] * count
    dominates_these: list[list[int]] = [[] for _ in range(count)]
    for left in range(count):
        for right in range(left + 1, count):
            if dominates(population[left], population[right]):
                dominates_these[left].append(right)
                dominated_by[right] += 1
            elif dominates(population[right], population[left]):
                dominates_these[right].append(left)
                dominated_by[left] += 1
    fronts: list[list[int]] = []
    current = [index for index, degree in enumerate(dominated_by) if degree == 0]
    rank = 0
    while current:
        for index in current:
            population[index].rank = rank
        _assign_crowding(population, current)
        fronts.append(current)
        nxt: list[int] = []
        for index in current:
            for other in dominates_these[index]:
                dominated_by[other] -= 1
                if dominated_by[other] == 0:
                    nxt.append(other)
        current = nxt
        rank += 1
    return fronts


def _tournament(rng: np.random.Generator, population: list[Individual]) -> Individual:
    left = population[int(rng.integers(len(population)))]
    right = population[int(rng.integers(len(population)))]
    left_wins = left.rank < right.rank or (left.rank == right.rank and left.crowding > right.crowding)
    return left if left_wins else right


def _offspring(rng: np.random.Generator, population: list[Individual], sigma: float) -> np.ndarray:
    children = []
    for _ in range(len(population)):
        first = _tournament(rng, population)
        second = _tournament(rng, population)
        child = 0.5 * (first.genes + second.genes) if rng.random() < 0.9 else first.genes.copy()
        children.append(child + rng.normal(0.0, sigma, size=child.shape))
    return np.stack(children).astype(np.float64)


def _select(combined: list[Individual], popsize: int) -> list[Individual]:
    chosen: list[int] = []
    for front in nondominated_sort(combined):
        if len(chosen) + len(front) <= popsize:
            chosen.extend(front)
            continue
        ordered = sorted(front, key=lambda index: combined[index].crowding, reverse=True)
        chosen.extend(ordered[: popsize - len(chosen)])
        break
    return [combined[index] for index in chosen]


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
