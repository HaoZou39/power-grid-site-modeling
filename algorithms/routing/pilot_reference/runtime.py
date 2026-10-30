"""Per-run metric geometry, private streams and evaluated-candidate identities."""

from dataclasses import dataclass, field
import math

import numpy as np
from shapely.geometry import Point

from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
from modeling.routing.compiled_geometry import project_clearance_points
from modeling.routing.context import tower_clearance
from modeling.routing.geometry import DISTANCE_TOL_M
from modeling.routing.types import Route
from .adapter import PilotAdapter


def dedup_path(points):
    points = np.asarray(points, dtype=float)
    return points[np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > DISTANCE_TOL_M]]


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
    origins: dict = field(default_factory=dict)
    stagnation: dict = field(default_factory=dict)
    planner_paths: dict = field(default_factory=dict)
    planner_seed_bank: dict = field(default_factory=lambda: {False: [], True: []})
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

    def store_planner_seed(self, path, *, corridor):
        self.planner_seed_bank[bool(corridor)].append(np.asarray(path, dtype=float).copy())

    def take_planner_seed(self, *, corridor):
        bank = self.planner_seed_bank[bool(corridor)]
        if not bank:
            self.count("planner_seed_bank_misses")
            return None
        self.count("planner_seed_bank_hits")
        return bank.pop(0).copy()

    def checkpoint(self, message="正在执行 PILOT CPU 搜索"):
        self.report("evolution", message)

    def remember(self):
        for index, (route, checked) in enumerate(self.budget.records):
            self.candidates[route.towers.tobytes()] = Candidate(route, checked, index)
            self.origins[route.towers.tobytes()] = "reference"

    def score(self, route, window):
        checked = window.evaluate(route)
        if checked is None:
            return None
        candidate = Candidate(route, checked, len(self.budget.records) - 1)
        self.candidates[candidate.key] = candidate
        self.origins[candidate.key] = window.source
        return candidate

    def mark(self, candidate, origin):
        self.origins[candidate.key] = origin

    def lookup(self, route):
        candidate = self.candidates[route.towers.tobytes()]
        self.count("evaluation_reuses")
        return candidate

    def better(self, current, candidate, **kwargs):
        return candidate_is_better(current, candidate, self.core, **kwargs)

    def clearance(self, point):
        if self._clearance is None:
            field = tower_clearance(self.problem)
            self._clearance = False if field is None else field
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
        return self.project_many(np.asarray(point, dtype=float).reshape(1, 2), radius,
                                 prefer_clearance=prefer_clearance)[0]

    def project_many(self, points, radius, *, prefer_clearance=0.):
        """project() of every row in [N, 2]; compiled unless Shapely no-tower polygons are present."""
        points = np.asarray(points, dtype=float).reshape(-1, 2)
        evaluator = self.evaluator
        if type(evaluator) is not CompiledRouteEvaluator or self.problem.no_tower_zones:
            return np.array([self._project(p, radius, prefer_clearance) for p in points]).reshape(-1, 2)
        if self._clearance is None:
            field = tower_clearance(self.problem)
            self._clearance = False if field is None else field
        ring = max(1, math.ceil(radius / self.scale))
        blocked_distance, missing_distance = evaluator._distance_fields()
        xs, ys, found = project_clearance_points(
            np.ascontiguousarray(points[:, 0]), np.ascontiguousarray(points[:, 1]), np.full(len(points), ring, np.int64),
            blocked_distance, missing_distance, evaluator._dem, evaluator._blocked,
            np.zeros(1) if self._clearance is False else self._clearance, float(self.scale),
            float(self.problem.constraints.tower_radius_m), float(prefer_clearance),
            float(self.problem.frame.width), float(self.problem.frame.height))
        # _project 先查原点，再把第 1..k 环的整个 (2r+1)² 方块逐格查一遍，k 为胜出环或最大环。
        walked = np.minimum(found, ring)
        self.adapter.node_checks += int(len(points) + ((walked + 1) * (2 * walked + 1) * (2 * walked + 3) // 3 - 1).sum())
        return np.column_stack([xs, ys])

    def _project(self, point, radius, prefer_clearance):
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
        return dedup_path(points)

    def valid_path(self, path):
        if len(path) < 2:
            return False
        return all(self.adapter.extension_allowed(path[:index], target, fixed_endpoint=index == len(path) - 1)
                   for index, target in enumerate(path[1:], 1))
