from dataclasses import replace

import numpy as np

from algorithms.routing.search import routing_search
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator, tower_cache_budget
from modeling.routing.types import Route
from test_routing_context import make_problem


def test_exact_tower_cache_preserves_every_value_and_is_bounded():
    rng = np.random.default_rng(28)
    problem = make_problem(dem=rng.uniform(-10, 100, (32, 32)))
    plain = RouteEvaluator(problem)
    cached = RouteEvaluator(problem).cache_tower_checks(4096)
    assert cached._tower_cache_capacity > 0
    for _ in range(3):
        for route in [Route(np.array([[8., 8.], [16., 8.]])), Route(rng.uniform(1, 31, (3, 2)))]:
            a, b = plain.evaluate(route, report=True), cached.evaluate(route, report=True)
            np.testing.assert_array_equal(a.objectives, b.objectives)
            assert a.violations == b.violations and a.spans == b.spans
            np.testing.assert_array_equal(a.elevations, b.elevations)
            assert a.tower_slopes_deg == b.tower_slopes_deg
            assert len(cached._tower_cache) <= cached._tower_cache_capacity
    cached.cache_tower_checks(0)
    assert not cached._tower_cache and cached._tower_cache_capacity == 0
    assert tower_cache_budget(problem, 0) == 0


def test_tower_cache_does_not_change_fixed_seed_search():
    cfg = replace(load_default_config().routing, popsize=8, max_evaluations=128, reference_count=2)
    problem = make_problem()
    first = routing_search(problem, replace(cfg, context_cache_mib=0))
    second = routing_search(problem, cfg)
    assert first.pareto_indices == second.pareto_indices
    for a, b, x, y in zip(first.routes, second.routes, first.evaluations, second.evaluations):
        np.testing.assert_array_equal(a.towers, b.towers)
        np.testing.assert_array_equal(x.objectives, y.objectives)
