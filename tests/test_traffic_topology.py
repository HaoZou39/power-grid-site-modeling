"""Topology-preserving road simplification regressions."""

import numpy as np

from data_tools.traffic_tool import RoadLine, _component_stats, _topology_simplified_segments


def _line(coords, source: str, level: int = 0) -> RoadLine:
    return RoadLine(source, 0, np.asarray(coords, dtype=np.float64), level)


def _simplify(*lines: RoadLine, tolerance: float = 1.0) -> tuple[np.ndarray, dict]:
    return _topology_simplified_segments(list(lines), tolerance)


def _endpoints(segments: np.ndarray) -> set[tuple[float, float]]:
    return {
        (round(float(point[0]), 6), round(float(point[1]), 6))
        for segment in segments
        for point in (segment[:2], segment[2:])
    }


def test_shared_source_node_stays_connected_after_simplification() -> None:
    segments, diagnostics = _simplify(
        _line([(0, 0), (5, 0.2), (10, 0)], "main"),
        _line([(5, 0.2), (5, 5)], "branch"),
    )
    assert (5.0, 0.2) in _endpoints(segments)
    assert diagnostics["raw_component_count"] == diagnostics["simplified_component_count"] == 1


def test_t_junction_and_multiple_branches_are_protected() -> None:
    segments, diagnostics = _simplify(
        _line([(0, 0), (5, 0.2), (10, 0)], "main"),
        _line([(5, 0.2), (5, 5)], "north"),
        _line([(5, 0.2), (5, -5)], "south"),
    )
    assert (5.0, 0.2) in _endpoints(segments)
    assert diagnostics["junction_node_count"] == 1
    assert diagnostics["simplified_component_count"] == 1


def test_redundant_shape_points_are_still_simplified() -> None:
    segments, diagnostics = _simplify(
        _line([(0, 0), (2, 0.05), (4, -0.05), (6, 0)], "road"),
    )
    assert len(segments) == 1
    assert diagnostics["raw_segment_count"] == 3


def test_disconnected_and_nearby_parallel_roads_are_not_snapped() -> None:
    segments, diagnostics = _simplify(
        _line([(0, 0), (10, 0)], "left"),
        _line([(0, 0.1), (10, 0.1)], "right"),
    )
    assert len(segments) == 2
    assert diagnostics["raw_component_count"] == diagnostics["simplified_component_count"] == 2


def test_bridge_crossing_is_not_noded_to_the_ground_road() -> None:
    segments, diagnostics = _simplify(
        _line([(0, 5), (10, 5)], "ground", level=0),
        _line([(5, 0), (5, 10)], "bridge", level=1),
    )
    assert diagnostics["simplified_component_count"] == 2
    assert (5.0, 5.0) not in _endpoints(segments)


def test_simplification_does_not_turn_a_geometric_crossing_into_connectivity() -> None:
    segments, diagnostics = _simplify(
        _line([(0, 0), (5, 4.9), (10, 10)], "diagonal"),
        _line([(0, 10), (10, 0)], "other"),
        tolerance=1.0,
    )
    assert diagnostics["raw_component_count"] == 2
    assert diagnostics["simplified_component_count"] == 2
    assert _component_stats(segments)["component_count"] == 2
