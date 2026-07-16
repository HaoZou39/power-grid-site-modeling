from __future__ import annotations

import numpy as np

from algorithms.cma_es.cma_es import generate_weight_grid, scalarize_tchebycheff
from algorithms.cma_es.pareto import extract_feasible_pareto_front
from algorithms.cma_es.weiszfeld import compute_demand_ideal_value, compute_weighted_geometric_median


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
    scalar = scalarize_tchebycheff(objectives, np.array([0.2, 0.3, 0.5]), normalization, obstacle_penalty_scale=2.0)
    assert abs(float(scalar[0]) - 0.75) < 1e-8
