"""Land use and relief under one footprint. A report for analysis, not a search objective."""

from __future__ import annotations

import numpy as np

from modeling.masks import compute_hard_footprint_indices
from modeling.slope import footprint_max_slope_deg

# Class ids follow markdown/DATA_MODULE_SUMMARY.md.
LANDUSE_NAMES = ("other", "field", "building", "road", "mountain", "water")


def footprint_terrain(
    dem: np.ndarray,
    landuse: np.ndarray,
    pose: tuple[float, float, float],
    rect_w_m: float,
    rect_h_m: float,
) -> dict[str, object]:
    if dem.shape != landuse.shape:
        raise ValueError(f"dem and landuse must share a shape, got {dem.shape} and {landuse.shape}")
    rows, cols = compute_hard_footprint_indices(np.array([pose], dtype=np.float64), rect_w_m, rect_h_m, dem.shape)[0].T
    classes = landuse[rows, cols].astype(np.int64)
    if classes.min() < 0 or classes.max() >= len(LANDUSE_NAMES):
        raise ValueError(f"landuse class outside 0..{len(LANDUSE_NAMES) - 1}")
    counts = np.bincount(classes, minlength=len(LANDUSE_NAMES))
    heights = dem[rows, cols]
    return {
        "cells": int(classes.size),
        "landuse_share": {name: float(count / classes.size) for name, count in zip(LANDUSE_NAMES, counts)},
        "elevation_min_m": float(heights.min()),
        "elevation_max_m": float(heights.max()),
        "elevation_range_m": float(heights.max() - heights.min()),
        "max_slope_deg": footprint_max_slope_deg(dem, pose, rect_w_m, rect_h_m),
    }
