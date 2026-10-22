"""Reproducible poses in rectangular and constrained center domains."""

from __future__ import annotations

import math
from typing import Callable

import numpy as np


INITIALIZATION_METHODS = ("gaussian", "uniform", "taguchi")


def sample_initial_population(
    popsize: int,
    seed: int,
    method: str = "uniform",
    sigma0: float = 1.0,
    *,
    allowed_mask: np.ndarray | None = None,
    pose_bounds: tuple[float, float, float, float] | None = None,
    center_filter: Callable[[np.ndarray], np.ndarray] | None = None,
    max_sampling_batches: int = 100,
) -> np.ndarray:
    """Return float32 raw poses; uniformity is defined after sigmoid decoding."""
    if popsize < 4:
        raise ValueError("popsize must be at least 4")
    if method not in INITIALIZATION_METHODS:
        raise ValueError(f"initialization must be one of {INITIALIZATION_METHODS}")
    if not math.isfinite(sigma0) or sigma0 <= 0:
        raise ValueError("sigma0 must be finite and positive")
    if method == "taguchi" and math.isqrt(popsize) ** 2 != popsize:
        raise ValueError("taguchi initialization requires a square popsize, such as 10000")
    rng = np.random.default_rng(seed)
    if allowed_mask is not None:
        if pose_bounds is None:
            raise ValueError("pose_bounds are required with allowed_mask")
        if resolve_initialization_method(method, allowed_mask, pose_bounds, center_filter is not None) == "uniform":
            if max_sampling_batches < 1:
                raise ValueError("max_sampling_batches must be positive")
            accepted, count = [], 0
            for _ in range(max_sampling_batches):
                raw = _raw_from_unit(_sample_allowed_centers(rng, popsize, allowed_mask, pose_bounds))
                kept = raw if center_filter is None else raw[center_filter(raw)]
                accepted.append(kept)
                count += len(kept)
                if count >= popsize:
                    return np.concatenate(accepted)[:popsize]
            raise ValueError("could not fill initialization inside feasible regions; check the allowed area and bounds")
    if method == "gaussian":
        return rng.normal(0.0, sigma0, size=(popsize, 3)).astype(np.float32)
    if method == "uniform":
        unit = rng.random((popsize, 3))
    else:
        levels = math.isqrt(popsize)
        a, b = np.indices((levels, levels)).reshape(2, -1)
        table = np.column_stack((a, b, (a + b) % levels))
        for column in range(3):
            table[:, column] = rng.permutation(levels)[table[:, column]]
        unit = (table[rng.permutation(popsize)] + 0.5) / levels
    return _raw_from_unit(unit)


def _raw_from_unit(unit: np.ndarray) -> np.ndarray:
    epsilon = np.finfo(np.float32).eps
    unit = np.clip(unit, epsilon, 1.0 - epsilon)
    return (np.log(unit) - np.log1p(-unit)).astype(np.float32)


def _domain_window(
    allowed_mask: np.ndarray, bounds: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    allowed = np.asarray(allowed_mask)
    if allowed.ndim != 2 or allowed.dtype != np.bool_:
        raise ValueError("allowed_mask must be a 2D boolean array")
    xmin, xmax, ymin, ymax = bounds
    if (not all(math.isfinite(value) for value in bounds)
            or not 0 <= xmin < xmax <= allowed.shape[1]
            or not 0 <= ymin < ymax <= allowed.shape[0]):
        raise ValueError("pose_bounds must be a non-empty rectangle inside allowed_mask")
    return math.floor(xmin), math.ceil(xmax), math.floor(ymin), math.ceil(ymax)


def resolve_initialization_method(
    method: str, allowed_mask: np.ndarray,
    pose_bounds: tuple[float, float, float, float], has_regions: bool = False,
) -> str:
    left, right, bottom, top = _domain_window(allowed_mask, pose_bounds)
    return method if not has_regions and allowed_mask[bottom:top, left:right].all() else "uniform"


def _sample_allowed_centers(
    rng: np.random.Generator, popsize: int, allowed_mask: np.ndarray,
    bounds: tuple[float, float, float, float],
) -> np.ndarray:
    xmin, xmax, ymin, ymax = bounds
    left, right, bottom, top = _domain_window(allowed_mask, bounds)
    allowed = allowed_mask[bottom:top, left:right]
    xlow = np.maximum(np.arange(left, right), xmin)
    xhigh = np.minimum(np.arange(left, right) + 1, xmax)
    ylow = np.maximum(np.arange(bottom, top), ymin)
    yhigh = np.minimum(np.arange(bottom, top) + 1, ymax)
    widths = xhigh - xlow
    # Only the two boundary columns can have fractional cell area.
    row_area = allowed.sum(axis=1).astype(np.float64)
    row_area -= allowed[:, 0] * (1 - widths[0])
    if len(widths) > 1:
        row_area -= allowed[:, -1] * (1 - widths[-1])
    row_area *= yhigh - ylow
    if row_area.sum() <= 0:
        raise ValueError("no allowed initialization centers inside the safe search bounds")
    rows = rng.choice(len(row_area), popsize, p=row_area / row_area.sum())
    columns = np.empty(popsize, dtype=np.intp)
    for row in np.unique(rows):
        positions = np.flatnonzero(rows == row)
        choices = np.flatnonzero(allowed[row])
        weights = widths[choices]
        columns[positions] = rng.choice(choices, len(positions), p=weights / weights.sum())
    # Keep sigmoid/float32 rounding from moving a center into an adjacent hard cell.
    guard = 8 * np.finfo(np.float32).eps * max(xmax - xmin, ymax - ymin)
    xpad = np.minimum(guard, (xhigh[columns] - xlow[columns]) / 4)
    ypad = np.minimum(guard, (yhigh[rows] - ylow[rows]) / 4)
    x = rng.uniform(xlow[columns] + xpad, xhigh[columns] - xpad)
    y = rng.uniform(ylow[rows] + ypad, yhigh[rows] - ypad)
    return np.column_stack(((x - xmin) / (xmax - xmin),
                            (y - ymin) / (ymax - ymin), rng.random(popsize)))
