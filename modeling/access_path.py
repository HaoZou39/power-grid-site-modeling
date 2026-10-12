"""直线进场，只给测试对照。

决策报告和引导式多目标搜索的进场长度、高差、坡度都用 `construction_cost.TerrainHaulCost` 的格子路径。
不要再把本文件的直线结果写进方案或侧栏。
"""

from __future__ import annotations

import math

import numpy as np

from modeling.logistics_cost import nearest_road_point

DEFAULT_ACCESS_SLOPE_LIMIT_DEG = 15.0


def access_profile(
    dem: np.ndarray,
    site: tuple[float, float],
    segments: np.ndarray,
    sample_m: float = 1.0,
) -> dict[str, float]:
    """Sample the straight approach and report its rise and steepest step."""

    if dem.ndim != 2 or not np.isfinite(dem).all():
        raise ValueError("dem must be a finite 2D array")
    if sample_m <= 0:
        raise ValueError("sample_m must be positive")
    road = nearest_road_point(site, segments)
    length = math.hypot(road[0] - site[0], road[1] - site[1])
    steps = max(1, int(math.ceil(length / sample_m)))
    elevations = [_read_dem(dem, site[0] + (road[0] - site[0]) * i / steps, site[1] + (road[1] - site[1]) * i / steps) for i in range(steps + 1)]
    step_length = length / steps if steps else 1.0
    steepest = 0.0
    if step_length > 0:
        for left, right in zip(elevations, elevations[1:]):
            steepest = max(steepest, math.degrees(math.atan(abs(right - left) / step_length)))
    return {
        "rise_m": abs(elevations[-1] - elevations[0]),
        "max_slope_deg": steepest,
    }


def access_warning(max_slope_deg: float, limit_deg: float = DEFAULT_ACCESS_SLOPE_LIMIT_DEG) -> bool:
    """A warning does not change hard feasibility."""

    if limit_deg <= 0:
        raise ValueError("access slope limit must be positive")
    return max_slope_deg > limit_deg


def _read_dem(dem: np.ndarray, x: float, y: float) -> float:
    row = min(dem.shape[0] - 1, max(0, int(math.floor(y))))
    col = min(dem.shape[1] - 1, max(0, int(math.floor(x))))
    return float(dem[row, col])
