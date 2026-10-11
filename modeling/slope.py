"""Footprint slope from an existing DEM. This is a report, not a search objective."""

from __future__ import annotations

import math

import numpy as np

from modeling.masks import compute_hard_footprint_indices

DEFAULT_SLOPE_LIMIT_DEG = 15.0


def footprint_max_slope_deg(
    dem: np.ndarray,
    pose: tuple[float, float, float],
    rect_w_m: float,
    rect_h_m: float,
) -> float:
    """Maximum slope, in degrees, between neighboring 1 m cells inside the footprint."""

    if dem.ndim != 2 or dem.size == 0 or not np.isfinite(dem).all():
        raise ValueError("dem must be a finite non-empty 2D array")
    indices = compute_hard_footprint_indices(np.array([pose], dtype=np.float64), rect_w_m, rect_h_m, dem.shape)
    cells = {(int(row), int(col)) for row, col in indices[0]}
    steepest = 0.0
    for row, col in cells:
        for neighbor in ((row + 1, col), (row, col + 1)):
            if neighbor not in cells:
                continue
            rise = abs(float(dem[neighbor]) - float(dem[row, col]))
            steepest = max(steepest, math.degrees(math.atan(rise)))
    return steepest
