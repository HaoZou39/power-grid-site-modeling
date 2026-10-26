from dataclasses import replace
import numpy as np

from algorithms.routing.initialization import TowerRange, distribute_towers, initialize_routes, minimum_towers, prune_reference
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import Route, RoutingConstraints
from test_routing_context import make_problem


def test_straight_lower_bound_and_direct_connection():
    problem = make_problem(constraints=RoutingConstraints(10, .4, 90, 0, 0))
    assert minimum_towers(problem) == 2
    route = distribute_towers(np.vstack([problem.start, problem.end]), 10)
    assert len(route.towers) == 2
    assert RouteEvaluator(problem).evaluate(route).is_feasible
    direct = make_problem()
    assert minimum_towers(direct) == 0


def test_references_can_cross_water_and_avoid_only_no_cross_zone():
    config = replace(load_default_config().routing, navigation_step_m=2)
    landuse = np.zeros((32, 32), dtype=np.int32); landuse[:, 14:17] = 5
    evaluator = RouteEvaluator(make_problem(landuse=landuse, constraints=RoutingConstraints(10, .4, 90, 0, 0)))
    initial = initialize_routes(evaluator, config, np.random.default_rng(config.seed), evaluator.evaluate)
    assert initial.valid_references > 0
    assert any(evaluator.evaluate(route).is_feasible and evaluator.evaluate(route).objectives[3] > 0 for route in initial.routes)
    evaluator = RouteEvaluator(make_problem(no_cross_zones=[[[14, 5], [17, 5], [17, 11], [14, 11]]]))
    initial = initialize_routes(evaluator, config, np.random.default_rng(config.seed), evaluator.evaluate)
    assert initial.valid_references > 0


def test_pruning_does_not_discard_a_crossing_tradeoff():
    landuse = np.zeros((32, 32), dtype=np.int32); landuse[7:10, 14:17] = 2
    evaluator = RouteEvaluator(make_problem(landuse=landuse))
    route = Route(np.array([[16., 15.]]))
    result = evaluator.evaluate(route)
    assert result.is_feasible and result.objectives[3] == 0
    pruned, _ = prune_reference(route, result, evaluator.evaluate, evaluator.problem)
    assert len(pruned.towers) == 1


def test_failed_references_stay_infeasible_and_reproduce():
    config = load_default_config().routing
    evaluator = RouteEvaluator(make_problem(landuse=np.full((32, 32), 2, dtype=np.int32),
        constraints=RoutingConstraints(10, .4, 90, 0, 0)))
    first = initialize_routes(evaluator, config, np.random.default_rng(config.seed), evaluator.evaluate)
    second = initialize_routes(evaluator, config, np.random.default_rng(config.seed), evaluator.evaluate)
    assert first.valid_references == 0
    assert first.upper == first.lower
    for a, b in zip(first.routes, second.routes):
        np.testing.assert_array_equal(a.towers, b.towers)
        assert not evaluator.evaluate(a).is_feasible


def test_initial_upper_is_expandable_even_when_straight_route_is_feasible():
    config = load_default_config().routing
    bounds = TowerRange(0, 0, 0)
    assert not bounds.expand(0, config)
    assert bounds.expand(config.expansion_interval, config)
    assert bounds.upper == config.expansion_step
    assert bounds.initial_upper == 0 and bounds.lower == 0
