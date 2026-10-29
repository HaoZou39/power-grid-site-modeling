from dataclasses import replace

import numpy as np
import pytest

from algorithms.routing.evaluation_budget import EvaluationBudget
from algorithms.routing.pilot_reference.hybrid import rrt_seed
from algorithms.routing.pilot_reference.rrt import corridor_extension_allowed
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import Route, RoutingConstraints
from test_pilot_components import state_for
from test_routing_context import make_problem


def test_corridor_accepts_placeable_steps_and_rejects_blocked_or_long_steps():
    land = np.zeros((32, 32), dtype=np.int32)
    land[8:11, 14:18] = 2
    dem = np.zeros(land.shape)
    dem[4, 4] = np.nan
    problem = make_problem(landuse=land, dem=dem, constraints=RoutingConstraints(30, 0.4, 20, 0, 0),
        no_cross_zones=(((8, 6), (11, 6), (11, 10), (8, 10)),))
    evaluator = RouteEvaluator(problem)
    prefix = np.array([[2., 8.], [6., 8.], [12., 8.]])
    sharp = np.array([12., 14.])
    close = np.array([6.2, 8.])
    crossing = np.array([20., 8.])
    blocked = np.array([15.2, 9.2])
    missing = np.array([4.2, 4.2])
    assert corridor_extension_allowed(evaluator, prefix[:1], np.array([6., 8.]))
    assert not corridor_extension_allowed(evaluator, prefix[:1], blocked)
    assert not corridor_extension_allowed(evaluator, prefix[:1], missing)
    assert not corridor_extension_allowed(evaluator, prefix[:1], np.array([40., 8.]))
    assert corridor_extension_allowed(evaluator, prefix, sharp)
    assert not evaluator.extension_allowed(prefix, sharp)
    assert corridor_extension_allowed(evaluator, prefix, close)
    assert not evaluator.extension_allowed(prefix, close)
    assert corridor_extension_allowed(evaluator, prefix[:1], crossing)
    assert not evaluator.span_allowed(prefix[0], crossing)
    route = Route(np.vstack([prefix, sharp]))
    checked = evaluator.evaluate(route)
    assert not checked.is_feasible
    assert all(evaluator.tower_allowed(tower) for tower in route.towers)


def test_initial_rrt_uses_corridor_while_global_seed_stays_strict():
    state = state_for(config=replace(state_for().config, pilot=replace(
        state_for().config.pilot, rrt_goal_bias=1., rrt_iterations_per_span=1, rrt_min_step_ratio=0.2)))
    calls = {"strict": 0}
    original = state.adapter.extension_allowed

    def wrapped(path, target, **kwargs):
        calls["strict"] += 1
        return original(path, target, **kwargs)

    state.adapter.extension_allowed = wrapped
    assert rrt_seed(state, 0, corridor=True) is None or calls["strict"] == 0
    assert calls["strict"] == 0
    rrt_seed(state, 0, corridor=False)
    assert calls["strict"] > 0


def test_global_build_uses_the_placeable_corridor_when_asked(monkeypatch):
    from algorithms.routing.pilot_reference import hybrid
    from algorithms.routing.ranges import TowerRange
    state = state_for()
    seen = {}

    def remember(state, lower, corridor=False):
        seen["corridor"] = corridor
        return None

    monkeypatch.setattr(hybrid, "rrt_seed", remember)
    window = state.budget.window("global_search", 8)
    with pytest.raises(RuntimeError, match="no fully evaluated"):
        hybrid.build_population(state, TowerRange(0, 4, 4), window, 4, include_astar=False, include_rrt=True,
                                category="global", corridor=True)
    assert seen["corridor"] is True


def test_budget_window_can_score_without_treating_it_as_initialization():
    problem = make_problem()
    evaluator = RouteEvaluator(problem)
    budget = EvaluationBudget(evaluator, 4, 0.)
    window = budget.window("initialization", 4)
    route = Route(np.array([[8., 8.], [16., 8.]]))
    checked = window.evaluate(route)
    assert checked is not None
    assert checked.is_feasible == evaluator.evaluate(route).is_feasible
