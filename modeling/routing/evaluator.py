"""One source of routing objectives, feasibility and final diagnostics."""

from __future__ import annotations

import math
import numpy as np
import torch
from shapely.geometry import LineString, Point

from .context import RoutingProblem
from .geometry import DISTANCE_TOL_M, circle_cells, footprint_slope, mask_intersection_length, sample_dem, turn_angles
from .types import Route, RouteEvaluation


class RouteEvaluator:
    def __init__(self, problem: RoutingProblem):
        self.problem = problem
        if not np.isfinite(sample_dem(problem.dem, np.vstack([problem.start, problem.end]))).all():
            raise ValueError("fixed connection points require valid DEM elevations")

    def tower_check(self, point: np.ndarray):
        problem, radius = self.problem, self.problem.constraints.tower_radius_m
        rows, cols = circle_cells(point, radius, problem.dem.shape)
        outside = not (radius <= point[0] <= problem.frame.width - radius and radius <= point[1] <= problem.frame.height - radius)
        blocked = bool(problem.tower_blocked[rows, cols].any())
        blocked |= any(Point(point).distance(zone) <= radius + DISTANCE_TOL_M for zone in problem.no_tower_zones)
        missing = not np.isfinite(sample_dem(problem.dem, np.asarray(point).reshape(1, 2))).all()
        missing |= not np.isfinite(problem.dem[rows, cols]).all()
        return rows, cols, outside, blocked, missing

    def tower_allowed(self, point: np.ndarray) -> bool:
        return not any(self.tower_check(point)[2:])

    def evaluate(self, route: Route, *, report: bool = False) -> RouteEvaluation:
        problem, towers = self.problem, route.towers
        constraints = problem.constraints
        radius = constraints.tower_radius_m
        points = route.points(problem.start, problem.end)
        lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
        violations = {
            "invalid_geometry": float(np.count_nonzero(lengths == 0)),
            "outside_tower_count": 0.0,
            "blocked_tower_count": 0.0, "invalid_dem_count": 0.0,
            "tower_overlap_m": 0.0, "span_excess_m": 0.0, "turn_excess_rad": 0.0,
            "forbidden_crossing_count": 0.0,
        }
        elevations = sample_dem(problem.dem, points)
        violations["invalid_dem_count"] = float(np.count_nonzero(~np.isfinite(elevations[[0, -1]])))
        slopes = []
        for point in towers:
            rows, cols, outside, blocked, missing = self.tower_check(point)
            violations["outside_tower_count"] += int(outside)
            violations["blocked_tower_count"] += int(blocked)
            violations["invalid_dem_count"] += int(missing)
            if report:
                slopes.append(footprint_slope(problem.dem, rows, cols))
        if len(towers) > 1:
            left, right = np.triu_indices(len(towers), 1)
            overlap = 2 * radius - np.linalg.norm(towers[left] - towers[right], axis=1)
            violations["tower_overlap_m"] = float(overlap[overlap > DISTANCE_TOL_M].sum())
        excess = lengths - constraints.max_span_m
        violations["span_excess_m"] = float(excess[excess > DISTANCE_TOL_M].sum())
        angles = turn_angles(points)
        angle_excess = angles - math.radians(constraints.max_turn_deg)
        violations["turn_excess_rad"] = float(angle_excess[angle_excess > 1e-12].sum())
        spatial = np.hypot(lengths, np.diff(elevations))
        spans, crossing = [], 0.0
        # Outside points are invalid before crossing traversal; do not allocate an unbounded walk.
        within = ((points >= 0).all(axis=1) & (points[:, 0] <= problem.frame.width) & (points[:, 1] <= problem.frame.height))
        for index, (start, end) in enumerate(zip(points[:-1], points[1:])):
            amount = 0.0
            if lengths[index] > 0 and within[index:index + 2].all():
                horizontal = mask_intersection_length(start, end, problem.crossing_mask)
                amount = float(spatial[index] * horizontal / lengths[index])
                segment = LineString([start, end])
                violations["forbidden_crossing_count"] += int(any(segment.intersects(zone) for zone in problem.no_cross_zones))
            crossing += amount
            spans.append({"horizontal_m": float(lengths[index]), "length_3d_m": float(spatial[index]), "crossing_3d_m": amount})
        violation = sum(value for key, value in violations.items() if key not in {"tower_overlap_m", "span_excess_m", "turn_excess_rad"})
        violation += violations["tower_overlap_m"] / (2 * radius) + violations["span_excess_m"] / constraints.max_span_m + violations["turn_excess_rad"] / math.pi
        objectives = np.array([len(towers), spatial.sum(), angles.sum(), crossing], dtype=float)
        objectives[~np.isfinite(objectives)] = math.inf
        return RouteEvaluation(objectives, violations, float(violation), elevations, spans, slopes)

    def batch(self, routes: list[Route]) -> tuple[torch.Tensor, torch.Tensor]:
        evaluations = [self.evaluate(route) for route in routes]
        return (torch.as_tensor(np.array([item.objectives for item in evaluations]).reshape(-1, 4)),
                torch.tensor([item.violation for item in evaluations], dtype=torch.float64))

    def padded_batch(self, towers: torch.Tensor, counts: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if towers.ndim != 3 or towers.shape[2] != 2 or counts.shape != (len(towers),):
            raise ValueError("expected towers [B, K, 2] and counts [B]")
        if counts.dtype not in (torch.int32, torch.int64) or torch.any(counts < 0) or torch.any(counts > towers.shape[1]):
            raise ValueError("tower counts must be integers within [0, K]")
        return self.batch([Route(row[:int(count)].detach().cpu().numpy()) for row, count in zip(towers, counts)])
