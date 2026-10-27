"""Boundary between original path operators and the current metric route model."""

import json
from pathlib import Path
import random

import numpy as np

from modeling.routing.types import Route


def source_identity():
    return json.loads(Path(__file__).with_name("provenance.json").read_text())


class PilotAdapter:
    def __init__(self, evaluator, seed):
        self.evaluator, self.problem = evaluator, evaluator.problem
        self.python_rng = random.Random(seed)
        self.numpy_rng = np.random.RandomState(seed)
        self.node_checks = self.edge_checks = 0

    def path(self, route):
        return route.points(self.problem.start, self.problem.end)

    def route(self, path):
        path = np.asarray(path, dtype=float)
        if path.ndim != 2 or path.shape[1] != 2 or len(path) < 2:
            raise ValueError("PILOT path must contain start and end in [N, 2]")
        if not np.array_equal(path[[0, -1]], np.vstack([self.problem.start, self.problem.end])):
            raise ValueError("PILOT path changed fixed endpoints")
        return Route(path[1:-1])

    def tower_allowed(self, point):
        self.node_checks += 1
        return self.evaluator.tower_allowed(np.asarray(point, dtype=float))

    def extension_allowed(self, path, target, *, fixed_endpoint=False):
        self.edge_checks += 1
        return self.evaluator.extension_allowed(path, target, fixed_endpoint=fixed_endpoint)
