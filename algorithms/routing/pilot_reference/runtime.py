"""Per-run metric geometry, private streams and evaluated-candidate identities."""

from dataclasses import dataclass, field
import math

import numpy as np
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Point

from modeling.routing.geometry import DISTANCE_TOL_M
from modeling.routing.types import Route
from .adapter import PilotAdapter


@dataclass(frozen=True)
class Candidate:
    route: Route
    evaluation: object
    evaluation_index: int

    @property
    def key(self):
        return self.route.towers.tobytes()


def candidate_is_better(current, candidate, cfg, *, target=None, margin=0.):
    a, b = current.evaluation, candidate.evaluation
    if a.is_feasible != b.is_feasible:
        return b.is_feasible
    if not a.is_feasible:
        return b.violation < a.violation - cfg.cv_tolerance
    if target is not None and b.objectives[target] < a.objectives[target] - margin:
        if np.all(b.objectives <= a.objectives + cfg.weak_tolerance):
            return True
    return bool(np.all(b.objectives <= a.objectives + cfg.dominance_tolerance)
                and np.any(b.objectives < a.objectives - cfg.dominance_tolerance))


@dataclass
class RunState:
    adapter: PilotAdapter
    config: object
    budget: object
    report: object
    diagnostics: dict = field(default_factory=dict)
    candidates: dict = field(default_factory=dict)
    stagnation: dict = field(default_factory=dict)
    planner_paths: dict = field(default_factory=dict)
    _clearance: object = None

    @property
    def evaluator(self):
        return self.adapter.evaluator

    @property
    def problem(self):
        return self.adapter.problem

    @property
    def core(self):
        return self.config.pilot.core

    @property
    def scale(self):
        return self.problem.constraints.max_span_m / self.core.reference_max_step

    def count(self, name, amount=1):
        self.diagnostics[name] = self.diagnostics.get(name, 0) + amount

    def checkpoint(self, message="正在执行 PILOT CPU 搜索"):
        self.report("evolution", message)

    def remember(self):
        for index, (route, checked) in enumerate(self.budget.records):
            self.candidates[route.towers.tobytes()] = Candidate(route, checked, index)

    def score(self, route, window):
        checked = window.evaluate(route)
        if checked is None:
            return None
        candidate = Candidate(route, checked, len(self.budget.records) - 1)
        self.candidates[candidate.key] = candidate
        return candidate

    def lookup(self, route):
        candidate = self.candidates[route.towers.tobytes()]
        self.count("evaluation_reuses")
        return candidate

    def better(self, current, candidate, **kwargs):
        return candidate_is_better(current, candidate, self.core, **kwargs)

    def clearance(self, point):
        if self._clearance is None:
            blocked = self.problem.tower_blocked | ~np.isfinite(self.problem.dem)
            self._clearance = distance_transform_edt(~blocked).astype(np.float32) if blocked.any() else False
        x, y = point
        radius = self.problem.constraints.tower_radius_m
        margin = min(x, y, self.problem.frame.width - x, self.problem.frame.height - y) - radius
        if self._clearance is not False:
            row = int(np.clip(math.floor(y), 0, self.problem.frame.height - 1))
            col = int(np.clip(math.floor(x), 0, self.problem.frame.width - 1))
            margin = min(margin, float(self._clearance[row, col]) - radius)
        for zone in self.problem.no_tower_zones:
            margin = min(margin, Point(point).distance(zone) - radius)
        return max(0., margin)

    def neighborhood_radius(self, path, index):
        if len(path) <= 2:
            return self.scale * self.core.radius_empty
        clearance = self.clearance(path[index])
        return float(np.clip(self.scale * self.core.radius_base + self.core.radius_clearance_factor * clearance,
                             self.scale * self.core.radius_min, self.scale * self.core.radius_max))

    def project(self, point, radius, *, prefer_clearance=0.):
        point = np.asarray(point, dtype=float)
        if self.adapter.tower_allowed(point):
            return point.copy()
        best, best_key = None, None
        for ring in range(1, max(1, math.ceil(radius / self.scale)) + 1):
            self.checkpoint()
            for dy in range(-ring, ring + 1):
                for dx in range(-ring, ring + 1):
                    candidate = point + self.scale * np.array([dx, dy])
                    if not self.adapter.tower_allowed(candidate):
                        continue
                    distance2 = float(dx * dx + dy * dy)
                    clearance = self.clearance(candidate) / self.scale
                    key = ((1 - prefer_clearance) * distance2 - prefer_clearance * 2 * clearance,
                           distance2, -clearance)
                    if best_key is None or key < best_key:
                        best, best_key = candidate, key
            if best is not None:
                return best
        return point.copy()

    def sanitize(self, path):
        points = np.asarray(path, dtype=float).copy()
        if points.ndim != 2 or points.shape[1:] != (2,) or len(points) < 2:
            raise ValueError("PILOT path requires [N, 2] endpoints and waypoints")
        if not np.array_equal(points[[0, -1]], [self.problem.start, self.problem.end]):
            raise ValueError("PILOT operator changed fixed endpoints")
        for index in range(1, len(points) - 1):
            points[index] = self.project(points[index], self.scale * self.core.sanitize_radius)
        return points[np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > DISTANCE_TOL_M]]

    def valid_path(self, path):
        if len(path) < 2:
            return False
        return all(self.adapter.extension_allowed(path[:index], target, fixed_endpoint=index == len(path) - 1)
                   for index, target in enumerate(path[1:], 1))
