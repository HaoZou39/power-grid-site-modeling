"""Distance-field lookup against TerrainHaulCost. No scene and no search."""

import math

import numpy as np
import pytest

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
    assert field.reachable_gate_count == field.gate_count
    assert field.unreachable_gate_count == 0


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


def _split_roads() -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[float, float]]:
    dem = np.zeros((10, 12), dtype=np.float64)
    buildable = np.ones((10, 12), dtype=np.uint8)
    buildable[4:6, :] = 0
    segments = np.array(
        [[0.0, 1.5, 4.0, 1.5], [7.0, 7.5, 11.5, 7.5]],
        dtype=np.float64,
    )
    return dem, buildable, segments, (1.0, 1.5)


def test_partly_disconnected_gates_are_skipped_and_candidates_stay_blocked() -> None:
    dem, buildable, segments, origin = _split_roads()
    field = build_haul_field(dem, buildable, segments, origin)
    assert 0 < field.reachable_gate_count < field.gate_count
    assert field.unreachable_gate_count == field.gate_count - field.reachable_gate_count

    values, blocked = query_exact(field, np.array([[2.5, 3.5], [8.5, 8.5]], dtype=np.float64))
    assert blocked.tolist() == [0.0, 1.0]
    assert np.isfinite(values[0]).all() and np.all(values[0] >= 0.0)
    assert np.all(values[1] == 0.0)


def test_all_disconnected_gates_report_diagnostic_counts() -> None:
    dem = np.zeros((9, 12), dtype=np.float64)
    buildable = np.zeros((9, 12), dtype=np.uint8)
    buildable[7:, :] = 1
    segments = np.array(
        [[0.0, 1.5, 4.0, 1.5], [7.0, 6.5, 11.5, 6.5]],
        dtype=np.float64,
    )
    with pytest.raises(
        ValueError,
        match=r"total_gates=\d+, reachable_gates=0, unreachable_gates=\d+",
    ):
        build_haul_field(dem, buildable, segments, (1.0, 1.5))

    without_origin = build_haul_field(dem, buildable, segments)
    assert without_origin.gate_count > 0
    assert without_origin.reachable_gate_count == without_origin.gate_count
    assert without_origin.unreachable_gate_count == 0


def test_origin_builds_one_graph_and_runs_one_dijkstra(monkeypatch) -> None:
    from modeling import logistics_cost

    dem, buildable, segments, origin = _split_roads()
    graph_calls = 0
    dijkstra_calls = 0
    real_graph = logistics_cost._build_graph
    real_dijkstra = logistics_cost._dijkstra_all

    def counting_graph(*args, **kwargs):
        nonlocal graph_calls
        graph_calls += 1
        return real_graph(*args, **kwargs)

    def counting_dijkstra(*args, **kwargs):
        nonlocal dijkstra_calls
        dijkstra_calls += 1
        return real_dijkstra(*args, **kwargs)

    monkeypatch.setattr(logistics_cost, "_build_graph", counting_graph)
    monkeypatch.setattr(logistics_cost, "_dijkstra_all", counting_dijkstra)
    build_haul_field(dem, buildable, segments, origin)
    assert graph_calls == 1
    assert dijkstra_calls == 1
