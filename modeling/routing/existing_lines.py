"""Task-level existing power lines. The shared scene rasters stay unchanged."""

import math

import numpy as np
from shapely.geometry import LineString, Point

from .clearance import center_distance, zone_mask
from .geometry import DISTANCE_TOL_M, mask_intersection_length

# A 1 m cell that the centerline touches can put the true line this far from that cell center.
CENTERLINE_RASTER_SLACK_M = math.sqrt(2) / 2


def existing_line_buffer_m(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("existing_line_crossing_buffer_m must be a finite number >= 0")
    return float(value)


def _coordinates(record):
    points = record.points if hasattr(record, "points") else record["points"]
    return np.asarray(points, dtype=np.float64)


def existing_lines(records, frame) -> tuple[LineString, ...]:
    """Open polylines in the scene's local metre frame. An empty list is unchanged."""
    lines = []
    seen = set()
    for record in records:
        identity = record.id if hasattr(record, "id") else record["id"]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("existing power line ids must be non-empty and unique")
        seen.add(identity)
        points = _coordinates(record)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
            raise ValueError("existing power line requires at least two finite vertices")
        if np.any(np.linalg.norm(np.diff(points, axis=0), axis=1) <= 0):
            raise ValueError("existing power line has a zero-length segment")
        for point in points:
            try:
                frame.validate_point(point)
            except ValueError as exc:
                raise ValueError("existing power line is outside the scene") from exc
        lines.append(LineString(points))
    return tuple(lines)


def tower_hits_existing_line(point, problem) -> bool:
    """True when the tower center is within the task tower radius of a centerline."""
    if not problem.existing_lines:
        return False
    radius = problem.constraints.tower_radius_m + DISTANCE_TOL_M
    location = Point(np.asarray(point, dtype=float))
    return any(location.distance(line) <= radius for line in problem.existing_lines)


def overlay_existing_lines(problem, records, buffer_m):
    """Copy the crossing mask and OR in this task's buffer. Base rasters are not written."""
    from dataclasses import replace

    width = existing_line_buffer_m(buffer_m)
    lines = existing_lines(records, problem.frame)
    if not lines:
        if not problem.existing_lines and problem.existing_line_buffer_m == width:
            return problem
        return replace(problem, existing_lines=(), existing_line_mask=None,
                       existing_line_distance=None, existing_line_buffer_m=width)
    shape = problem.dem.shape
    center = zone_mask(lines, shape)
    distance = None if not center.any() else readonly_distance(center)
    if width == 0:
        band = None
        crossing = problem.crossing_mask
    else:
        burned = zone_mask([line.buffer(width) for line in lines], shape)
        if burned.any():
            crossing = np.array(problem.crossing_mask, copy=True)
            crossing |= burned
            crossing.flags.writeable = False
            burned.flags.writeable = False
            band = burned
        else:
            band = None
            crossing = problem.crossing_mask
    return replace(problem, crossing_mask=crossing, existing_lines=lines, existing_line_mask=band,
                   existing_line_distance=distance, existing_line_buffer_m=width)


def readonly_distance(mask):
    field = center_distance(mask)
    field.flags.writeable = False
    return field


def _marks(geometry, found):
    if geometry.is_empty:
        return
    kind = geometry.geom_type
    if kind == "Point":
        found.append({"x": float(geometry.x), "y": float(geometry.y)})
    elif kind == "LineString":
        # One collinear overlap is one crossing, marked at its midpoint.
        middle = geometry.interpolate(0.5, normalized=True)
        found.append({"x": float(middle.x), "y": float(middle.y)})
    elif kind in {"MultiPoint", "MultiLineString", "GeometryCollection"}:
        for part in geometry.geoms:
            _marks(part, found)


def existing_line_report(problem, points, elevations) -> dict:
    """Report-only buffer length and deduplicated planar crossings. Both are 0 without lines."""
    points = np.asarray(points, dtype=float)
    if not problem.existing_lines:
        return {"existing_line_crossing_length_m": 0.0, "existing_line_crossing_count": 0,
                "existing_line_crossings": []}
    elevations = np.asarray(elevations, dtype=float)
    length = 0.0
    mask = problem.existing_line_mask
    if mask is not None and len(elevations) == len(points):
        within = ((points >= 0).all(axis=1) & (points[:, 0] <= problem.frame.width)
                  & (points[:, 1] <= problem.frame.height))
        for index, (start, end) in enumerate(zip(points[:-1], points[1:])):
            horizontal = float(np.linalg.norm(end - start))
            z0, z1 = elevations[index], elevations[index + 1]
            if horizontal <= 0 or not within[index:index + 2].all() or not np.isfinite([z0, z1]).all():
                continue
            planar = mask_intersection_length(start, end, mask)
            length += math.hypot(horizontal, float(z1 - z0)) * planar / horizontal
    found = []
    route = LineString(points)
    for line in problem.existing_lines:
        _marks(route.intersection(line), found)
    return {"existing_line_crossing_length_m": float(length), "existing_line_crossing_count": len(found),
            "existing_line_crossings": found}
