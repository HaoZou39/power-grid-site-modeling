"""Shared constrained NSGA-II ranking; genes may be site poses or tower arrays."""

from dataclasses import dataclass
import numpy as np

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
        if not np.isfinite(span) or span <= 0.0:
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


def tournament(rng: np.random.Generator, population: list[Individual]) -> Individual:
    left = population[int(rng.integers(len(population)))]
    right = population[int(rng.integers(len(population)))]
    left_wins = left.rank < right.rank or (left.rank == right.rank and left.crowding > right.crowding)
    return left if left_wins else right


def select_population(combined: list[Individual], popsize: int) -> list[Individual]:
    chosen: list[int] = []
    for front in nondominated_sort(combined):
        if len(chosen) + len(front) <= popsize:
            chosen.extend(front)
            continue
        ordered = sorted(front, key=lambda index: combined[index].crowding, reverse=True)
        chosen.extend(ordered[: popsize - len(chosen)])
        break
    return [combined[index] for index in chosen]
