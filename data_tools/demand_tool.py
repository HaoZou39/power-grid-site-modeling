from __future__ import annotations

import numpy as np

from .io_utils import LOCAL_COORD_CONVENTION


def generate_demand_points(
    n_demand_points: int,
    demand_seed: int,
    primary_grid_shape: tuple[int, int],
    demand_on_buildable_only: bool,
    obstacle_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None, dict]:
    if n_demand_points <= 0:
        raise ValueError("n_demand_points must be positive")
    if len(primary_grid_shape) != 2:
        raise ValueError("primary_grid_shape must have length 2")
    h, w = (int(primary_grid_shape[0]), int(primary_grid_shape[1]))
    if h <= 0 or w <= 0:
        raise ValueError("primary_grid_shape values must be positive")
    rng = np.random.default_rng(demand_seed)
    if demand_on_buildable_only:
        if obstacle_mask is None:
            raise ValueError("obstacle_mask is required when demand_on_buildable_only is True")
        if obstacle_mask.ndim != 2 or obstacle_mask.size == 0:
            raise ValueError("obstacle_mask must be a non-empty 2D array")
        if obstacle_mask.shape != (h, w):
            raise ValueError(f"obstacle_mask shape {obstacle_mask.shape} does not match primary_grid_shape {(h, w)}")
        buildable = np.argwhere(obstacle_mask <= 0)
        if len(buildable) < n_demand_points:
            raise ValueError("not enough buildable cells for requested demand points")
        chosen = buildable[rng.choice(len(buildable), size=n_demand_points, replace=False)]
        jitter = rng.random((n_demand_points, 2), dtype=np.float32)
        points = np.column_stack([chosen[:, 1] + jitter[:, 0], chosen[:, 0] + jitter[:, 1]])
    else:
        points = rng.random((n_demand_points, 2), dtype=np.float32) * np.array([w, h], dtype=np.float32)
    if not np.isfinite(points).all():
        raise ValueError("demand_points contains NaN or Inf")
    metadata = {
        "n_demand_points": n_demand_points,
        "demand_seed": demand_seed,
        "primary_grid_shape": [h, w],
        "demand_on_buildable_only": demand_on_buildable_only,
        "local_coord_convention": LOCAL_COORD_CONVENTION,
    }
    return points.astype(np.float32), None, metadata
