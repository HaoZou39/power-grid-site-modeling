"""Tower-count bounds and their existing expansion schedule."""

from dataclasses import dataclass
import math
import numpy as np
from config.project_config import RoutingConfig
from modeling.routing.context import RoutingProblem
from modeling.routing.geometry import DISTANCE_TOL_M

def minimum_towers(problem: RoutingProblem) -> int:
    ratio = np.linalg.norm(problem.end - problem.start) / (problem.constraints.max_span_m + DISTANCE_TOL_M)
    return max(0, math.ceil(np.nextafter(ratio, -math.inf)) - 1)

@dataclass
class TowerRange:
    lower: int
    initial_upper: int
    upper: int
    probe_upper: int | None = None

    def expand(self, generation: int, config: RoutingConfig) -> bool:
        if generation < 1 or generation % config.expansion_interval:
            return False
        if self.probe_upper is None:
            self.upper += config.expansion_step
        else:
            self.probe_upper += config.expansion_step
            self.upper = max(self.upper, self.probe_upper)
        return True
