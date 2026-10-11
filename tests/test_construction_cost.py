"""Hand-checked haul lengths. Prices are not part of the problem. No scene and no search."""

import math

import numpy as np
import pytest

from algorithms.common.scalarization import OBJECTIVE_NAMES
from modeling.construction_cost import RoadHaulCost, TerrainHaulCost


def _road() -> np.ndarray:
    return np.array([[0.0, 0.0, 5.0, 0.0], [5.0, 0.0, 10.0, 0.0]], dtype=np.float64)


def test_straight_haul_reports_lengths_without_a_price() -> None:
    measures = RoadHaulCost().measures((0.0, 0.0), (10.0, 3.0), _road())
    assert math.isclose(measures["road_m"], 10.0)
    assert math.isclose(measures["offroad_m"], 3.0)
    assert measures["access_rise_m"] is None
    assert "construction_cost" not in OBJECTIVE_NAMES


def _valley() -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[float, float], tuple[float, float]]:
    dem = np.zeros((6, 6), dtype=np.float64)
    buildable = np.ones((6, 6), dtype=np.uint8)
    segments = np.array([[0.0, 0.5, 5.9, 0.5]], dtype=np.float64)
    origin = (2.5, 0.5)
    site = (2.5, 3.5)
    return dem, buildable, segments, origin, site


def test_flat_approach_length_is_the_walked_distance() -> None:
    dem, buildable, segments, origin, site = _valley()
    measures = TerrainHaulCost().measures(origin, site, segments, dem=dem, buildable=buildable)
    approach = TerrainHaulCost().approach(site, segments, dem, buildable)
    assert math.isclose(measures["offroad_m"], 3.0)
    assert math.isclose(measures["access_rise_m"], 0.0)
    assert math.isclose(measures["road_m"], 0.0)
    assert math.isclose(approach["offroad_m"], measures["offroad_m"])
    assert math.isclose(approach["max_slope_deg"], 0.0)


def test_blocked_cell_forces_a_longer_approach() -> None:
    dem, buildable, segments, origin, site = _valley()
    buildable[2, 2] = 0
    blocked = TerrainHaulCost().measures(origin, site, segments, dem=dem, buildable=buildable)
    assert blocked["offroad_m"] > 3.0


def test_rise_is_reported_separately_from_length() -> None:
    dem, buildable, segments, origin, site = _valley()
    dem[1, 2] = 1.0
    sloped = TerrainHaulCost().measures(origin, site, segments, dem=dem, buildable=buildable)
    assert math.isclose(sloped["offroad_m"], 3.0)
    assert sloped["access_rise_m"] > 0.0
    route = TerrainHaulCost().route(origin, site, segments, dem, buildable)
    assert route["points"][0] == origin
    assert route["points"][-1] == site


def test_no_buildable_path_is_an_error() -> None:
    dem, buildable, segments, origin, site = _valley()
    buildable[2, :] = 0
    with pytest.raises(ValueError, match="no buildable path"):
        TerrainHaulCost().measures(origin, site, segments, dem=dem, buildable=buildable)
