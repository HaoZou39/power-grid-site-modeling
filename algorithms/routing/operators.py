"""Exclusive action dispatch with independently replaceable tower operators."""

from dataclasses import dataclass
from typing import Callable
import numpy as np

from config.project_config import RoutingConfig
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import Route
from .repair import repair_towers


def move_tower(towers, sigma, rng):
    index = int(rng.integers(len(towers)))
    towers[index] += rng.normal(0, sigma, 2)
    return towers


def insert_tower(towers, start, end, sigma, rng):
    points = Route(towers).points(start, end)
    index = int(rng.integers(len(points) - 1))
    center = (points[index] + points[index + 1]) / 2
    center += rng.normal(0, sigma, 2)
    return np.insert(towers, index, center, axis=0)


def delete_tower(towers, rng):
    return np.delete(towers, int(rng.integers(len(towers))), axis=0)


def crossover(towers, other, rng):
    left = int(rng.integers(len(towers) + 1))
    right = int(rng.integers(len(other) + 1))
    return np.vstack([towers[:left], other[right:]])


@dataclass(frozen=True)
class NumpyOperators:
    move: Callable
    insert: Callable
    delete: Callable
    crossover: Callable
    repair: Callable


def numpy_operators():
    return NumpyOperators(move_tower, insert_tower, delete_tower, crossover, repair_towers)


def constrain_tower_count(towers, evaluator, config, rng, lower, upper, target_count):
    desired = max(lower, min(upper, len(towers))) if target_count is None else target_count
    desired = max(lower, min(upper, desired))
    while len(towers) < desired:
        points = Route(towers).points(evaluator.problem.start, evaluator.problem.end)
        index = int(np.argmax(np.linalg.norm(np.diff(points, axis=0), axis=1)))
        center = (points[index] + points[index + 1]) / 2
        center += rng.normal(0, config.mutation_scale * evaluator.problem.constraints.max_span_m, 2)
        towers = np.insert(towers, index, center, axis=0)
    while len(towers) > desired:
        towers = np.delete(towers, int(rng.integers(len(towers))), axis=0)
    radius = evaluator.problem.constraints.tower_radius_m
    if min(evaluator.problem.frame.width, evaluator.problem.frame.height) >= 2 * radius:
        towers = np.clip(towers, radius, [evaluator.problem.frame.width - radius, evaluator.problem.frame.height - radius])
    return towers


def offspring(first: Route, second: Route, evaluator: RouteEvaluator, config: RoutingConfig,
              rng: np.random.Generator, lower: int, upper: int, *, target_count: int | None = None,
              operators: NumpyOperators | None = None) -> Route:
    operators = numpy_operators() if operators is None else operators
    towers = first.towers.copy()
    sigma = config.mutation_scale * evaluator.problem.constraints.max_span_m
    action = int(rng.integers(4))
    if action == 0 and len(towers):
        towers = operators.move(towers, sigma, rng)
    elif action == 1 and len(towers) < upper:
        towers = operators.insert(towers, evaluator.problem.start, evaluator.problem.end, sigma, rng)
    elif action == 2 and len(towers) > lower:
        towers = operators.delete(towers, rng)
    elif len(towers) and len(second.towers):
        towers = operators.crossover(towers, second.towers, rng)
    towers = constrain_tower_count(towers, evaluator, config, rng, lower, upper, target_count)
    return operators.repair(Route(towers), evaluator, config, rng)
