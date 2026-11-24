import numpy as np
import pytest

from config.project_config import load_default_config
from config.routing_task import ExistingPowerLine, RoutingRunConfig
from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.existing_lines import existing_line_report, overlay_existing_lines
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.types import Route, RoutingConstraints
from test_routing_context import make_problem
from test_routing_output import routing_task


LINE = {"id": "existing-line-001", "points": [[2.0, 16.0], [30.0, 16.0]]}
RADIUS = RoutingConstraints(40, 2, 180, 0, 0)


def overlay(problem, lines=(), buffer=10.0):
    return overlay_existing_lines(problem, lines, buffer)


def test_missing_lines_leave_the_base_problem_unchanged():
    problem = make_problem(constraints=RADIUS)
    same = overlay(problem, (), 10)
    assert same.crossing_mask is problem.crossing_mask
    assert same.tower_blocked is problem.tower_blocked
    assert same.dem is problem.dem and same.landuse is problem.landuse
    route = Route(np.empty((0, 2)))
    base, overlaid = RouteEvaluator(problem).evaluate(route), RouteEvaluator(same).evaluate(route)
    np.testing.assert_array_equal(base.objectives, overlaid.objectives)
    assert base.is_feasible == overlaid.is_feasible
    assert existing_line_report(same, route.points(problem.start, problem.end), base.elevations)["existing_line_crossing_count"] == 0


def test_centerline_radius_blocks_and_the_buffer_does_not():
    base = make_problem(constraints=RADIUS, start=(2, 4), end=(28, 4))
    problem = overlay(base, [LINE], 10)
    evaluator = RouteEvaluator(problem)
    assert problem.tower_blocked is base.tower_blocked
    assert not evaluator.tower_allowed([16, 16])
    assert not evaluator.tower_allowed([16, 18])
    assert evaluator.tower_allowed([16, 18.5])
    assert evaluator.evaluate(Route(np.array([[16.0, 18.5]]))).violations["blocked_tower_count"] == 0


def test_buffer_adds_crossing_only_where_the_route_enters_it():
    empty = make_problem(constraints=RADIUS, start=(16, 2), end=(16, 30))
    base = RouteEvaluator(empty).evaluate(Route(np.empty((0, 2)))).objectives[3]
    narrow = overlay(empty, [LINE], 0)
    wide = overlay(empty, [LINE], 10)
    assert RouteEvaluator(narrow).evaluate(Route(np.empty((0, 2)))).objectives[3] == pytest.approx(base)
    crossed = RouteEvaluator(wide).evaluate(Route(np.empty((0, 2)))).objectives[3]
    assert crossed > base
    missed = overlay(make_problem(constraints=RADIUS, start=(2, 2), end=(28, 2)), [LINE], 10)
    assert RouteEvaluator(missed).evaluate(Route(np.empty((0, 2)))).objectives[3] == pytest.approx(0)
    report = existing_line_report(wide, np.array([[16.0, 2.0], [16.0, 30.0]]), np.zeros(2))
    assert report["existing_line_crossing_length_m"] == pytest.approx(crossed)
    assert report["existing_line_crossing_count"] == 1


def test_oblique_parallel_repeat_and_overlapping_buffers():
    line = LINE
    oblique = overlay(make_problem(constraints=RADIUS, start=(2, 2), end=(30, 30)), [line], 10)
    assert RouteEvaluator(oblique).evaluate(Route(np.empty((0, 2)))).objectives[3] > 0
    near = overlay(make_problem(constraints=RADIUS, start=(2, 20), end=(28, 20)), [line], 10)
    far = overlay(make_problem(constraints=RADIUS, start=(2, 30), end=(28, 30)), [line], 10)
    assert RouteEvaluator(near).evaluate(Route(np.empty((0, 2)))).objectives[3] > 20
    assert RouteEvaluator(far).evaluate(Route(np.empty((0, 2)))).objectives[3] == pytest.approx(0)
    twice = overlay(make_problem(constraints=RADIUS, start=(4, 4), end=(28, 4)), [line], 10)
    points = np.array([[4.0, 4.0], [16.0, 28.0], [28.0, 4.0]])
    assert existing_line_report(twice, points, np.zeros(3))["existing_line_crossing_count"] == 2
    shared = overlay(make_problem(constraints=RADIUS, start=(4, 4), end=(28, 4)), [line], 10)
    shared_points = np.array([[4.0, 4.0], [16.0, 16.0], [28.0, 4.0]])
    assert existing_line_report(shared, shared_points, np.zeros(3))["existing_line_crossing_count"] == 1
    along = overlay(make_problem(constraints=RADIUS, start=(4, 16), end=(24, 16)), [line], 10)
    assert existing_line_report(along, np.array([[4.0, 16.0], [24.0, 16.0]]), np.zeros(2))["existing_line_crossing_count"] == 1
    one = overlay(make_problem(constraints=RADIUS, start=(16, 2), end=(16, 30)), [line], 10)
    both = overlay(one, [line, {"id": "existing-line-002", "points": [[2.0, 20.0], [30.0, 20.0]]}], 10)
    single = RouteEvaluator(one).evaluate(Route(np.empty((0, 2)))).objectives[3]
    union = RouteEvaluator(both).evaluate(Route(np.empty((0, 2)))).objectives[3]
    assert single < union < 2 * single


def test_reference_compiled_and_tensor_agree():
    problem = overlay(make_problem(constraints=RADIUS, start=(4, 4), end=(28, 28)), [LINE], 10)
    routes = [Route(np.empty((0, 2))), Route(np.array([[16.0, 18.5]])), Route(np.array([[16.0, 16.0]])),
              Route(np.array([[10.0, 24.0], [22.0, 8.0]]))]
    reference = RouteEvaluator(problem)
    compiled = CompiledRouteEvaluator(problem)
    tensor = TensorRouteEvaluator(problem, load_default_config().routing)
    try:
        for route, actual in zip(routes, tensor.evaluate_many(routes)):
            expected, fast = reference.evaluate(route), compiled.evaluate(route)
            assert expected.is_feasible == fast.is_feasible == actual.is_feasible
            np.testing.assert_allclose(expected.objectives, fast.objectives, atol=1e-8)
            np.testing.assert_allclose(expected.objectives, actual.objectives, atol=1e-6)
            np.testing.assert_allclose(list(expected.violations.values()), list(fast.violations.values()), atol=1e-8)
            np.testing.assert_allclose(list(expected.violations.values()), list(actual.violations.values()), atol=1e-6)
    finally:
        tensor.close()


def test_a_later_buffer_replaces_only_the_task_mask():
    base = make_problem(constraints=RADIUS, start=(16, 2), end=(16, 30))
    original = base.crossing_mask.copy()
    first = overlay(base, [LINE], 10)
    second = overlay(base, [LINE], 1)
    np.testing.assert_array_equal(base.crossing_mask, original)
    assert base.dem is first.dem is second.dem
    assert first.crossing_mask is not second.crossing_mask
    wide = RouteEvaluator(first).evaluate(Route(np.empty((0, 2)))).objectives[3]
    narrow = RouteEvaluator(second).evaluate(Route(np.empty((0, 2)))).objectives[3]
    assert narrow > 0 and narrow < wide


def test_lines_round_trip_and_old_tasks_keep_defaults(tmp_path, monkeypatch):
    task, _ = routing_task(tmp_path, monkeypatch)
    raw = task.model_dump()
    raw.pop("existing_power_lines")
    raw.pop("existing_line_crossing_buffer_m")
    loaded = RoutingRunConfig.model_validate(raw)
    assert loaded.existing_power_lines == []
    assert loaded.existing_line_crossing_buffer_m == load_default_config().routing.existing_line_crossing_buffer_m
    lines = [ExistingPowerLine.model_validate(LINE), ExistingPowerLine.model_validate(
        {"id": "existing-line-002", "points": [[4.0, 4.0], [8.0, 9.0], [12.0, 9.0]]})]
    saved = task.model_copy(update={"existing_power_lines": lines, "existing_line_crossing_buffer_m": 0}).model_dump()
    restored = RoutingRunConfig.model_validate(saved)
    assert [line.id for line in restored.existing_power_lines] == ["existing-line-001", "existing-line-002"]
    assert restored.existing_line_crossing_buffer_m == 0
    with pytest.raises(ValueError):
        RoutingRunConfig.model_validate({**saved, "existing_power_lines": [LINE, {**LINE}]})
    with pytest.raises(ValueError):
        RoutingRunConfig.model_validate({**saved, "existing_line_crossing_buffer_m": -1})
    with pytest.raises(ValueError):
        overlay(make_problem(), [{"id": "outside", "points": [[-1.0, 1.0], [2.0, 2.0]]}], 10)
