from __future__ import annotations

import numpy as np
import torch

OBJECTIVE_NAMES = ("dem_soft", "road_distance", "demand_distance")
_OBJECTIVE_SHORT_NAMES = ("dem", "road", "demand")


def normalize_weight_vector(weights: np.ndarray, min_weight: float = 0.0) -> np.ndarray:
    w = np.asarray(weights, dtype=np.float64)
    if w.shape != (3,):
        raise ValueError(f"weights must have shape [3], got {w.shape}")
    if not np.isfinite(w).all() or np.any(w < 0):
        raise ValueError("weights must be finite and non-negative")
    if min_weight < 0:
        raise ValueError("min_weight must be non-negative")
    if min_weight > 0:
        w = np.maximum(w, min_weight)
    total = float(w.sum())
    if total <= 0:
        raise ValueError("weights sum must be positive")
    return w / total


def generate_weight_grid(weight_grid_step: float, min_weight: float) -> list[np.ndarray]:
    if weight_grid_step <= 0 or weight_grid_step > 1:
        raise ValueError("weight_grid_step must be in (0, 1]")
    n = int(round(1.0 / weight_grid_step))
    if not np.isclose(n * weight_grid_step, 1.0, rtol=0.0, atol=1e-8):
        raise ValueError("weight_grid_step must evenly divide 1.0")
    out: list[np.ndarray] = []
    for i in range(n + 1):
        for j in range(n + 1 - i):
            k = n - i - j
            raw = np.array([i, j, k], dtype=np.float64) / float(n)
            out.append(normalize_weight_vector(raw, min_weight))
    return out


def compute_normalization_from_samples(
    sampled_objectives: dict[str, np.ndarray],
    demand_ideal: float,
    scale_percentile: float,
    normalization_samples: int,
    normalization_seed: int,
) -> dict[str, float | int]:
    if normalization_samples <= 0:
        raise ValueError("normalization_samples must be positive")
    if scale_percentile < 0 or scale_percentile > 100:
        raise ValueError("scale_percentile must be in [0, 100]")
    if not np.isfinite(demand_ideal):
        raise ValueError("demand_ideal must be finite")
    ideals = {"dem": 0.0, "road": 0.0, "demand": float(demand_ideal)}
    scales: dict[str, float] = {}
    for objective_name, short_name in zip(OBJECTIVE_NAMES, _OBJECTIVE_SHORT_NAMES, strict=True):
        objective = np.asarray(sampled_objectives[objective_name], dtype=np.float64)
        if objective.shape[0] != normalization_samples:
            raise ValueError(
                f"{objective_name} sample count {objective.shape[0]} does not match "
                f"normalization_samples {normalization_samples}"
            )
        if not np.isfinite(objective).all():
            raise ValueError(f"{objective_name} contains NaN or Inf")
        delta = np.maximum(0.0, objective - ideals[short_name])
        scale = float(np.percentile(delta, scale_percentile))
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError(f"normalization scale for {objective_name} must be positive")
        scales[short_name] = scale
    return {
        "ideal_dem": ideals["dem"],
        "ideal_road": ideals["road"],
        "ideal_demand": ideals["demand"],
        "scale_dem": scales["dem"],
        "scale_road": scales["road"],
        "scale_demand": scales["demand"],
        "scale_percentile": float(scale_percentile),
        "normalization_samples": int(normalization_samples),
        "normalization_seed": int(normalization_seed),
    }


def _normalization_value(normalization: dict[str, float | int], prefix: str, short_name: str) -> float:
    value = float(normalization[f"{prefix}_{short_name}"])
    if not np.isfinite(value):
        raise ValueError(f"{prefix}_{short_name} must be finite")
    return value


def _normalization_scales(normalization: dict[str, float | int]) -> tuple[float, float, float]:
    scales = tuple(_normalization_value(normalization, "scale", name) for name in _OBJECTIVE_SHORT_NAMES)
    for short_name, scale in zip(_OBJECTIVE_SHORT_NAMES, scales, strict=True):
        if scale <= 0:
            raise ValueError(f"scale_{short_name} must be positive")
    return scales


def scalarize_tchebycheff_numpy(
    objectives: dict[str, np.ndarray],
    weights: np.ndarray,
    normalization: dict[str, float | int],
    obstacle_penalty_scale: float,
    eps: float = 0.0,
) -> np.ndarray:
    if obstacle_penalty_scale < 0:
        raise ValueError("obstacle_penalty_scale must be non-negative")
    if eps < 0:
        raise ValueError("eps must be non-negative")
    w = normalize_weight_vector(weights, min_weight=0.0)
    scales = _normalization_scales(normalization)
    values = []
    for objective_name, short_name, scale in zip(OBJECTIVE_NAMES, _OBJECTIVE_SHORT_NAMES, scales, strict=True):
        objective = np.asarray(objectives[objective_name], dtype=np.float64)
        ideal = _normalization_value(normalization, "ideal", short_name)
        values.append(np.maximum(0.0, (objective - ideal) / (scale + eps)))
    stacked = np.stack(values, axis=1)
    obstacle = np.asarray(objectives["obstacle_soft"], dtype=np.float64)
    return np.max(stacked * w[None, :], axis=1) + obstacle_penalty_scale * obstacle


def scalarize_tchebycheff_torch(
    objectives: dict[str, torch.Tensor],
    weights: torch.Tensor | np.ndarray,
    normalization: dict[str, float | int],
    obstacle_penalty_scale: float,
    eps: float = 0.0,
) -> torch.Tensor:
    if obstacle_penalty_scale < 0:
        raise ValueError("obstacle_penalty_scale must be non-negative")
    if eps < 0:
        raise ValueError("eps must be non-negative")
    first = objectives[OBJECTIVE_NAMES[0]]
    w = torch.as_tensor(weights, dtype=first.dtype, device=first.device)
    if w.shape != (3,):
        raise ValueError(f"weights must have shape [3], got {tuple(w.shape)}")
    if not torch.isfinite(w).all().item() or torch.any(w < 0).item():
        raise ValueError("weights must be finite and non-negative")
    total = torch.sum(w)
    if total.item() <= 0:
        raise ValueError("weights sum must be positive")
    w = w / total
    return _scalarize_tchebycheff_torch_impl(
        objectives,
        w[None, :].expand(first.shape[0], -1),
        normalization,
        obstacle_penalty_scale,
        eps,
    )


def scalarize_tchebycheff_torch_batched(
    objectives: dict[str, torch.Tensor],
    weights: torch.Tensor | np.ndarray,
    normalization: dict[str, float | int],
    obstacle_penalty_scale: float,
    eps: float = 0.0,
) -> torch.Tensor:
    if obstacle_penalty_scale < 0:
        raise ValueError("obstacle_penalty_scale must be non-negative")
    if eps < 0:
        raise ValueError("eps must be non-negative")
    first = objectives[OBJECTIVE_NAMES[0]]
    w = torch.as_tensor(weights, dtype=first.dtype, device=first.device)
    expected_shape = (first.shape[0], 3)
    if w.shape != expected_shape:
        raise ValueError(f"weights must have shape {expected_shape}, got {tuple(w.shape)}")
    if not torch.isfinite(w).all().item() or torch.any(w < 0).item():
        raise ValueError("weights must be finite and non-negative")
    totals = torch.sum(w, dim=1, keepdim=True)
    if torch.any(totals <= 0).item():
        raise ValueError("each weights row must have a positive sum")
    return _scalarize_tchebycheff_torch_impl(
        objectives,
        w / totals,
        normalization,
        obstacle_penalty_scale,
        eps,
    )


def _scalarize_tchebycheff_torch_impl(
    objectives: dict[str, torch.Tensor],
    weights: torch.Tensor,
    normalization: dict[str, float | int],
    obstacle_penalty_scale: float,
    eps: float,
) -> torch.Tensor:
    scales = _normalization_scales(normalization)
    first = objectives[OBJECTIVE_NAMES[0]]
    values = []
    for objective_name, short_name, scale in zip(OBJECTIVE_NAMES, _OBJECTIVE_SHORT_NAMES, scales, strict=True):
        objective = objectives[objective_name]
        if objective.shape != first.shape:
            raise ValueError(f"{objective_name} shape {tuple(objective.shape)} does not match {tuple(first.shape)}")
        ideal = _normalization_value(normalization, "ideal", short_name)
        values.append(torch.clamp_min((objective - ideal) / (scale + eps), 0.0))
    stacked = torch.stack(values, dim=1)
    obstacle = objectives["obstacle_soft"]
    if obstacle.shape != first.shape:
        raise ValueError(f"obstacle_soft shape {tuple(obstacle.shape)} does not match {tuple(first.shape)}")
    return torch.max(stacked * weights, dim=1).values + obstacle_penalty_scale * obstacle
