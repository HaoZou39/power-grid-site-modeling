from dataclasses import asdict, replace

import numpy as np
import pytest

from algorithms.routing.search import routing_search
from config.project_config import load_default_config
from plugins.routing_plugin import RoutingParameters
from test_routing_context import make_problem


def cpu_config():
    return replace(load_default_config().routing, evolution_backend="numpy", evaluation_backend="compiled_cpu",
                   devices=["cpu"], popsize=8, max_evaluations=64, reference_count=2)


def test_empty_pilot_strategy_reproduces_current_numpy_search():
    config = cpu_config()
    baseline = routing_search(make_problem(), config)
    migrated = routing_search(make_problem(), replace(config, search_strategy="pilot_reference"))
    assert baseline.evaluation_count == migrated.evaluation_count == 64
    assert baseline.generation_count == migrated.generation_count
    assert baseline.pareto_indices == migrated.pareto_indices
    np.testing.assert_array_equal(baseline.evaluation_indices, migrated.evaluation_indices)
    assert len(baseline.routes) == len(migrated.routes)
    for a, b, fa, fb in zip(baseline.routes, migrated.routes, baseline.evaluations, migrated.evaluations):
        np.testing.assert_array_equal(a.towers, b.towers)
        np.testing.assert_array_equal(fa.objectives, fb.objectives)
        assert fa.violations == fb.violations
    phases = migrated.execution["phase_evaluations"]
    assert sum(phases.values()) == migrated.evaluation_count
    assert phases["initialization"] == migrated.initialization_evaluations
    assert migrated.execution["search_strategy"] == "pilot_reference"


def test_nested_pilot_config_roundtrips_json_without_coercing_numbers():
    raw = asdict(cpu_config());raw["search_strategy"] = "pilot_reference"
    parsed = RoutingParameters.model_validate(raw)
    assert parsed.model_dump(mode="json") == raw
    raw["pilot"]["initialization_budget_factor"] = "2"
    with pytest.raises(ValueError):
        RoutingParameters.model_validate(raw)


@pytest.mark.parametrize("change", [{"evolution_backend": "tensor"}, {"devices": ["cuda:0"]}, {"evaluation_backend": "tensor"}])
def test_pilot_strategy_rejects_unsupported_execution(change):
    with pytest.raises(ValueError, match="pilot_reference"):
        replace(cpu_config(), search_strategy="pilot_reference", **change)


def test_budget_windows_share_total_but_enforce_per_call_limits():
    from algorithms.routing.evaluation_budget import EvaluationBudget
    class Evaluator:
        def __init__(self):self.calls = []
        def evaluate_many(self, routes, *, details):
            self.calls.extend(routes)
            return list(routes)
    evaluator = Evaluator()
    budget = EvaluationBudget(evaluator, 5, 0., clock=lambda: 1.)
    initial = budget.window("initialization", 3)
    assert initial.evaluate_many([1, 2, 3, 4]) == [1, 2, 3]
    assert initial.evaluate(9) is None
    assert budget.window("local_search", 1).evaluate(4) == 4
    assert budget.window("local_search", 1).evaluate_many([5, 6]) == [5]
    assert budget.window("offspring", 5).evaluate(7) is None
    assert evaluator.calls == [1, 2, 3, 4, 5]
    assert budget.counts == {"initialization": 3, "local_search": 2}
    assert budget.times == [1.] * 5


def test_adapter_keeps_continuous_coordinates_and_fixed_endpoints():
    from algorithms.routing.pilot_reference.adapter import PilotAdapter
    from modeling.routing.evaluator import RouteEvaluator
    from modeling.routing.types import Route
    adapter = PilotAdapter(RouteEvaluator(make_problem()), 123)
    route = Route(np.array([[12.125, 11.375]]))
    np.testing.assert_array_equal(adapter.route(adapter.path(route)).towers, route.towers)
    changed = adapter.path(route).copy();changed[0, 0] += .01
    with pytest.raises(ValueError, match="fixed endpoints"):
        adapter.route(changed)
    first, second = PilotAdapter(adapter.evaluator, 123), PilotAdapter(adapter.evaluator, 123)
    assert first.python_rng.random() == second.python_rng.random()
    np.testing.assert_array_equal(first.numpy_rng.normal(size=4), second.numpy_rng.normal(size=4))


def test_model_extension_distinguishes_fixed_endpoints_and_new_tower_footprints():
    from modeling.routing.evaluator import RouteEvaluator
    from modeling.routing.types import RoutingConstraints
    problem = make_problem(start=(2, 8), end=(28, 8), constraints=RoutingConstraints(13, 3, 90, 0, 0))
    evaluator = RouteEvaluator(problem)
    assert evaluator.extension_allowed(np.array([[2., 8.]]), np.array([15., 8.]))
    assert evaluator.extension_allowed(np.array([[2., 8.], [15., 8.]]), problem.end, fixed_endpoint=True)
    assert not evaluator.extension_allowed(np.array([[2., 8.], [15., 8.]]), np.array([16., 8.]))
    assert not evaluator.extension_allowed(np.array([[2., 8.], [15., 8.]]), np.array([8., 8.]))


def test_incremental_geometry_matches_full_route_feasibility():
    from modeling.routing.evaluator import RouteEvaluator
    from modeling.routing.types import Route, RoutingConstraints
    landuse = np.zeros((32, 32), dtype=np.int32);landuse[20:23, 20:23] = 5
    problem = make_problem(landuse=landuse, start=(2, 8), end=(28, 8),
        constraints=RoutingConstraints(13, 1, 90, 0, 0),
        no_cross_zones=[[[14, 16], [17, 16], [17, 18], [14, 18]]])
    evaluator = RouteEvaluator(problem);rng = np.random.default_rng(9)
    routes = [Route(np.array([[15., 8.]]))]
    routes += [Route(rng.uniform(0, 32, (int(rng.integers(5)), 2))) for _ in range(150)]
    feasible = []
    for route in routes:
        prefix, allowed = [problem.start], True
        for tower in route.towers:
            allowed &= evaluator.extension_allowed(prefix, tower)
            prefix.append(tower)
        allowed &= evaluator.extension_allowed(prefix, problem.end, fixed_endpoint=True)
        assert allowed == evaluator.evaluate(route).is_feasible
        feasible.append(allowed)
    assert any(feasible) and not all(feasible)
