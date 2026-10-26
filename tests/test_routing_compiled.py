from dataclasses import replace

import numpy as np
import pytest

from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
from modeling.routing.compiled_geometry import crossing_length
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.geometry import mask_intersection_length
from modeling.routing.types import Route, RoutingConstraints
from test_routing_context import make_problem


def assert_equal(problem, routes):
    reference, compiled = RouteEvaluator(problem), CompiledRouteEvaluator(problem)
    for route in routes:
        a, b = reference.evaluate(route), compiled.evaluate(route)
        assert a.is_feasible == b.is_feasible
        np.testing.assert_allclose(a.objectives, b.objectives, atol=1e-8, rtol=1e-10)
        np.testing.assert_allclose(list(a.violations.values()), list(b.violations.values()), atol=1e-10)
        np.testing.assert_allclose(a.violation, b.violation, atol=1e-10)
        for point in route.towers:
            assert reference.tower_allowed(point) == compiled.tower_allowed(point)


def test_compiled_matches_random_terrain_landuse_and_polygons():
    rng = np.random.default_rng(40)
    land = rng.integers(0, 6, (32, 32), dtype=np.int32)
    dem = rng.uniform(-50, 100, (32, 32)); dem[16, 16] = np.nan
    polygon = [[[10, 10], [15, 10], [15, 15], [10, 15]]]
    problem = make_problem(landuse=land, dem=dem, no_tower_zones=polygon, no_cross_zones=polygon)
    routes = [Route(rng.uniform(-1, 33, (i % 8, 2))) for i in range(60)]
    assert_equal(problem, routes)


@pytest.mark.parametrize("radius", [.4, 1., 3.])
def test_compiled_tangency_spacing_span_turn_and_zero_edges(radius):
    land = np.zeros((32, 32), dtype=np.int32); land[8, 10] = 2
    problem = make_problem(landuse=land, constraints=RoutingConstraints(13, radius, 90, 0, 0))
    assert_equal(problem, [Route(np.array(x).reshape(-1, 2)) for x in
        ([], [[10 - radius, 8.5]], [[10 - radius - 1e-8, 8.5]], [[2, 8]], [[15, 8]],
         [[6, 8], [6 + 2 * radius, 8]], [[5, 5], [5, 15]], [[0, 8]], [[32, 8]])])


def test_compiled_crossing_matches_exact_reference_on_shared_edges():
    rng = np.random.default_rng(2); mask = rng.random((32, 32)) < .3
    cases = [np.array([[0., 8.], [32., 8.]]), np.array([[16., 0.], [16., 32.]]),
             np.array([[0., 0.], [32., 32.]]), np.array([[32., 0.], [0., 32.]])]
    cases += [rng.uniform(0, 32, (2, 2)) for _ in range(100)]
    for a, b in cases:
        assert crossing_length(a, b, mask) == pytest.approx(mask_intersection_length(a, b, mask), abs=1e-10)


def test_compiled_search_matches_numpy_reference_trajectory():
    from algorithms.routing.search import routing_search
    from config.project_config import load_default_config
    config = replace(load_default_config().routing, popsize=8, max_evaluations=64, reference_count=2)
    problem = make_problem()
    reference = routing_search(problem, config)
    actual = routing_search(problem, replace(config, evaluation_backend="compiled_cpu"))
    assert reference.pareto_indices == actual.pareto_indices
    assert reference.evaluation_count == actual.evaluation_count
    for a, b in zip(reference.routes, actual.routes):
        np.testing.assert_array_equal(a.towers, b.towers)
