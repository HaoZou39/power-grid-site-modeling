"""Variable-length tower operators; the two connection points remain external."""

import numpy as np

from config.project_config import RoutingConfig
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import Route
from .initialization import repair_towers


def offspring(first: Route, second: Route, evaluator: RouteEvaluator, config: RoutingConfig,
              rng: np.random.Generator, lower: int, upper: int, *, target_count: int | None = None) -> Route:
    towers = first.towers.copy()
    action = int(rng.integers(4))
    if action == 0 and len(towers):
        index = int(rng.integers(len(towers)))
        towers[index] += rng.normal(0, config.mutation_scale * evaluator.problem.constraints.max_span_m, 2)
    elif action == 1 and len(towers) < upper:
        points = first.points(evaluator.problem.start, evaluator.problem.end)
        index = int(rng.integers(len(points) - 1))
        center = (points[index] + points[index + 1]) / 2
        center += rng.normal(0, config.mutation_scale * evaluator.problem.constraints.max_span_m, 2)
        towers = np.insert(towers, index, center, axis=0)
    elif action == 2 and len(towers) > lower:
        towers = np.delete(towers, int(rng.integers(len(towers))), axis=0)
    elif len(towers) and len(second.towers):
        left = int(rng.integers(len(towers) + 1))
        right = int(rng.integers(len(second.towers) + 1))
        towers = np.vstack([towers[:left], second.towers[right:]])
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
    return repair_towers(Route(towers), evaluator, config, rng)
