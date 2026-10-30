"""Whole-footprint intersections and exact lengths on a 1 m cell grid."""

from __future__ import annotations

import math
import numpy as np

DISTANCE_TOL_M = 1e-9


def circle_cells(point: np.ndarray, radius: float, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    x, y = point
    # Subtracting cell boundaries loses more than one ulp of radius near tangency.
    limit = radius + 32 * np.finfo(float).eps * max(1, abs(x), abs(y), radius)
    left, right = max(0, math.ceil(x - limit) - 1), min(shape[1] - 1, math.floor(x + limit))
    top, bottom = max(0, math.ceil(y - limit) - 1), min(shape[0] - 1, math.floor(y + limit))
    if left > right or top > bottom:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    rows, cols = np.mgrid[top:bottom + 1, left:right + 1]
    dx = x - np.clip(x, cols, cols + 1)
    dy = y - np.clip(y, rows, rows + 1)
    inside = dx * dx + dy * dy <= limit * limit
    return rows[inside], cols[inside]


def mask_intersection_length(start: np.ndarray, end: np.ndarray, mask: np.ndarray) -> float:
    delta = end - start
    length = float(np.linalg.norm(delta))
    if length == 0:
        return 0.0
    intervals = [np.array([0.0, 1.0])]
    for axis in range(2):
        if delta[axis] != 0:
            lo, hi = sorted([start[axis], end[axis]])
            lines = np.arange(math.floor(lo) + 1, math.ceil(hi), dtype=float)
            intervals.append((lines - start[axis]) / delta[axis])
    boundaries = np.unique(np.concatenate(intervals))
    middle = (boundaries[:-1] + boundaries[1:]) / 2
    points = start + middle[:, None] * delta
    cols, rows = np.floor(points).astype(int).T
    hit = np.zeros(len(middle), dtype=bool)
    # A segment lying on a shared edge belongs to both adjacent closed cells.
    col_offsets = (0, -1) if delta[0] == 0 and start[0] == math.floor(start[0]) else (0,)
    row_offsets = (0, -1) if delta[1] == 0 and start[1] == math.floor(start[1]) else (0,)
    for dc in col_offsets:
        for dr in row_offsets:
            cc, rr = cols + dc, rows + dr
            valid = (cc >= 0) & (rr >= 0) & (cc < mask.shape[1]) & (rr < mask.shape[0])
            hit[valid] |= mask[rr[valid], cc[valid]]
    return float(np.diff(boundaries)[hit].sum() * length)


def sample_dem(dem: np.ndarray, points: np.ndarray) -> np.ndarray:
    height, width = dem.shape
    result = np.full(len(points), np.nan)
    valid = np.isfinite(points).all(axis=1) & (points[:, 0] >= 0) & (points[:, 0] <= width) & (points[:, 1] >= 0) & (points[:, 1] <= height)
    xy = np.clip(points[valid] - 0.5, [0, 0], [width - 1, height - 1])
    cols, rows = np.floor(xy).astype(int).T
    right, bottom = np.minimum(cols + 1, width - 1), np.minimum(rows + 1, height - 1)
    fx, fy = (xy - np.column_stack([cols, rows])).T
    samples = np.column_stack([dem[rows, cols], dem[rows, right], dem[bottom, cols], dem[bottom, right]])
    weights = np.column_stack([(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy])
    # Zero-weight neighbours do not invalidate an exact sample next to nodata.
    values = np.where(weights > 0, samples, 0)
    result[valid] = np.sum(values * weights, axis=1)
    return result


def turn_angles(points: np.ndarray) -> np.ndarray:
    edges = np.diff(points, axis=0)
    lengths = np.linalg.norm(edges, axis=1)
    unit = edges / np.maximum(lengths[:, None], np.finfo(float).tiny)
    cross = unit[:-1, 0] * unit[1:, 1] - unit[:-1, 1] * unit[1:, 0]
    dot = np.einsum("ij,ij->i", unit[:-1], unit[1:])
    return np.arctan2(np.abs(cross), dot)


def footprint_slope(dem: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> float:
    if not len(rows):
        return float("nan")
    top, bottom = max(0, int(rows.min()) - 1), min(dem.shape[0], int(rows.max()) + 2)
    left, right = max(0, int(cols.min()) - 1), min(dem.shape[1], int(cols.max()) + 2)
    dy, dx = np.gradient(np.asarray(dem[top:bottom, left:right], dtype=float))
    slope = np.degrees(np.arctan(np.hypot(dx, dy)))
    return float(np.max(slope[rows - top, cols - left]))
