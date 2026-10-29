"""Read-only routing context assembled from prepared metric products."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from shapely.geometry import Polygon

from modeling.road_control import highway_building_buffer, rasterize_osm_centerlines, road_building_buffer
from .clearance import center_distance
from .types import RoutingConstraints, RoutingFrame


def readonly(array: np.ndarray) -> np.ndarray:
    view = np.asarray(array).view()
    view.flags.writeable = False
    return view


def mask_distance(mask: np.ndarray) -> np.ndarray | None:
    return readonly(center_distance(mask)) if mask.any() else None


def tower_clearance(problem: RoutingProblem) -> np.ndarray | None:
    """Distance to the nearest cell that is tower-blocked or lacks DEM; None when neither exists."""
    fields = [field for field in (problem.blocked_distance, problem.missing_distance) if field is not None]
    return fields[0] if len(fields) == 1 else (np.minimum(*fields) if fields else None)


def polygons(rings: Sequence) -> tuple[Polygon, ...]:
    result = []
    for ring in rings:
        points = np.asarray(ring, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
            raise ValueError("region must contain at least three finite [x, y] points")
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError("region must be a valid polygon with positive area")
        result.append(polygon)
    return tuple(result)


@dataclass(frozen=True)
class RoutingProblem:
    dem: np.ndarray
    landuse: np.ndarray
    road_control: np.ndarray
    tower_blocked: np.ndarray
    crossing_mask: np.ndarray
    # 像元中心到最近不可立塔 / 缺高程像元中心的距离（格），float32；掩膜为空时为 None。
    blocked_distance: np.ndarray | None
    missing_distance: np.ndarray | None
    start: np.ndarray
    end: np.ndarray
    frame: RoutingFrame
    constraints: RoutingConstraints
    no_tower_zones: tuple[Polygon, ...]
    no_cross_zones: tuple[Polygon, ...]


def build_routing_problem(
    dem: np.ndarray,
    landuse: np.ndarray,
    road_segments: np.ndarray,
    road_kinds: np.ndarray,
    protected_farmland: np.ndarray | None,
    start: Sequence[float],
    end: Sequence[float],
    frame: RoutingFrame,
    constraints: RoutingConstraints,
    *,
    no_tower_zones: Sequence = (),
    no_cross_zones: Sequence = (),
) -> RoutingProblem:
    shape = (frame.height, frame.width)
    if dem.shape != shape or landuse.shape != shape:
        raise ValueError("DEM, landuse and routing frame must share one 1 m shape")
    if not np.issubdtype(dem.dtype, np.number) or np.iscomplexobj(dem):
        raise ValueError("DEM must be a real numeric matrix")
    if not np.issubdtype(landuse.dtype, np.integer) or landuse.min() < 0 or landuse.max() > 5:
        raise ValueError("landuse must contain integer class IDs 0 through 5")
    segments, kinds = np.asarray(road_segments), np.asarray(road_kinds)
    if segments.ndim != 2 or segments.shape[1] != 4 or not np.isfinite(segments).all():
        raise ValueError("road_segments must be finite [S, 4]")
    if kinds.shape != (len(segments),) or not np.issubdtype(kinds.dtype, np.integer) or not np.isin(kinds, [0, 1, 2, 3]).all():
        raise ValueError("road kinds must be one integer 0..3 for each segment")
    if protected_farmland is None:
        farmland = np.zeros(shape, dtype=bool)
    else:
        farmland = np.asarray(protected_farmland)
        if farmland.shape != shape or farmland.dtype != np.bool_:
            raise ValueError("protected farmland must be a boolean matrix matching DEM")
    start_point, end_point = frame.validate_point(start), frame.validate_point(end)
    if np.array_equal(start_point, end_point):
        raise ValueError("start and end connection points must be different")
    road = road_building_buffer(landuse, rasterize_osm_centerlines(segments[kinds == 0], shape), constraints.road_setback_m)
    road |= highway_building_buffer(segments, kinds, shape, constraints.highway_setback_m)
    crossing = (landuse == 2) | (landuse == 5) | road
    blocked = crossing | farmland
    return RoutingProblem(
        readonly(dem), readonly(landuse), readonly(road), readonly(blocked), readonly(crossing),
        mask_distance(blocked), mask_distance(~np.isfinite(dem)),
        readonly(start_point.copy()), readonly(end_point.copy()), frame, constraints,
        polygons(no_tower_zones), polygons(no_cross_zones),
    )
