from copy import deepcopy

import pytest

from experiments.validate_routing_refactor import compare_snapshots


def snapshot():
    return {"kind": "routing_refactor_synthetic", "schema": {"version": 1}, "cases": {
        "cpu": {"evaluations": [{"xy": "coordinates", "source": "initialization"}],
                "selection": ["parent"], "random_states": ["stream"], "bounds": [0, 1, 2]}}}


def test_refactor_comparison_checks_complete_candidate_and_execution_contract():
    before = snapshot()
    assert compare_snapshots(before, deepcopy(before)) == {"matched": True, "cases": 1, "complete_evaluations": 1}
    for field in ["evaluations", "selection", "random_states", "bounds"]:
        after = deepcopy(before);after["cases"]["cpu"][field] = []
        with pytest.raises(AssertionError, match=field):
            compare_snapshots(before, after)
    after = deepcopy(before);after["schema"] = {}
    with pytest.raises(AssertionError, match="schema"):
        compare_snapshots(before, after)


def test_phase_windows_share_one_limit_and_offer_readonly_history():
    from algorithms.routing.evaluation_budget import EvaluationBudget

    class Evaluator:
        def evaluate_many(self, routes, *, details):
            return [item * 2 for item in routes]

    ledger = EvaluationBudget(Evaluator(), 3, 0., clock=lambda: 1.)
    seeds, evolution = ledger.window("initialization", 2), ledger.window("offspring", 3)
    assert seeds.evaluate_many([1, 2, 3]) == [2, 4]
    assert seeds.remaining == 0
    assert evolution.remaining == 1
    history = seeds.history
    assert isinstance(history, tuple)
    assert evolution.evaluate(4) == 8
    assert evolution.evaluate(5) is None
    assert history == ((1, 2), (2, 4))
    assert ledger.history == ((1, 2), (2, 4), (4, 8))
    assert ledger.counts == {"initialization": 2, "offspring": 1}


def test_evaluation_budget_reuses_duplicate_route_values_without_changing_budget():
    import numpy as np
    from algorithms.routing.evaluation_budget import EvaluationBudget
    from modeling.routing.types import Route

    class Evaluator:
        def __init__(self):
            self.calls = []

        def evaluate_many(self, routes, *, details):
            self.calls.append(list(routes))
            return [object() for _ in routes]

    evaluator = Evaluator()
    route = Route(np.array([[8., 8.]]))
    ledger = EvaluationBudget(evaluator, 3, 0., clock=lambda: 1.)
    values = ledger.window("offspring", 3).evaluate_many([route, Route(route.towers), route])

    assert len(evaluator.calls) == 1
    assert len(evaluator.calls[0]) == 1
    assert len(values) == len(ledger.records) == 3
    assert values[0] is values[1] is values[2]
    assert ledger.cache_hits == 2


def test_python_composition_replaces_initializer_and_evolution_independently():
    from dataclasses import replace
    from functools import partial
    import numpy as np
    from algorithms.routing.components import SearchComponents
    from algorithms.routing.initial_population import initialize_population
    from algorithms.routing.numpy_search import evolve
    from algorithms.routing.search import run_with_components
    from config.project_config import load_default_config
    from test_routing_context import make_problem

    config = replace(load_default_config().routing, evolution_backend="numpy", devices=["cpu"],
                     popsize=4, max_evaluations=8 * load_default_config().routing.pilot.initialization_budget_factor + 16, reference_count=2,
                     search_strategy="pilot_reference", pilot=replace(load_default_config().routing.pilot,
                     initialization_mode="balanced", enabled_mechanisms=[]))
    initial_histories, calls = [], []

    def initializer(evaluator, config, rng, budget, report):
        result = initialize_population(evaluator, config, rng, budget, report)
        initial_histories.append([r.towers.tobytes() for r, _ in budget.history])
        return result

    def variation(first, second, evaluator, config, rng, lower, upper, *, target_count):
        calls.append(first.towers.copy())
        return first

    problem = make_problem()
    run_with_components(problem, config, SearchComponents(initializer, evolve))
    modified = run_with_components(problem, config, SearchComponents(initializer, partial(evolve, variation=variation)))
    assert calls
    assert initial_histories[0] == initial_histories[1]
    assert modified.evaluation_count == config.max_evaluations
    assert all(np.isfinite(route.towers).all() for route in modified.routes)


@pytest.mark.parametrize("action,name", [(0, "move"), (1, "insert"), (2, "delete"), (3, "crossover")])
def test_each_numpy_operator_is_replaceable_without_changing_the_driver(action, name):
    from dataclasses import replace
    import numpy as np
    from algorithms.routing.operators import numpy_operators, offspring
    from config.project_config import load_default_config
    from modeling.routing.evaluator import RouteEvaluator
    from modeling.routing.types import Route
    from test_routing_context import make_problem

    config, evaluator = load_default_config().routing, RouteEvaluator(make_problem())
    seed = next(seed for seed in range(100) if np.random.default_rng(seed).integers(4) == action)
    first, second = Route(np.array([[8., 8.], [18., 8.]])), Route(np.array([[12., 12.]]))
    operators, calls = numpy_operators(), []
    original = getattr(operators, name)

    def replacement(*args):
        calls.append(name)
        return original(*args) + .01

    expected = offspring(first, second, evaluator, config, np.random.default_rng(seed), 0, 5)
    actual = offspring(first, second, evaluator, config, np.random.default_rng(seed), 0, 5,
                       operators=replace(operators, **{name: replacement}))
    assert calls == [name]
    assert not np.array_equal(expected.towers, actual.towers)


def test_trial_generation_reuses_its_evaluation_and_obeys_the_shared_budget():
    from dataclasses import replace
    from functools import partial
    from algorithms.routing.components import SearchComponents
    from algorithms.routing.initial_population import initialize_population
    from algorithms.routing.numpy_search import evolve
    from algorithms.routing.search import run_with_components
    from algorithms.routing.types import EvaluatedCandidate
    from config.project_config import load_default_config
    from test_routing_context import make_problem

    config = replace(load_default_config().routing, evolution_backend="numpy", devices=["cpu"],
                     popsize=4, max_evaluations=31, reference_count=2)
    used = []

    def trials(first, second, evaluator, config, rng, lower, upper, *, target_count, window, variation):
        route = first
        checked = None
        for candidate in [first, second]:
            value = window.evaluate(candidate)
            if value is None:
                break
            used.append(candidate)
            route, checked = candidate, value
        return None if checked is None else EvaluatedCandidate(route, checked)

    result = run_with_components(make_problem(), config,
        SearchComponents(initialize_population, partial(evolve, generate=trials)))
    assert len(used) > config.popsize
    assert len(used) + result.initialization_evaluations == config.max_evaluations
    assert result.execution["phase_evaluations"]["offspring"] == len(used)


def test_routing_layers_do_not_import_application_adapters():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    paths = [*root.joinpath("algorithms/routing").rglob("*.py"),
             *root.joinpath("modeling/routing").rglob("*.py"), root / "config/routing_task.py"]
    for path in paths:
        if "vendor" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""] if node.level == 0 else []
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            assert all(module.split(".")[0] not in {"backend", "worker", "frontend", "plugins", "experiments"}
                       for module in modules), path
    imports = ast.parse((root / "experiments/routing_output.py").read_text())
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "algorithms.routing.search"
                   for node in ast.walk(imports))


@pytest.mark.parametrize("action,name", [(0, "move"), (1, "insert"), (2, "delete"), (3, "crossover")])
def test_each_tensor_operator_keeps_its_batch_replacement_seam(action, name):
    from dataclasses import replace
    import numpy as np
    import torch
    from algorithms.routing.tensor_operators import tensor_operators, vary, TowerBatch
    from modeling.routing.types import Route

    first = TowerBatch.from_routes([Route(np.array([[8., 8.], [18., 8.]]))], "cpu", 5)
    second = TowerBatch.from_routes([Route(np.array([[12., 12.]]))], "cpu", 5)
    operators, calls = tensor_operators(), []
    original = getattr(operators, name)

    def replacement(*args):
        calls.append(args[0].shape[0])
        result = original(*args)
        return (result[0] + .01, result[1]) if isinstance(result, tuple) else result + .01

    kwargs = dict(start=torch.tensor([2., 8.]), end=torch.tensor([28., 8.]), lower=0, upper=5,
                  sigma=1., radius=.4, size=(32, 32), generator=torch.Generator().manual_seed(1),
                  actions=torch.tensor([action]), locations=torch.tensor([.5]),
                  cuts=torch.tensor([[.5, .5]]), noise=torch.zeros((1, 2)))
    expected = vary(first, second, **kwargs)
    actual = vary(first, second, **kwargs, operators=replace(operators, **{name: replacement}))
    assert calls == [1]
    assert not torch.equal(expected.xy, actual.xy)
    assert torch.equal(expected.counts, actual.counts)


@pytest.mark.parametrize("backend", ["numpy", "tensor"])
def test_native_selection_and_range_policy_can_be_replaced(backend):
    from dataclasses import replace
    from functools import partial
    from algorithms.routing.components import SearchComponents, tensor_driver
    from algorithms.routing.initial_population import initialize_population
    from algorithms.routing.numpy_search import evolve
    from algorithms.routing.search import run_with_components
    from algorithms.routing.selection import numpy_selection, tensor_selection
    from config.project_config import load_default_config
    from test_routing_context import make_problem

    config = replace(load_default_config().routing, evolution_backend=backend, devices=["cpu"],
                     popsize=4, max_evaluations=32, reference_count=2, expansion_interval=1)
    selection = numpy_selection() if backend == "numpy" else tensor_selection()
    calls = []

    def parents(*args):
        calls.append("parents")
        return selection.parents(*args)

    driver = evolve if backend == "numpy" else tensor_driver
    result = run_with_components(make_problem(), config, SearchComponents(initialize_population,
        partial(driver, selection=replace(selection, parents=parents), range_policy=lambda *args: False)))
    assert calls
    assert result.generation_count > 0
    assert result.final_upper == result.initial_upper
    assert not result.expansions


def test_fixed_seed_initializer_is_a_complete_replacement():
    from dataclasses import replace
    import numpy as np
    from algorithms.common.nsga2 import Individual
    from algorithms.routing.components import SearchComponents
    from algorithms.routing.initial_population import InitialPopulation
    from algorithms.routing.numpy_search import evolve
    from algorithms.routing.ranges import TowerRange
    from algorithms.routing.search import run_with_components
    from config.project_config import load_default_config
    from modeling.routing.types import Route
    from test_routing_context import make_problem

    def initialize(evaluator, config, rng, budget, report):
        route = Route(np.empty((0, 2)))
        checked = budget.window("initialization", 1).evaluate(route)
        return InitialPopulation([Individual(route.towers, checked.objectives, checked.violation)],
                                 TowerRange(0, 0, 0), None, [(route, checked)])

    config = replace(load_default_config().routing, evolution_backend="numpy", devices=["cpu"],
                     popsize=4, max_evaluations=24)
    result = run_with_components(make_problem(), config, SearchComponents(initialize, evolve))
    assert result.initialization_evaluations == 1
    assert result.initial_upper == 0
    assert result.generation_count > 0
    assert result.evaluation_count == config.max_evaluations


@pytest.mark.parametrize("backend", ["numpy", "tensor"])
def test_driver_rejects_a_mismatched_backend(backend):
    from dataclasses import replace
    from algorithms.routing.components import SearchComponents, tensor_driver
    from algorithms.routing.initial_population import initialize_population
    from algorithms.routing.numpy_search import evolve
    from algorithms.routing.search import run_with_components
    from config.project_config import load_default_config
    from test_routing_context import make_problem

    config = replace(load_default_config().routing, evolution_backend=backend, devices=["cpu"],
                     popsize=4, max_evaluations=24, reference_count=2)
    wrong_driver = tensor_driver if backend == "numpy" else evolve
    with pytest.raises(ValueError, match="requires evolution_backend"):
        run_with_components(make_problem(), config, SearchComponents(initialize_population, wrong_driver))


def test_tensor_driver_uses_initializer_candidates_instead_of_all_trials():
    from dataclasses import replace
    from functools import partial
    import numpy as np
    import torch
    from algorithms.common.nsga2 import Individual
    from algorithms.routing.components import SearchComponents, tensor_driver
    from algorithms.routing.initial_population import InitialPopulation
    from algorithms.routing.ranges import TowerRange
    from algorithms.routing.search import run_with_components
    from config.project_config import load_default_config
    from modeling.routing.types import Route
    from test_routing_context import make_problem

    chosen = Route(np.array([[8., 8.]]))
    discarded = Route(np.array([[10., 9.]]))
    calls = []

    def initialize(evaluator, config, rng, budget, report):
        values = budget.window("initialization", 2).evaluate_many([chosen, discarded])
        return InitialPopulation([Individual(chosen.towers, values[0].objectives, values[0].violation)],
                                 TowerRange(1, 1, 1), None, [(chosen, values[0])])

    def variation(first, second, **kwargs):
        expected = first.xy.new_tensor(chosen.towers).expand(len(first.xy), -1, -1)
        assert torch.equal(first.xy, expected)
        assert torch.equal(second.xy, expected)
        calls.append(len(first.xy))
        return first

    config = replace(load_default_config().routing, evolution_backend="tensor", devices=["cpu"],
                     popsize=4, max_evaluations=8, expansion_interval=100)
    result = run_with_components(make_problem(), config,
        SearchComponents(initialize, partial(tensor_driver, variation=variation)))
    assert calls == [4, 2]
    assert result.initialization_evaluations == 2
    assert result.evaluation_count == 8
    assert any(np.array_equal(r.towers, discarded.towers) for r in result.routes)


def test_benchmark_comparison_ignores_only_documented_runtime_fields(tmp_path):
    import json
    import numpy as np
    from experiments.validate_routing_refactor import compare_benchmarks

    old, new = tmp_path / "before", tmp_path / "after"
    files = []
    for root, elapsed in [(old, 1.), (new, 2.)]:
        run = root / "case"
        run.mkdir(parents=True)
        saved = run / "candidates.npz"
        np.savez(saved, xy=np.array([[1., 2.]]), objectives=np.ones((1, 4)),
                 evaluation_indices=np.array([3]), evaluation_times_s=np.array([elapsed]))
        row = dict(seed=1, elapsed_s=elapsed, candidate_file=str(saved), evaluation_count=3,
                   n_candidates=1, execution={"phase_evaluations": {"initialization": 3}, "timings": {"total": elapsed}})
        (run / "report.json").write_text(json.dumps({"rows": [row]}))
        files.append(saved)
    assert compare_benchmarks(old, new)["complete_evaluations_per_version"] == 3
    np.savez(files[1], xy=np.array([[2., 2.]]), objectives=np.ones((1, 4)),
             evaluation_indices=np.array([3]), evaluation_times_s=np.array([2.]))
    with pytest.raises(AssertionError, match="candidate artifact differs"):
        compare_benchmarks(old, new)


def test_expansion_probe_uses_the_same_injected_repair_as_other_children():
    from dataclasses import replace
    from functools import partial
    import numpy as np
    from algorithms.common.nsga2 import Individual
    from algorithms.routing.components import SearchComponents, tensor_driver
    from algorithms.routing.initial_population import InitialPopulation
    from algorithms.routing.ranges import TowerRange
    from algorithms.routing.search import run_with_components
    from config.project_config import load_default_config
    from modeling.routing.types import Route
    from test_routing_context import make_problem
    calls = []
    def initialize(evaluator, config, rng, budget, report):
        route = Route(np.array([[15.,8.]]))
        value = budget.window("initialization",1).evaluate(route)
        return InitialPopulation([Individual(route.towers,value.objectives,value.violation)],
                                 TowerRange(1,1,1),None,[(route,value)])
    def repair(route, *args):
        calls.append(route)
        towers = route.towers.copy()
        towers[:,1] = 12.
        return Route(towers)
    cfg = replace(load_default_config().routing, evolution_backend="tensor", evaluation_backend="reference",
                  devices=["cpu"],popsize=4,max_evaluations=5,expansion_interval=1,expansion_step=1)
    result = run_with_components(make_problem(),cfg,SearchComponents(initialize,partial(tensor_driver,repair=repair)))
    assert len(calls) == 4
    assert result.execution["phase_evaluations"]["offspring"] == 4
    assert all(np.all(route.towers[:,1] == 12.) for route in result.routes[1:])
