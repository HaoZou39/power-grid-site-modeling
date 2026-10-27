from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from algorithms.routing.pilot_reference.adapter import PilotAdapter
from algorithms.routing.pilot_reference.rrt import rrt_path
from algorithms.routing.search import routing_search
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import RoutingConstraints
from pilot_reference import original_constants, original_functions
from test_pilot_integration import cpu_config
from test_routing_context import make_problem


def test_rrt_goal_extensions_and_backtracking_match_original_random_tape():
    class NumpyTape:
        random = SimpleNamespace(uniform=lambda *args: 2.)
        def __getattr__(self, name):return getattr(np, name)
    bindings = {**original_constants(), "np": NumpyTape(),
        "random": SimpleNamespace(random=lambda: 0.),
        "_coarsen_obstacle_grid": lambda *a: np.zeros((16, 32), dtype=bool),
        "_coarse_edge_is_collision_free": lambda *a: True,
        "_dedup_consecutive_points": lambda p: p,
        "_decode_coarse_path_to_fine": lambda p, *a: [(x * 6, y * 6) for x, y in p]}
    original = original_functions("path_planners.py", ["_rrt_path"], bindings)["_rrt_path"]
    expected = original((0, 0), (120, 0), None, max_iters=20, goal_bias=1.,
                        min_step=12., max_step=12., allow_astar_fallback=False)
    trace = []
    actual = rrt_path(np.array([0., 0.]), np.array([120., 0.]), np.array([192., 96.]),
        max_iters=20, goal_bias=1., min_step=12., max_step=12.,
        python_rng=SimpleNamespace(random=lambda: 0.), numpy_rng=SimpleNamespace(uniform=lambda *a: 12.),
        sample_free=lambda: pytest.fail("unexpected random target"),
        extension_allowed=lambda path, target, **kw: trace.append((path.copy(), target.copy(), kw)) or True)
    np.testing.assert_array_equal(actual, expected)
    assert len(trace) == 10 and trace[-1][2] == {"fixed_endpoint": True}


def test_rrt_uses_nearest_branch_and_rejects_an_invalid_extension():
    targets = iter([np.array([0., 4.]), np.array([4., 0.]), np.array([0., 4.])])
    trace = []
    def allowed(path, target, **kw):
        trace.append((path.copy(), target.copy()))
        return len(trace) != 1
    path = rrt_path(np.array([0., 0.]), np.array([10., 10.]), np.array([20., 20.]),
        max_iters=3, goal_bias=0., min_step=2., max_step=2.,
        python_rng=SimpleNamespace(random=lambda: 1.), numpy_rng=SimpleNamespace(uniform=lambda *a: 2.),
        sample_free=lambda: next(targets), extension_allowed=allowed)
    assert path is None
    np.testing.assert_array_equal(trace[2][0], [[0., 0.]])
    np.testing.assert_array_equal(trace[2][1], [0., 2.])
    old_targets = iter([np.array([0., 4.]), np.array([4., 0.]), np.array([0., 4.])])
    old_trace = []
    class NumpyTape:
        random = SimpleNamespace(uniform=lambda *a: 2.)
        def __getattr__(self, name):return getattr(np, name)
    def old_allowed(start, end, blocked):
        old_trace.append((start.copy(), end.copy()))
        return len(old_trace) != 1
    bindings = {**original_constants(), "RRT_CELL_SIZE": 1, "np": NumpyTape(),
        "random": SimpleNamespace(random=lambda: 1.), "_sample_free_point": lambda _: next(old_targets),
        "_coarsen_obstacle_grid": lambda *a: np.zeros((20, 20), dtype=bool),
        "_coarse_edge_is_collision_free": old_allowed}
    original = original_functions("path_planners.py", ["_rrt_path"], bindings)["_rrt_path"]
    assert original((0, 0), (10, 10), None, max_iters=3, goal_bias=0., min_step=2., max_step=2.,
                    allow_astar_fallback=False) == []
    np.testing.assert_array_equal([(p[-1], t) for p, t in trace], old_trace)


def test_rrt_cancellation_and_no_free_target_terminate():
    args = dict(max_iters=5, goal_bias=0., min_step=1., max_step=2.,
        python_rng=SimpleNamespace(random=lambda: 1.), numpy_rng=SimpleNamespace(uniform=lambda *a: 1.),
        sample_free=lambda: None, extension_allowed=lambda *a, **kw: pytest.fail("no target"))
    assert rrt_path(np.array([0., 0.]), np.array([9., 9.]), np.array([10., 10.]), **args) is None
    def cancel():raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        rrt_path(np.array([0., 0.]), np.array([9., 9.]), np.array([10., 10.]), checkpoint=cancel, **args)


def test_rrt_seed_is_injected_and_full_constraints_remain_authoritative():
    cfg = cpu_config();pilot = replace(cfg.pilot, enabled_mechanisms=["rrt"], rrt_goal_bias=1.)
    cfg = replace(cfg, search_strategy="pilot_reference", pilot=pilot, max_evaluations=96)
    problem = make_problem(constraints=RoutingConstraints(10., .4, 90., 0., 0.))
    result = routing_search(problem, cfg)
    stats = result.execution["pilot_initialization"]
    assert stats["rrt_unique_feasible_seeds"] > 0
    assert stats["rrt_successes"] >= stats["rrt_unique_feasible_seeds"]
    assert stats["edge_checks"] > 0
    assert result.initialization_evaluations <= cfg.pilot.initialization_budget_factor * cfg.popsize
    assert sum(result.execution["phase_evaluations"].values()) == result.evaluation_count == 96
    for route, value in zip(result.routes, result.evaluations):
        if value.is_feasible:assert RouteEvaluator(problem).evaluate(route).is_feasible
    repeat = routing_search(problem, cfg)
    for a, b in zip(result.routes, repeat.routes):np.testing.assert_array_equal(a.towers, b.towers)
    assert stats == repeat.execution["pilot_initialization"]


def test_standard_strategy_rejects_a_nonempty_pilot_mechanism_list():
    cfg = cpu_config()
    with pytest.raises(ValueError, match="pilot_reference"):
        replace(cfg, pilot=replace(cfg.pilot, enabled_mechanisms=["rrt"]))


@pytest.mark.parametrize("change", [{"enabled_mechanisms": ["astar"]}, {"enabled_mechanisms": ["rrt", "rrt"]},
    {"rrt_iterations_per_span": True}, {"rrt_goal_bias": float("nan")}, {"rrt_min_step_ratio": 0.},
    {"rrt_seed_min": 1000}])
def test_rrt_rejects_invalid_research_parameters(change):
    with pytest.raises(ValueError):
        replace(cpu_config().pilot, **change)


def test_saved_round1_parameters_resolve_new_defaults_but_project_config_is_strict():
    from dataclasses import asdict
    from config.project_config import parse_pilot_config
    from plugins.routing_plugin import RoutingParameters
    cfg = cpu_config();old = asdict(cfg.pilot)
    old = {k: v for k, v in old.items() if not k.startswith("rrt_")}
    restored = RoutingParameters.model_validate({"pilot": old})
    assert restored.pilot == cfg.pilot
    with pytest.raises(ValueError, match="fields mismatch"):
        parse_pilot_config(old)


def test_rrt_fixed_connections_can_touch_blocked_land_while_spans_cross_water():
    landuse = np.zeros((32, 32), dtype=np.int32);landuse[:, 10:20] = 5
    landuse[8, 2] = landuse[8, 28] = 2
    problem = make_problem(landuse=landuse, constraints=RoutingConstraints(30., .4, 90., 0., 0.))
    adapter = PilotAdapter(RouteEvaluator(problem), 1)
    path = rrt_path(problem.start, problem.end, np.array([32., 32.]), max_iters=1, goal_bias=1.,
        min_step=30., max_step=30., python_rng=adapter.python_rng, numpy_rng=adapter.numpy_rng,
        sample_free=lambda: None, extension_allowed=adapter.extension_allowed)
    np.testing.assert_array_equal(path, [problem.start, problem.end])
    assert adapter.evaluator.evaluate(adapter.route(path)).is_feasible
