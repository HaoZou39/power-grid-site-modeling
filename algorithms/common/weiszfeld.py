from __future__ import annotations

import numpy as np


def _normalized_weights(demand_points: np.ndarray, demand_weights: np.ndarray | None) -> np.ndarray:
    points = np.asarray(demand_points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or points.shape[0] == 0:
        raise ValueError(f"demand_points must have shape [N, 2], got {points.shape}")
    if not np.isfinite(points).all():
        raise ValueError("demand_points contains NaN or Inf")
    if demand_weights is None:
        return np.full(points.shape[0], 1.0 / points.shape[0], dtype=np.float64)
    weights = np.asarray(demand_weights, dtype=np.float64)
    if weights.ndim != 1 or weights.shape[0] != points.shape[0]:
        raise ValueError(f"demand_weights must have shape [{points.shape[0]}], got {weights.shape}")
    if not np.isfinite(weights).all():
        raise ValueError("demand_weights contains NaN or Inf")
    if np.any(weights < 0):
        raise ValueError("demand_weights must be non-negative")
    total = float(weights.sum())
    if total <= 0:
        raise ValueError("demand_weights sum must be positive")
    return weights / total


def compute_weighted_geometric_median(
    demand_points: np.ndarray,
    demand_weights: np.ndarray | None,
    max_iters: int,
    tol: float,
    eps: float,
) -> np.ndarray:
    if max_iters <= 0 or tol <= 0 or eps <= 0:
        raise ValueError("max_iters, tol, and eps must be positive")
    points = np.asarray(demand_points, dtype=np.float64)
    weights = _normalized_weights(points, demand_weights)
    current = np.sum(points * weights[:, None], axis=0)
    for _ in range(max_iters):
        dist = np.linalg.norm(points - current[None, :], axis=1)
        near = dist < eps
        if np.any(near):
            current = points[int(np.argmax(weights * near))]
            dist = np.maximum(np.linalg.norm(points - current[None, :], axis=1), eps)
        inv = weights / np.maximum(dist, eps)
        nxt = np.sum(points * inv[:, None], axis=0) / inv.sum()
        if np.linalg.norm(nxt - current) <= tol:
            return nxt.astype(np.float64)
        current = nxt
    return current.astype(np.float64)


def compute_demand_ideal_value(
    demand_points: np.ndarray,
    demand_weights: np.ndarray | None,
    max_iters: int,
    tol: float,
    eps: float,
) -> float:
    points = np.asarray(demand_points, dtype=np.float64)
    weights = _normalized_weights(points, demand_weights)
    median = compute_weighted_geometric_median(points, weights, max_iters=max_iters, tol=tol, eps=eps)
    distances = np.linalg.norm(points - median[None, :], axis=1)
    return float(np.sum(weights * distances))
