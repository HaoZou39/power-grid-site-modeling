from dataclasses import replace
import numpy as np
import pytest
from algorithms.routing.search import routing_search
from algorithms.routing.initialization import TowerRange
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import RoutingConstraints
from test_pilot_integration import cpu_config
from test_routing_context import make_problem


def config(mode, *, rrt=True, budget=256):
    base = cpu_config()
    return replace(base, search_strategy="pilot_reference", max_generations=2, max_evaluations=budget,
        pilot=replace(base.pilot, initialization_mode=mode, enabled_mechanisms=["rrt"] if rrt else [],
                      rrt_goal_bias=1.))


def test_pruned_rrt_only_admits_final_processed_seeds(monkeypatch):
    problem = make_problem(constraints=RoutingConstraints(13., .4, 90., 0., 0.))
    monkeypatch.setattr("algorithms.routing.pilot_reference.rrt.rrt_path",
        lambda *a, **kw: np.vstack([problem.start, [8., 8.], [14., 8.], [20., 8.], problem.end]))
    result = routing_search(problem, config("pruned"))
    stats = result.execution["pilot_initialization"]
    assert stats["rrt_removed_towers"] > 0
    assert all(after <= before for before, after in zip(stats["rrt_towers_before"], stats["rrt_towers_after"]))
    assert stats["initial_population_size"] <= len(stats["rrt_towers_after"]) + 4
    assert result.generation_count == config("pruned").max_generations
    assert sum(result.execution["phase_evaluations"].values()) == result.evaluation_count


@pytest.mark.parametrize("rrt", [False, True])
def test_balanced_initialization_fills_actual_population_and_limits_rrt_share(rrt):
    problem = make_problem(constraints=RoutingConstraints(13., .4, 90., 0., 0.))
    cfg = config("balanced", rrt=rrt)
    result = routing_search(problem, cfg)
    stats = result.execution["pilot_initialization"]
    assert stats["initial_population_size"] == cfg.popsize
    assert stats["initial_rrt_slots"] <= cfg.popsize // cfg.pilot.rrt_population_divisor
    assert stats["initial_unique_population"] + stats["initial_reused_slots"] == cfg.popsize
    assert result.initialization_evaluations <= cfg.pilot.initialization_budget_factor * cfg.popsize
    for route, checked in zip(result.routes, result.evaluations):
        if checked.is_feasible:assert RouteEvaluator(problem).evaluate(route).is_feasible
    repeat = routing_search(problem, cfg)
    assert len(result.routes) == len(repeat.routes)
    for a, b in zip(result.routes, repeat.routes):np.testing.assert_array_equal(a.towers, b.towers)


def test_bounded_expansion_preserves_seed_towers_without_inflating_probe_anchor():
    bounds = TowerRange(2, 10, 10, probe_upper=4)
    cfg = load_default_config().routing
    assert bounds.expand(cfg.expansion_interval, cfg)
    assert bounds.upper == 10 and bounds.probe_upper == 4 + cfg.expansion_step
    for generation in range(2 * cfg.expansion_interval, 12 * cfg.expansion_interval, cfg.expansion_interval):
        assert bounds.expand(generation, cfg)
    assert bounds.upper == bounds.probe_upper


def test_bounded_search_records_reference_anchor_and_preserves_budget():
    result = routing_search(make_problem(), config("bounded"))
    stats = result.execution["pilot_initialization"]
    assert stats["initial_population_size"] == cpu_config().popsize
    assert stats["reference_upper"] <= result.initial_upper
    assert result.generation_count == config("bounded").max_generations


def test_balanced_tiny_budget_records_reuse_without_inventing_evaluations():
    cfg = config("balanced", budget=8)
    result = routing_search(make_problem(), cfg)
    stats = result.execution["pilot_initialization"]
    assert stats["initial_population_size"] == cfg.popsize
    assert stats["initial_reused_slots"] > 0
    assert result.generation_count == cfg.max_generations


def test_missing_historical_mode_resolves_legacy_and_unknown_mode_is_rejected():
    from dataclasses import asdict
    from plugins.routing_plugin import RoutingParameters
    old = asdict(cpu_config().pilot);old.pop("initialization_mode")
    assert RoutingParameters.model_validate({"pilot": old}).pilot.initialization_mode == "legacy"
    with pytest.raises(ValueError, match="initialization mode"):
        replace(cpu_config().pilot, initialization_mode="unknown")


def test_seed_pruning_retains_a_detour_when_deleting_would_increase_crossing():
    from algorithms.routing.initialization import prune_reference
    from modeling.routing.types import Route
    landuse = np.zeros((32, 32), dtype=np.int32);landuse[7:10, 10:20] = 5
    problem = make_problem(landuse=landuse, constraints=RoutingConstraints(30., .4, 90., 0., 0.))
    evaluator = RouteEvaluator(problem);route = Route(np.array([[15., 14.]]));before = evaluator.evaluate(route)
    assert before.is_feasible and before.objectives[3] == 0
    after, checked = prune_reference(route, before, evaluator.evaluate, problem)
    np.testing.assert_array_equal(after.towers, route.towers)
    np.testing.assert_array_equal(checked.objectives, before.objectives)
