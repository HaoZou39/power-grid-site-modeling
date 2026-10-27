"""Shared 1 m road occupancy and setback geometry for siting and routing."""

from __future__ import annotations
import math
import numpy as np
from scipy.ndimage import distance_transform_edt

ROAD_LANDUSE_CLASS = 3


def _road_cells(segments: np.ndarray, shape: tuple[int, int], *, require_crossing: bool = True) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    height, width = shape
    for x1, y1, x2, y2 in segments:
        length = math.hypot(float(x2 - x1), float(y2 - y1))
        steps = max(1, int(math.ceil(length / 0.25)))
        for index in range(steps + 1):
            weight = index / steps
            cell = _cell((x1 + (x2 - x1) * weight, y1 + (y2 - y1) * weight), shape, require_inside=False)
            if cell is not None and 0 <= cell[0] < height and 0 <= cell[1] < width:
                cells.add(cell)
    if not cells and require_crossing:
        raise ValueError("road does not cross the grid")
    return cells


def rasterize_road_mask(segments: np.ndarray, shape: tuple[int, int], *, allow_empty: bool = False) -> np.ndarray:
    """Rasterize OSM centerlines with the same cells used by haul-field gates."""

    mask = np.zeros(shape, dtype=bool)
    for row, col in _road_cells(segments, shape, require_crossing=not allow_empty):
        mask[row, col] = True
    return mask


def _cell(
    point: tuple[float, float],
    shape: tuple[int, int],
    *,
    require_inside: bool = True,
) -> tuple[int, int] | None:
    row = int(math.floor(point[1]))
    col = int(math.floor(point[0]))
    height, width = shape
    if 0 <= row < height and 0 <= col < width:
        return row, col
    if require_inside:
        raise ValueError("point is outside the grid")
    return None


def require_road_setback_m(value: object) -> float:
    """Finite, non-negative building setback in metres. Zero keeps the road cells only."""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("road_setback_m must be a finite, non-negative number") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError("road_setback_m must be a finite, non-negative number")
    return number


def rasterize_osm_centerlines(segments: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """OSM centerline cells. An empty segment array is an empty mask, not a skipped constraint."""

    if np.asarray(segments).size == 0:
        return np.zeros(shape, dtype=bool)

    return rasterize_road_mask(segments, shape, allow_empty=True)


def road_setback_source(
    landuse: np.ndarray,
    osm_road_mask: np.ndarray,
) -> np.ndarray | None:
    """Class 3 or an OSM centerline. ``None`` when that union is empty."""

    landuse_grid = np.asarray(landuse)
    osm_grid = np.asarray(osm_road_mask, dtype=bool)
    if landuse_grid.ndim != 2 or osm_grid.shape != landuse_grid.shape:
        raise ValueError(
            "road setback arrays must share a 2D shape, "
            f"got landuse {landuse_grid.shape} and osm {osm_grid.shape}"
        )
    road = np.logical_or(landuse_grid == ROAD_LANDUSE_CLASS, osm_grid)
    if not road.any():
        return None
    return road


def road_setback_distance(
    landuse: np.ndarray,
    osm_road_mask: np.ndarray,
) -> np.ndarray | None:
    """Distance to class 3 or an OSM centerline. ``None`` when that union is empty."""

    road = road_setback_source(landuse, osm_road_mask)
    if road is None:
        return None
    return distance_transform_edt(~road, sampling=(1.0, 1.0))


def mask_within_distance(
    distance: np.ndarray | None,
    setback_m: float,
    shape: tuple[int, int],
) -> np.ndarray:
    """``<= setback`` on a 1 m EDT. An empty source keeps every cell out of the buffer."""

    if distance is None:
        return np.zeros(shape, dtype=bool)
    return distance <= setback_m


def road_building_buffer(
    landuse: np.ndarray,
    osm_road_mask: np.ndarray,
    road_setback_m: float,
) -> np.ndarray:
    """Cells within the 1 m distance transform of satellite class 3 or an OSM centerline.

    ``distance_transform_edt`` measures distance to the nearest road cell, so a road cell
    is 0 and an orthogonal neighbour is 1. ``<= road_setback_m`` is a grid approximation,
    not a continuous geometric clearance. Zero still forbids the road cells themselves.
    """

    setback = require_road_setback_m(road_setback_m)
    distance = road_setback_distance(landuse, osm_road_mask)
    return mask_within_distance(distance, setback, np.asarray(landuse).shape)


def highway_building_buffer(segments: np.ndarray, kinds: np.ndarray, shape: tuple[int, int], setback_m: float) -> np.ndarray:
    setback = require_road_setback_m(setback_m)
    padding = int(math.ceil(setback))
    highway = np.asarray(segments)[np.isin(np.asarray(kinds), [1, 2])]
    if not len(highway):
        return np.zeros(shape, dtype=bool)
    # Outside centreline cells can still impose a setback inside the scene.
    shifted = highway + np.asarray([padding, padding, padding, padding])
    expanded = (shape[0] + 2 * padding, shape[1] + 2 * padding)
    source = rasterize_osm_centerlines(shifted, expanded)
    if not source.any():
        return np.zeros(shape, dtype=bool)
    buffer = distance_transform_edt(~source, sampling=(1.0, 1.0)) <= setback
    return buffer[padding:padding + shape[0], padding:padding + shape[1]].copy()
