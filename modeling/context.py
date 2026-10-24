"""一次搜索共用的数据包。

`SiteProblemContext` 只保存已经对齐的 1 m 数组和张量。它不是目标或约束的父类。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import torch
from scipy.ndimage import distance_transform_edt

ROAD_LANDUSE_CLASS = 3
WATER_LANDUSE_CLASS = 5
DEFAULT_ROAD_SETBACK_M = 5.0
DEFAULT_WATER_SETBACK_M = 5.0


@dataclass(frozen=True)
class SiteProblemContext:
    """Prepared 1 m data and tensors shared by all search algorithms."""

    dem: np.ndarray
    obstacle_mask: np.ndarray
    road_segments: np.ndarray
    dem_tensor: torch.Tensor
    obstacle_tensor: torch.Tensor
    road_segments_tensor: torch.Tensor
    road_voronoi_tensor: torch.Tensor
    demand_points: np.ndarray
    demand_weights: np.ndarray | None
    demand_points_tensor: torch.Tensor
    demand_weights_tensor: torch.Tensor | None
    device: torch.device
    obstacle_soft_mask: np.ndarray | None = None
    obstacle_soft_tensor: torch.Tensor | None = None
    osm_road_mask: np.ndarray | None = None
    building_obstacle_mask: np.ndarray | None = None
    landuse: np.ndarray | None = None
    road_setback_m: float = DEFAULT_ROAD_SETBACK_M
    road_buffer: np.ndarray | None = None
    water_setback_m: float = DEFAULT_WATER_SETBACK_M
    water_buffer: np.ndarray | None = None
    initialization_feasible_zones: tuple[tuple[tuple[float, float], ...], ...] = ()
    initialization_exclusion_zones: tuple[tuple[tuple[float, float], ...], ...] = ()
    # Dilated permanent-farmland cells. None means this scene has no farmland file.
    access_connector_blocked: np.ndarray | None = None


def soft_obstacle_tensor(context: SiteProblemContext) -> torch.Tensor:
    """Soft-cost mask. Missing means the hard mask, which is the default policy."""

    if context.obstacle_soft_tensor is None:
        return context.obstacle_tensor
    return context.obstacle_soft_tensor


def require_road_setback_m(value: object) -> float:
    """Finite, non-negative building setback in metres. Zero keeps the road cells only."""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("road_setback_m must be a finite, non-negative number") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError("road_setback_m must be a finite, non-negative number")
    return number


def require_water_setback_m(value: object) -> float:
    """Finite, non-negative building setback around class 5. Zero keeps the water cells only."""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("water_setback_m must be a finite, non-negative number") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError("water_setback_m must be a finite, non-negative number")
    return number


def rasterize_osm_centerlines(segments: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """OSM centerline cells. An empty segment array is an empty mask, not a skipped constraint."""

    if np.asarray(segments).size == 0:
        return np.zeros(shape, dtype=bool)
    from modeling.construction_cost import rasterize_road_mask

    return rasterize_road_mask(segments, shape)


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
    landuse_grid = np.asarray(landuse)
    osm_grid = np.asarray(osm_road_mask, dtype=bool)
    if landuse_grid.ndim != 2 or osm_grid.shape != landuse_grid.shape:
        raise ValueError(
            "road setback arrays must share a 2D shape, "
            f"got landuse {landuse_grid.shape} and osm {osm_grid.shape}"
        )
    road = np.logical_or(landuse_grid == ROAD_LANDUSE_CLASS, osm_grid)
    if not road.any():
        return np.zeros(landuse_grid.shape, dtype=bool)
    distance = distance_transform_edt(~road, sampling=(1.0, 1.0))
    return distance <= setback


def water_building_buffer(landuse: np.ndarray, water_setback_m: float) -> np.ndarray:
    """Cells within the 1 m distance transform of land-use class 5.

    Official and remote-sensing water are already the same class. Zero still forbids
    those cells. The buffer is only for the building footprint, not the haul mask.
    """

    setback = require_water_setback_m(water_setback_m)
    grid = np.asarray(landuse)
    if grid.ndim != 2:
        raise ValueError(f"water setback landuse must be 2D, got {grid.shape}")
    water = grid == WATER_LANDUSE_CLASS
    if not water.any():
        return np.zeros(grid.shape, dtype=bool)
    distance = distance_transform_edt(~water, sampling=(1.0, 1.0))
    return distance <= setback


def merge_building_hard_mask(
    obstacle_mask: np.ndarray,
    road_buffer: np.ndarray,
    water_buffer: np.ndarray,
) -> np.ndarray:
    """Land hard cells plus the two building-only setbacks. This is not a haul mask."""

    road = np.asarray(road_buffer, dtype=bool)
    water = np.asarray(water_buffer, dtype=bool)
    obstacle = np.asarray(obstacle_mask)
    if obstacle.shape != road.shape or water.shape != road.shape:
        raise ValueError(
            "building hard-mask arrays must share one shape, "
            f"got obstacle {obstacle.shape}, road {road.shape}, water {water.shape}"
        )
    return np.logical_or(np.logical_or(obstacle > 0, road), water).astype(np.float32)


def compose_building_hard_mask(
    obstacle_mask: np.ndarray,
    landuse: np.ndarray,
    osm_road_mask: np.ndarray,
    road_setback_m: float,
    water_setback_m: float = DEFAULT_WATER_SETBACK_M,
) -> np.ndarray:
    """Land hard cells plus road and water setbacks. This mask is not a haul mask."""

    return merge_building_hard_mask(
        obstacle_mask,
        road_building_buffer(landuse, osm_road_mask, road_setback_m),
        water_building_buffer(landuse, water_setback_m),
    )


def building_hard_mask(context: SiteProblemContext) -> np.ndarray:
    """Prepared building mask. Haul paths continue to use ``obstacle_mask``."""

    if context.building_obstacle_mask is not None:
        return context.building_obstacle_mask
    landuse = context.landuse
    if landuse is None:
        landuse = np.zeros(context.dem.shape, dtype=np.int16)
    osm = context.osm_road_mask
    if osm is None:
        osm = rasterize_osm_centerlines(context.road_segments, context.dem.shape)
    return compose_building_hard_mask(
        context.obstacle_mask,
        landuse,
        osm,
        context.road_setback_m,
        context.water_setback_m,
    )
