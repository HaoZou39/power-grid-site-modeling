from __future__ import annotations

import numpy as np

from .io_utils import LOCAL_COORD_CONVENTION


def generate_demand_points(
    n_demand_points: int,
    demand_seed: int,
    half_side_m: float,
    demand_on_buildable_only: bool,
    obstacle_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None, dict]:
    if n_demand_points <= 0:
        raise ValueError("n_demand_points must be positive")
    if half_side_m <= 0:
        raise ValueError("half_side_m must be positive")
    side = 2.0 * half_side_m
    rng = np.random.default_rng(demand_seed)
    if demand_on_buildable_only:
        if obstacle_mask is None:
            raise ValueError("obstacle_mask is required when demand_on_buildable_only is True")
        if obstacle_mask.ndim != 2 or obstacle_mask.size == 0:
            raise ValueError("obstacle_mask must be a non-empty 2D array")
        buildable = np.argwhere(obstacle_mask <= 0)
        if len(buildable) < n_demand_points:
            raise ValueError("not enough buildable cells for requested demand points")
        chosen = buildable[rng.choice(len(buildable), size=n_demand_points, replace=False)]
        jitter = rng.random((n_demand_points, 2), dtype=np.float32)
        points = np.column_stack([chosen[:, 1] + jitter[:, 0], chosen[:, 0] + jitter[:, 1]])
    else:
        points = rng.random((n_demand_points, 2), dtype=np.float32) * np.float32(side)
    if not np.isfinite(points).all():
        raise ValueError("demand_points contains NaN or Inf")
    metadata = {
        "n_demand_points": n_demand_points,
        "demand_seed": demand_seed,
        "half_side_m": half_side_m,
        "demand_on_buildable_only": demand_on_buildable_only,
        "local_coord_convention": LOCAL_COORD_CONVENTION,
    }
    return points.astype(np.float32), None, metadata

