"""Compiled raster evaluation with exact Shapely polygon checks."""

import math

import numpy as np
from shapely.geometry import LineString, Point

from .clearance import center_distance
from .compiled_geometry import clearance_tower_flags, evaluate_route
from .evaluator import RouteEvaluator
from .geometry import DISTANCE_TOL_M
from .types import RouteEvaluation

VIOLATION_NAMES = ("invalid_geometry", "outside_tower_count", "blocked_tower_count", "invalid_dem_count",
                   "tower_overlap_m", "span_excess_m", "turn_excess_rad", "forbidden_crossing_count")


def violation_sum(values, radius, max_span):
    return (values[0] + values[1] + values[2] + values[3] + values[7]
            + values[4] / (2 * radius) + values[5] / max_span + values[6] / math.pi)


def total_violation(values, radius, max_span):
    return float(violation_sum(values, radius, max_span))


class CompiledRouteEvaluator(RouteEvaluator):
    def __init__(self, problem):
        super().__init__(problem)
        self._blocked_distance = self._missing_distance = None

    def _distance_fields(self):
        if self._blocked_distance is None:
            dem = np.asarray(self.problem.dem)
            blocked = np.asarray(self.problem.tower_blocked, dtype=bool)
            missing = ~np.isfinite(dem)
            self._dem, self._blocked = dem, blocked
            self._blocked_distance = center_distance(blocked) if blocked.any() else np.zeros(1, np.float32)
            self._missing_distance = center_distance(missing) if missing.any() else np.zeros(1, np.float32)
        return self._blocked_distance, self._missing_distance

    def tower_allowed(self, point):
        p = self.problem
        radius = p.constraints.tower_radius_m
        x, y = float(point[0]), float(point[1])
        blocked_distance, missing_distance = self._distance_fields()
        outside, hit, missing = clearance_tower_flags(
            blocked_distance, missing_distance, self._dem, self._blocked, x, y, radius)
        if outside or hit or missing:
            return False
        return not any(Point((x, y)).distance(zone) <= radius + DISTANCE_TOL_M for zone in p.no_tower_zones)

    def evaluate(self, route, *, report=False, details=True):
        if report:
            return super().evaluate(route, report=True)
        p, c = self.problem, self.problem.constraints
        points = route.points(p.start, p.end)
        objectives, values, elevations, spans, hits = evaluate_route(points, p.dem, p.tower_blocked,
            p.crossing_mask, c.tower_radius_m, c.max_span_m, math.radians(c.max_turn_deg))
        if p.no_tower_zones:
            for i, point in enumerate(route.towers):
                if not hits[i] and any(Point(point).distance(zone) <= c.tower_radius_m + DISTANCE_TOL_M for zone in p.no_tower_zones):
                    values[2] += 1
        if p.no_cross_zones:
            for start, end in zip(points[:-1], points[1:]):
                if (np.linalg.norm(end - start) > 0 and (start >= 0).all() and (end >= 0).all()
                        and (start <= [p.frame.width, p.frame.height]).all() and (end <= [p.frame.width, p.frame.height]).all()):
                    values[7] += any(LineString([start, end]).intersects(zone) for zone in p.no_cross_zones)
        return RouteEvaluation(objectives, dict(zip(VIOLATION_NAMES, values)),
            total_violation(values, c.tower_radius_m, c.max_span_m), elevations if details else np.empty(0),
            [dict(zip(("horizontal_m", "length_3d_m", "crossing_3d_m"), row)) for row in spans] if details else [], [])

    def evaluate_many(self, routes, *, details=True):
        return [self.evaluate(route, details=details) for route in routes]
