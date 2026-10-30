"""Backend-independent routing search result contract."""

from dataclasses import dataclass, field
import numpy as np
from modeling.routing.types import Route, RouteEvaluation

@dataclass
class RoutingResult:
    routes: list[Route]
    evaluations: list[RouteEvaluation]
    pareto_indices: list[int]
    evaluation_count: int
    lower: int
    initial_upper: int
    final_upper: int
    expansions: list[dict[str, int]]
    stop_reason: str
    generation_count: int
    initialization_evaluations: int
    execution: dict = field(default_factory=dict)
    evaluation_indices: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    evaluation_times_s: np.ndarray = field(default_factory=lambda: np.empty(0))
    published_indices: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluatedCandidate:
    route: Route
    evaluation: RouteEvaluation
