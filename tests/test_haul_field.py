"""Distance-field lookup against TerrainHaulCost. No scene and no search."""

import math

import numpy as np

from modeling.construction_cost import TerrainHaulCost
from modeling.haul_field import build_haul_field, query_exact


def _valley() -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[float, float], tuple[float, float]]:
    dem = np.zeros((6, 6), dtype=np.float64)
    buildable = np.ones((6, 6), dtype=np.uint8)
    segments = np.array([[0.0, 0.5, 5.9, 0.5]], dtype=np.float64)
    origin = (2.5, 0.5)
    site = (2.5, 3.5)
    return dem, buildable, segments, origin, site


def _matches(field_values: np.ndarray, measured: dict[str, float], *, with_origin: bool) -> None:
    if with_origin:
        assert math.isclose(float(field_values[0]), measured["road_m"], rel_tol=0.0, abs_tol=1e-6)
        assert math.isclose(float(field_values[1]), measured["offroad_m"], rel_tol=0.0, abs_tol=1e-6)
        assert math.isclose(float(field_values[2]), measured["access_rise_m"], rel_tol=0.0, abs_tol=1e-6)
    else:
        assert math.isclose(float(field_values[0]), measured["offroad_m"], rel_tol=0.0, abs_tol=1e-6)
        assert math.isclose(float(field_values[1]), measured["access_rise_m"], rel_tol=0.0, abs_tol=1e-6)


def test_flat_center_matches_the_walked_approach() -> None:
    dem, buildable, segments, origin, site = _valley()
    field = build_haul_field(dem, buildable, segments, origin)
    values, blocked = query_exact(field, np.array([site], dtype=np.float64))
    measured = TerrainHaulCost().measures(origin, site, segments, dem=dem, buildable=buildable)
    assert blocked[0] == 0.0
    _matches(values[0], measured, with_origin=True)
    assert math.isclose(measured["offroad_m"], 3.0)
    assert math.isclose(measured["access_rise_m"], 0.0)
    assert math.isclose(measured["road_m"], 0.0)


def test_blocked_cell_keeps_the_longer_approach_and_its_rise() -> None:
    dem, buildable, segments, origin, site = _valley()
    buildable[2, 2] = 0
    field = build_haul_field(dem, buildable, segments, origin)
    values, blocked = query_exact(field, np.array([site], dtype=np.float64))
    measured = TerrainHaulCost().measures(origin, site, segments, dem=dem, buildable=buildable)
    assert blocked[0] == 0.0
    assert measured["offroad_m"] > 3.0
    _matches(values[0], measured, with_origin=True)


def test_rise_stays_separate_from_length() -> None:
    dem, buildable, segments, origin, site = _valley()
    dem[1, 2] = 1.0
    field = build_haul_field(dem, buildable, segments, origin)
    values, blocked = query_exact(field, np.array([site], dtype=np.float64))
    measured = TerrainHaulCost().measures(origin, site, segments, dem=dem, buildable=buildable)
    assert blocked[0] == 0.0
    assert math.isclose(measured["offroad_m"], 3.0)
    assert measured["access_rise_m"] > 0.0
    _matches(values[0], measured, with_origin=True)


def test_blocked_row_is_not_a_feasible_objective() -> None:
    dem, buildable, segments, origin, site = _valley()
    buildable[2, :] = 0
    field = build_haul_field(dem, buildable, segments, origin)
    values, blocked = query_exact(field, np.array([site], dtype=np.float64))
    assert blocked[0] == 1.0
    assert np.all(values[0] == 0.0)


def test_road_contact_just_outside_the_grid_still_builds() -> None:
    dem = np.zeros((6, 6), dtype=np.float64)
    buildable = np.ones((6, 6), dtype=np.uint8)
    segments = np.array([[-1.0, 0.5, 5.0, 0.5]], dtype=np.float64)
    field = build_haul_field(dem, buildable, segments)
    values, blocked = query_exact(field, np.array([[2.5, 3.5]], dtype=np.float64))
    assert blocked[0] == 0.0
    assert values[0, 0] > 0.0


def test_off_center_site_includes_the_last_segment() -> None:
    dem, buildable, segments, origin, _site = _valley()
    site = (2.7, 3.5)
    field = build_haul_field(dem, buildable, segments)
    values, blocked = query_exact(field, np.array([site], dtype=np.float64))
    measured = TerrainHaulCost().approach(site, segments, dem, buildable)
    assert blocked[0] == 0.0
    assert measured["offroad_m"] > 3.0
    _matches(values[0], measured, with_origin=False)
