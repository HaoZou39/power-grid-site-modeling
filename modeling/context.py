"""一次搜索共用的数据包。

`SiteProblemContext` 只保存已经对齐的 1 m 数组和张量。它不是目标或约束的父类。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import torch
from scipy.ndimage import distance_transform_edt

from config.project_config import load_default_config
from modeling.road_control import (
    ROAD_LANDUSE_CLASS, highway_building_buffer, mask_within_distance,
    rasterize_osm_centerlines, require_road_setback_m, road_building_buffer,
    road_setback_distance, road_setback_source,
)

WATER_LANDUSE_CLASS = 5
DEFAULT_ROAD_SETBACK_M = load_default_config().modeling.road_setback_m
DEFAULT_WATER_SETBACK_M = load_default_config().modeling.water_setback_m


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
    road_segment_kinds: np.ndarray | None = None
    highway_buffer: np.ndarray | None = None
    obstacle_soft_mask: np.ndarray | None = None
    obstacle_soft_tensor: torch.Tensor | None = None
    building_soft_tensor: torch.Tensor | None = None
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
    # Cells outside the true-north study domain. Building-only, like the setbacks.
    study_outside: np.ndarray | None = None


def soft_obstacle_tensor(context: SiteProblemContext) -> torch.Tensor:
    """Prepared building costs, including setbacks, independent of haul walkability."""

    if context.building_soft_tensor is not None:
        return context.building_soft_tensor

    if context.obstacle_soft_tensor is None:
        return context.obstacle_tensor
    return context.obstacle_soft_tensor


def require_water_setback_m(value: object) -> float:
    """Finite, non-negative building setback around class 5. Zero keeps the water cells only."""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("water_setback_m must be a finite, non-negative number") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError("water_setback_m must be a finite, non-negative number")
    return number


def water_setback_source(landuse: np.ndarray) -> np.ndarray | None:
    """Land-use class 5. ``None`` when the grid has no water."""

    grid = np.asarray(landuse)
    if grid.ndim != 2:
        raise ValueError(f"water setback landuse must be 2D, got {grid.shape}")
    water = grid == WATER_LANDUSE_CLASS
    if not water.any():
        return None
    return water


def water_setback_distance(landuse: np.ndarray) -> np.ndarray | None:
    """Distance to land-use class 5. ``None`` when the grid has no water."""

    water = water_setback_source(landuse)
    if water is None:
        return None
    return distance_transform_edt(~water, sampling=(1.0, 1.0))


def water_building_buffer(landuse: np.ndarray, water_setback_m: float) -> np.ndarray:
    """Cells within the 1 m distance transform of land-use class 5.

    Official and remote-sensing water are already the same class. Zero still forbids
    those cells. The buffer is only for the building footprint, not the haul mask.
    """

    setback = require_water_setback_m(water_setback_m)
    distance = water_setback_distance(landuse)
    return mask_within_distance(distance, setback, np.asarray(landuse).shape)


def merge_building_hard_mask(
    obstacle_mask: np.ndarray,
    road_buffer: np.ndarray,
    water_buffer: np.ndarray,
    highway_buffer: np.ndarray | None = None,
    study_outside: np.ndarray | None = None,
) -> np.ndarray:
    """Land hard cells plus the building-only setbacks and study-domain edge. This is not a haul mask."""

    road = np.asarray(road_buffer, dtype=bool)
    water = np.asarray(water_buffer, dtype=bool)
    obstacle = np.asarray(obstacle_mask)
    if obstacle.shape != road.shape or water.shape != road.shape:
        raise ValueError(
            "building hard-mask arrays must share one shape, "
            f"got obstacle {obstacle.shape}, road {road.shape}, water {water.shape}"
        )
    merged = np.logical_or(np.logical_or(obstacle > 0, road), water)
    for name, extra in (("highway buffer", highway_buffer), ("study-domain mask", study_outside)):
        if extra is None:
            continue
        if extra.shape != merged.shape:
            raise ValueError(f"{name} must share the building mask shape")
        merged |= np.asarray(extra, dtype=bool)
    return merged.astype(np.float32)


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
        segments = context.road_segments if context.road_segment_kinds is None else context.road_segments[context.road_segment_kinds == 0]
        osm = rasterize_osm_centerlines(segments, context.dem.shape)
    base = compose_building_hard_mask(
        context.obstacle_mask,
        landuse,
        osm,
        context.road_setback_m,
        context.water_setback_m,
    )

    if context.road_segment_kinds is not None:
        from config.project_config import load_default_config
        base = np.maximum(base, highway_building_buffer(context.road_segments, context.road_segment_kinds, context.dem.shape,
                                        load_default_config().modeling.highway_setback_m))
    if context.study_outside is not None:
        base = np.maximum(base, context.study_outside.astype(np.float32))
    return base
