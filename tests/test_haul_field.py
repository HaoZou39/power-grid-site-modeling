"""Distance-field lookup against TerrainHaulCost. No scene and no search."""

import math

import numpy as np
import pytest

from modeling.construction_cost import TerrainHaulCost
from modeling.haul_field import build_haul_field, query_exact, query_route


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


def test_route_reconstruction_uses_the_field_gate_and_exact_metrics() -> None:
    dem, buildable, segments, origin, site = _valley()
    dem[1, 2] = 2.0
    buildable[2, 2] = 0
    field = build_haul_field(dem, buildable, segments, origin)
    values, blocked = query_exact(field, np.asarray([site], dtype=np.float64))
    route = query_route(field, site)

    assert blocked.tolist() == [0.0]
    assert route["road_haul_m"] == pytest.approx(values[0, 0])
    assert route["offroad_haul_m"] == pytest.approx(values[0, 1])
    assert route["haul_rise_m"] == pytest.approx(values[0, 2])
    gate_index = int(route["gate_index"])
    assert tuple(route["road_contact"]) == pytest.approx(field.gate_contacts[gate_index])
    assert route["road_segment_id"] == int(field.gate_contact_edges[gate_index])
    assert route["points"][0] == origin
    assert route["points"][-1] == site
    length = sum(math.dist(left, right) for left, right in zip(route["points"], route["points"][1:]))
    assert length == pytest.approx(route["road_haul_m"] + route["offroad_haul_m"])
    assert field.gate_road_m[gate_index] == pytest.approx(field.road_m[tuple(field.gate_cells[gate_index])])
    assert field.gate_offroad_m[gate_index] == pytest.approx(field.offroad_m[tuple(field.gate_cells[gate_index])])
    assert field.gate_rise_m[gate_index] == pytest.approx(field.access_rise_m[tuple(field.gate_cells[gate_index])])


def test_route_reconstruction_arrays_use_compact_dtypes() -> None:
    dem, buildable, segments, origin, _site = _valley()
    field = build_haul_field(dem, buildable, segments, origin)
    assert field.predecessor.dtype == np.int8
    assert field.gate_owner.dtype == np.int32
    assert field.gate_cells.dtype == np.int32
    assert field.gate_contact_edges.dtype == np.int32


@pytest.mark.parametrize(
    ("offset", "adds_terminal"),
    [(0.049, False), (0.051, True)],
)
def test_route_reconstruction_keeps_the_existing_five_centimeter_terminal_rule(
    offset: float,
    adds_terminal: bool,
) -> None:
    dem, buildable, segments, _origin, _site = _valley()
    field = build_haul_field(dem, buildable, segments)
    site = (2.5 + offset, 3.5)
    centered, _ = query_exact(field, np.asarray([[2.5, 3.5]], dtype=np.float64))
    values, blocked = query_exact(field, np.asarray([site], dtype=np.float64))
    route = query_route(field, site)

    assert blocked.tolist() == [0.0]
    assert math.isclose(values[0, 0] - centered[0, 0], offset if adds_terminal else 0.0, abs_tol=1e-9)
    assert (route["points"][-1] == site) is adds_terminal


def test_report_follows_fifo_gate_ownership_even_when_gate_initial_costs_differ() -> None:
    dem = np.zeros((7, 7), dtype=np.float64)
    buildable = np.ones_like(dem, dtype=np.uint8)
    segments = np.asarray(
        [[0.0, 0.01, 6.9, 0.01], [0.0, 6.01, 6.9, 6.01]],
        dtype=np.float64,
    )
    site = (3.5, 3.5)
    field = build_haul_field(dem, buildable, segments)
    values, blocked = query_exact(field, np.asarray([site], dtype=np.float64))
    route = query_route(field, site)

    assert blocked.tolist() == [0.0]
    assert route["offroad_haul_m"] == pytest.approx(values[0, 0])
    assert tuple(field.gate_cells[int(route["gate_index"])]) == (1, 3)
    assert route["offroad_haul_m"] == pytest.approx(3.49)
    assert 2.51 < route["offroad_haul_m"]


def _short_road() -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[float, float]]:
    dem = np.zeros((5, 5), dtype=np.float64)
    buildable = np.ones((5, 5), dtype=np.uint8)
    segments = np.array([[0.25, 0.5, 0.75, 0.5]], dtype=np.float64)
    return dem, buildable, segments, (2.5, 2.5)


def _diagonal_steps(points: list[tuple[float, float]]) -> list[float]:
    lengths = []
    for left, right in zip(points, points[1:]):
        dx = abs(right[0] - left[0])
        dy = abs(right[1] - left[1])
        if dx > 0.5 and dy > 0.5:
            lengths.append(math.hypot(right[0] - left[0], right[1] - left[1]))
    return lengths


def test_diagonal_open_ground_is_shorter_and_keeps_rise_on_that_path() -> None:
    dem, buildable, segments, site = _short_road()
    ortho = build_haul_field(dem, buildable, segments)
    diag = build_haul_field(dem, buildable, segments, diagonal=True)
    ortho_values, ortho_blocked = query_exact(ortho, np.array([site], dtype=np.float64))
    diag_values, diag_blocked = query_exact(diag, np.array([site], dtype=np.float64))
    route = query_route(diag, site)
    steps = _diagonal_steps(route["points"])

    assert ortho_blocked[0] == 0.0 and diag_blocked[0] == 0.0
    assert float(diag_values[0, 0]) < float(ortho_values[0, 0])
    assert steps == pytest.approx([math.sqrt(2)])
    assert float(diag_values[0, 0]) == pytest.approx(0.75 + 1.0 + math.sqrt(2))

    dem[1, 1] = 5.0
    dem[1, 2] = 5.0
    hilly = build_haul_field(dem, buildable, segments, diagonal=True)
    hilly_values, hilly_blocked = query_exact(hilly, np.array([site], dtype=np.float64))
    assert hilly_blocked[0] == 0.0
    assert float(hilly_values[0, 0]) == pytest.approx(float(diag_values[0, 0]))
    assert float(hilly_values[0, 1]) == pytest.approx(10.0)


def test_diagonal_step_does_not_cut_a_blocked_corner() -> None:
    dem, buildable, segments, site = _short_road()
    buildable[1, 1] = 0
    ortho = build_haul_field(dem, buildable, segments)
    diag = build_haul_field(dem, buildable, segments, diagonal=True)
    ortho_values, _ortho_blocked = query_exact(ortho, np.array([site], dtype=np.float64))
    diag_values, blocked = query_exact(diag, np.array([site], dtype=np.float64))
    route = query_route(diag, site)

    assert blocked[0] == 0.0
    assert float(diag_values[0, 0]) == pytest.approx(float(ortho_values[0, 0]))
    assert float(diag_values[0, 0]) > 0.75 + 1.0 + math.sqrt(2)
    assert _diagonal_steps(route["points"]) == []
    assert (1.5, 1.5) not in route["points"]


def test_diagonal_search_prefers_the_shorter_gate_not_the_first_seed() -> None:
    dem = np.zeros((5, 5), dtype=np.float64)
    buildable = np.ones((5, 5), dtype=np.uint8)
    segments = np.array([[0.4, 0.95, 0.6, 0.95]], dtype=np.float64)
    site = (2.5, 2.5)
    ortho = build_haul_field(dem, buildable, segments)
    diag = build_haul_field(dem, buildable, segments, diagonal=True)
    cell = (2, 2)
    ortho_values, _ortho_blocked = query_exact(ortho, np.array([site], dtype=np.float64))
    diag_values, blocked = query_exact(diag, np.array([site], dtype=np.float64))

    assert float(ortho.gate_offroad_m[0]) > float(ortho.gate_offroad_m[1])
    assert int(ortho.gate_owner[cell]) == 0
    assert int(diag.gate_owner[cell]) == 1
    assert blocked[0] == 0.0
    assert float(diag_values[0, 0]) == pytest.approx(float(diag.gate_offroad_m[1]) + 1.0 + math.sqrt(2))
    assert float(diag_values[0, 0]) < float(ortho_values[0, 0])


def test_closed_diagonal_keeps_the_existing_cache_key(tmp_path) -> None:
    from experiments.haul_field_cache import _cache_key

    dem = np.zeros((2, 2), dtype=np.float64)
    buildable = np.ones((2, 2), dtype=np.uint8)
    segments = np.zeros((1, 4), dtype=np.float64)
    signature = (("dem_1m.npy", 1, 1),)
    plain = _cache_key(tmp_path, signature, "{}", None, dem, buildable, segments)
    closed = _cache_key(tmp_path, signature, "{}", None, dem, buildable, segments, diagonal=False)
    opened = _cache_key(tmp_path, signature, "{}", None, dem, buildable, segments, diagonal=True)
    assert plain == closed
    assert opened != closed
