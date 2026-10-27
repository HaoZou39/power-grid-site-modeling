from dataclasses import replace

import numpy as np
import pytest

from algorithms.routing.navigation import tower_navigation_route
from algorithms.routing.search import routing_search
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import RoutingConstraints
from test_routing_context import make_problem


def test_navigation_crosses_water_between_legal_towers():
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[:, 14:17] = 5
    evaluator = RouteEvaluator(make_problem(landuse=landuse, constraints=RoutingConstraints(8, .4, 100, 0, 0)))
    route = tower_navigation_route(evaluator, 2)
    assert route is not None
    result = evaluator.evaluate(route)
    assert result.is_feasible and result.objectives[3] > 0


def test_navigation_detours_when_water_is_wider_than_a_span():
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[:24, 12:20] = 5
    evaluator = RouteEvaluator(make_problem(landuse=landuse, constraints=RoutingConstraints(6, .4, 100, 0, 0)))
    route = tower_navigation_route(evaluator, 2)
    assert route is not None and route.towers[:, 1].max() > 24
    assert evaluator.evaluate(route).is_feasible
    repeated = tower_navigation_route(evaluator, 2)
    np.testing.assert_array_equal(route.towers, repeated.towers)


def test_navigation_respects_no_cross_regions_and_reports_failure_without_claiming_impossibility():
    evaluator = RouteEvaluator(make_problem(no_cross_zones=[[[0, 0], [32, 0], [32, 32], [0, 32]]]))
    assert tower_navigation_route(evaluator, 2) is None


def test_navigation_keeps_connection_points_external_and_handles_large_footprints():
    evaluator = RouteEvaluator(make_problem(start=(2, 8), end=(28, 8), constraints=RoutingConstraints(13, 3, 100, 0, 0)))
    route = tower_navigation_route(evaluator, 2)
    assert route is not None and evaluator.evaluate(route).is_feasible
    np.testing.assert_array_equal(route.points(evaluator.problem.start, evaluator.problem.end)[[0, -1]], [[2, 8], [28, 8]])


def test_navigation_accepts_cancellation():
    evaluator = RouteEvaluator(make_problem(constraints=RoutingConstraints(5, .4, 100, 0, 0)))
    def cancel():
        raise RuntimeError("cancel navigation")
    with pytest.raises(RuntimeError, match="cancel navigation"):
        tower_navigation_route(evaluator, 2, checkpoint=cancel)


def test_large_span_keeps_navigation_bounded_by_the_scene():
    evaluator = RouteEvaluator(make_problem(constraints=RoutingConstraints(10000, .4, 100, 0, 0),
        no_cross_zones=[[[0, 0], [32, 0], [32, 32], [0, 32]]]))
    assert tower_navigation_route(evaluator, 2) is None


@pytest.mark.parametrize("backend", ["numpy", "tensor"])
def test_navigation_seed_reaches_evolution_with_original_budget(backend):
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[:24, 12:20] = 5
    problem = make_problem(landuse=landuse, constraints=RoutingConstraints(6, .4, 100, 0, 0))
    config = replace(load_default_config().routing, evolution_backend=backend, evaluation_backend="reference",
                     devices=["cpu"], popsize=8, max_evaluations=64, reference_count=2,
                     repair_attempts=1, navigation_step_m=2)
    result = routing_search(problem, config)
    assert result.pareto_indices and result.evaluation_count == config.max_evaluations
    for index in result.pareto_indices:
        assert RouteEvaluator(problem).evaluate(result.routes[index]).is_feasible
