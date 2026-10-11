"""Construction reports stay outside the three search objectives."""

import math

import numpy as np

from algorithms.common.scalarization import OBJECTIVE_NAMES
from modeling.access_path import access_profile, access_warning
from modeling.evaluator import compute_hard_constraints
from modeling.logistics_cost import logistics_route
from modeling.slope import footprint_max_slope_deg


def test_uniform_slope_is_steeper_than_flat_ground() -> None:
    flat = np.full((8, 8), 3.0, dtype=np.float32)
    ramp = np.zeros((8, 8), dtype=np.float32)
    ramp[:] = np.arange(8, dtype=np.float32) * 0.5
    pose = (4.5, 4.5, 0.0)
    assert footprint_max_slope_deg(ramp, pose, 4.0, 4.0) > footprint_max_slope_deg(flat, pose, 4.0, 4.0)
    assert OBJECTIVE_NAMES == ("dem_soft", "road_distance", "demand_distance")


def test_nearby_origin_has_a_shorter_road_length() -> None:
    segments = np.array([[0.0, 0.0, 10.0, 0.0]], dtype=np.float64)
    near = logistics_route((0.0, 1.0), (1.0, 1.0), segments)
    far = logistics_route((0.0, 1.0), (10.0, 1.0), segments)
    assert near["road_m"] < far["road_m"]
    assert math.isclose(far["road_m"], 10.0)
    assert math.isclose(far["offroad_m"], 2.0)
    joined = np.array([[0.0, 0.0, 5.0, 0.0], [5.0, 0.0, 10.0, 0.0]], dtype=np.float64)
    route = logistics_route((0.0, 1.0), (10.0, 1.0), joined)
    assert route["points"][0] == (0.0, 1.0)
    assert route["points"][-1] == (10.0, 1.0)
    assert any(abs(point[1]) < 0.01 for point in route["points"])


def test_steep_approach_warns_without_changing_feasibility() -> None:
    dem = np.zeros((1, 7), dtype=np.float32)
    dem[0, 3] = 5.0
    segments = np.array([[6.5, 0.5, 8.5, 0.5]], dtype=np.float64)
    steep = access_profile(dem, (0.5, 0.5), segments)
    flat = access_profile(np.zeros_like(dem), (0.5, 0.5), segments)
    assert steep["max_slope_deg"] > flat["max_slope_deg"]
    assert access_warning(steep["max_slope_deg"], 10.0) is True
    feasible = compute_hard_constraints(
        dem,
        np.zeros_like(dem),
        np.array([[0.5, 0.5, 0.0]]),
        0.4,
        0.4,
        device="cpu",
    )
    assert bool(feasible["is_feasible"][0].item()) is True
