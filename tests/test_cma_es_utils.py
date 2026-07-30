from __future__ import annotations

import numpy as np
import torch

from algorithms.common.pareto import extract_feasible_pareto_front
from algorithms.common.scalarization import (
    compute_normalization_from_samples,
    generate_weight_grid,
    scalarize_tchebycheff_numpy,
    scalarize_tchebycheff_torch,
)
from algorithms.common.weiszfeld import compute_demand_ideal_value, compute_weighted_geometric_median


def test_weiszfeld_two_equal_points_returns_midpoint_and_ideal() -> None:
    points = np.array([[0.0, 0.0], [2.0, 0.0]], dtype=np.float64)
    median = compute_weighted_geometric_median(points, None, max_iters=128, tol=1e-9, eps=1e-12)
    np.testing.assert_allclose(median, np.array([1.0, 0.0]), atol=1e-8)
    ideal = compute_demand_ideal_value(points, None, max_iters=128, tol=1e-9, eps=1e-12)
    assert abs(ideal - 1.0) < 1e-8


def test_weiszfeld_rejects_invalid_weights() -> None:
    points = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float64)
    try:
        compute_weighted_geometric_median(points, np.array([1.0, -1.0]), max_iters=16, tol=1e-6, eps=1e-8)
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_pareto_uses_only_feasible_records() -> None:
    records = [
        {"id": "a", "dem_soft": 1.0, "road_distance": 3.0, "demand_distance": 2.0, "is_feasible": True},
        {"id": "b", "dem_soft": 2.0, "road_distance": 2.0, "demand_distance": 2.0, "is_feasible": True},
        {"id": "c", "dem_soft": 3.0, "road_distance": 1.0, "demand_distance": 2.0, "is_feasible": True},
        {"id": "d", "dem_soft": 4.0, "road_distance": 4.0, "demand_distance": 4.0, "is_feasible": True},
        {"id": "bad", "dem_soft": 0.0, "road_distance": 0.0, "demand_distance": 0.0, "is_feasible": False},
    ]
    front = extract_feasible_pareto_front(records, ("dem_soft", "road_distance", "demand_distance"))
    assert {row["id"] for row in front} == {"a", "b", "c"}


def test_weight_grid_is_deterministic_and_normalized() -> None:
    weights = generate_weight_grid(0.5, min_weight=0.0)
    assert len(weights) == 6
    for weight in weights:
        np.testing.assert_allclose(weight.sum(), 1.0)
        assert np.all(weight >= 0)


def test_tchebycheff_scalarization_uses_scales_and_penalty() -> None:
    objectives = {
        "dem_soft": np.array([5.0]),
        "road_distance": np.array([2.0]),
        "demand_distance": np.array([3.0]),
        "obstacle_soft": np.array([0.25]),
    }
    normalization = {
        "ideal_dem": 0.0,
        "ideal_road": 0.0,
        "ideal_demand": 1.0,
        "scale_dem": 10.0,
        "scale_road": 4.0,
        "scale_demand": 4.0,
    }
    scalar = scalarize_tchebycheff_numpy(objectives, np.array([0.2, 0.3, 0.5]), normalization, obstacle_penalty_scale=2.0)
    assert abs(float(scalar[0]) - 0.75) < 1e-8


def test_normalization_uses_fixed_ideals_and_percentile_scales() -> None:
    objectives = {
        "dem_soft": np.array([0.0, 2.0, 4.0]),
        "road_distance": np.array([1.0, 3.0, 5.0]),
        "demand_distance": np.array([10.0, 12.0, 16.0]),
    }
    normalization = compute_normalization_from_samples(
        objectives,
        demand_ideal=10.0,
        scale_percentile=100.0,
        normalization_samples=3,
        normalization_seed=123,
    )

    assert normalization["ideal_dem"] == 0.0
    assert normalization["ideal_road"] == 0.0
    assert normalization["ideal_demand"] == 10.0
    assert normalization["scale_dem"] == 4.0
    assert normalization["scale_road"] == 5.0
    assert normalization["scale_demand"] == 6.0
    assert normalization["normalization_seed"] == 123


def test_tchebycheff_torch_matches_numpy_and_keeps_gradient() -> None:
    objectives_np = {
        "dem_soft": np.array([5.0]),
        "road_distance": np.array([2.0]),
        "demand_distance": np.array([3.0]),
        "obstacle_soft": np.array([0.25]),
    }
    objectives_torch = {
        name: torch.tensor(value, dtype=torch.float64, requires_grad=name != "obstacle_soft")
        for name, value in objectives_np.items()
    }
    objectives_torch["obstacle_soft"].requires_grad_(True)
    normalization = {
        "ideal_dem": 0.0,
        "ideal_road": 0.0,
        "ideal_demand": 1.0,
        "scale_dem": 10.0,
        "scale_road": 4.0,
        "scale_demand": 4.0,
    }
    weights = np.array([0.2, 0.3, 0.5])

    scalar_np = scalarize_tchebycheff_numpy(objectives_np, weights, normalization, obstacle_penalty_scale=2.0)
    scalar_torch = scalarize_tchebycheff_torch(objectives_torch, torch.as_tensor(weights), normalization, obstacle_penalty_scale=2.0)

    np.testing.assert_allclose(scalar_torch.detach().numpy(), scalar_np)
    scalar_torch.sum().backward()
    assert objectives_torch["demand_distance"].grad is not None
    assert torch.isfinite(objectives_torch["demand_distance"].grad).all()
