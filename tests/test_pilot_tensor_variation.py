from dataclasses import replace

import numpy as np
import pytest
import torch

from algorithms.routing.pilot_reference.tensor_runtime import TensorRunState
from algorithms.routing.pilot_reference.tensor_geometry import PilotTensorGeometry
from algorithms.routing.pilot_reference.tensor_population import TensorPopulation
from algorithms.routing.pilot_reference import tensor_variation as tensor
from algorithms.routing.pilot_reference import variation, refinement, mutation
from algorithms.routing.ranges import TowerRange
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.tensor_queries import TensorRouteGeometry
from modeling.routing.tensor_types import TowerBatch
from modeling.routing.types import Route
from test_pilot_components import state_for
from test_pilot_tensor_runtime import native_config
from test_routing_context import make_problem


@pytest.fixture(params=["cpu", "cuda:0"])
def tensor_state(request):
    device = request.param
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    host = state_for(limit=4096)
    engine = TensorRouteEvaluator(host.problem, native_config(device))
    host.budget.evaluator = engine
    geometry = PilotTensorGeometry(TensorRouteGeometry(engine), host.config)
    state = TensorRunState(host, geometry, torch.Generator(device=device).manual_seed(123))
    try:
        yield state
    finally:
        geometry.close()
        engine.close()


def scored(state, paths):
    routes = [Route(np.asarray(path, dtype=float)) for path in paths]
    return state.score(TowerBatch.from_routes(routes, state.device), state.budget.window("initialization", len(paths)))


def record_decisions(state, start, *, native):
    decisions = []
    compare = state.better
    def checked(first, second, **kwargs):
        accepted = compare(first, second, **kwargs)
        if native:
            assert not bool((accepted & (second.ids < 0)).any())
            for index, take in zip(second.ids.tolist(), accepted.tolist()):
                if index >= start:
                    decisions.append(take)
        elif second.evaluation_index >= start:
            decisions.append(accepted)
        return accepted
    state.better = checked
    return decisions


@pytest.mark.parametrize("name", ["crossover", "shorten", "smooth"])
def test_deterministic_operator_matches_cpu_requests_and_acceptance(tensor_state, name):
    state = tensor_state
    genes = [np.array([[8., 12.], [18., 11.]]), np.array([[10., 7.], [20., 9.]])]
    parents = scored(state, genes)
    cpu = state_for()
    first, second = [cpu.score(Route(g), cpu.budget.window("initialization", 1)) for g in genes]
    start = len(state.budget.records)
    cpu_decisions = record_decisions(cpu, 2, native=False)
    gpu_decisions = record_decisions(state, start, native=True)
    window = state.budget.window("offspring", 200)
    if name == "crossover":
        expected = variation.crossover(first, second, cpu, cpu.budget.window("offspring", 200))
        actual = tensor.crossover(parents.take([0]), parents.take([1]), state, window)
    else:
        expected = getattr(refinement, name)(first, cpu, cpu.budget.window("offspring", 200))
        actual = getattr(tensor, name)(parents.take([0]), state, window)
    reference = cpu.budget.records[2:]
    observed = state.budget.records[start:]
    assert len(reference) == len(observed)
    for (a, av), (b, bv) in zip(reference, observed):
        np.testing.assert_allclose(a.towers, b.towers, atol=1e-12, rtol=1e-12)
        np.testing.assert_allclose(av.objectives, bv.objectives, atol=1e-9, rtol=1e-10)
        assert av.is_feasible == bv.is_feasible
    np.testing.assert_allclose(expected.route.towers, actual.routes.routes()[0].towers, atol=1e-12, rtol=1e-12)
    assert gpu_decisions == cpu_decisions
    np.testing.assert_array_equal(parents.routes.routes()[0].towers, genes[0])
    if name == "crossover":
        result = tensor.crossover(parents.take([0]), parents.take([1]), state, state.budget.window("offspring", 1))
        assert bool((result.ids >= 0).all())
        before = len(state.budget.records)
        tensor.crossover(parents.take([0]), parents.take([1]), state, state.budget.window("offspring", 0))
        assert len(state.budget.records) == before


def test_crossover_keeps_endpoints_when_a_shorter_lane_is_inactive(tensor_state):
    state = tensor_state
    state.better = lambda first, second, **kwargs: torch.zeros(len(first), dtype=torch.bool, device=state.device)
    short, long = np.array([[8., 12.]]), np.array([[8., 12.], [14., 14.], [18., 11.], [22., 16.]])
    first = scored(state, [short, long])
    second = scored(state, [np.array([[10., 8.]]), np.array([[10., 8.], [16., 12.], [20., 10.], [24., 14.]])])
    result = tensor.crossover(first, second, state, state.budget.window("offspring", 50))
    ends = result.routes.routes()
    assert len(ends) == 2
    for route in ends:
        np.testing.assert_array_equal(route.points(state.problem.start, state.problem.end)[[0, -1]],
                                      [state.problem.start, state.problem.end])


def test_fixed_mutation_proposals_preserve_static_base_and_acceptance(tensor_state):
    state = tensor_state
    genes = np.array([[10., 10.], [19., 9.]])
    current = scored(state, [genes])
    cpu = state_for()
    first = cpu.score(Route(genes), cpu.budget.window("initialization", 1))
    cpu_decisions = record_decisions(cpu, 1, native=False)
    gpu_decisions = record_decisions(state, 1, native=True)
    # Both implementations receive identical polar proposals around tower zero.
    rng = np.random.RandomState(99)
    draws = rng.uniform(size=(state.core.mutation_tries, 2))
    radius = cpu.neighborhood_radius(cpu.adapter.path(first.route), 1)
    angles = draws[:, 0] * 2 * np.pi
    lengths = (state.core.mutation_min_fraction + draws[:, 1] * (1-state.core.mutation_min_fraction)) * radius
    proposals = genes[0] + lengths[:, None] * np.column_stack((np.cos(angles), np.sin(angles)))
    values = iter(draws.ravel())
    cpu.adapter.python_rng.randint = lambda *args: 1
    cpu.adapter.numpy_rng = type("Draws", (), {"uniform": lambda _, low, high: low + next(values) * (high-low)})()
    expected = mutation.mutate(first, cpu, cpu.budget.window("offspring", 200))
    actual = tensor.mutate(current, state, state.budget.window("offspring", 200),
                           indices=torch.tensor([0], device=state.device),
                           proposals=torch.tensor(proposals[:, None], device=state.device))
    observed = state.budget.records[1:]
    assert len(observed) == len(cpu.budget.records)-1
    for (a, _), (b, _) in zip(cpu.budget.records[1:], observed):
        np.testing.assert_allclose(a.towers, b.towers, atol=1e-12, rtol=1e-12)
    np.testing.assert_allclose(expected.route.towers, actual.routes.routes()[0].towers, atol=1e-12, rtol=1e-12)
    assert gpu_decisions == cpu_decisions
    before = len(state.budget.records)
    result = tensor.mutate(current, state, state.budget.window("offspring", 1),
                           indices=torch.tensor([0], device=state.device),
                           proposals=torch.tensor(proposals[:, None], device=state.device))
    assert len(state.budget.records) <= before+1 and bool((result.ids >= 0).all())
    np.testing.assert_array_equal(current.routes.routes()[0].towers, genes)


def test_parallel_mutations_match_individual_lanes_with_fixed_proposals(tensor_state):
    state = tensor_state
    parents = scored(state, [[[10., 10.], [19., 9.]], [[11., 12.]]])
    trials = torch.tensor([[[10.+i/20, 10.], [11., 12.+i/30]] for i in range(state.core.mutation_tries)], device=state.device, dtype=torch.float64)
    start = len(state.budget.records)
    actual = tensor.mutate(parents, state, state.budget.window("offspring", 200),
                           indices=torch.zeros(2, dtype=torch.long, device=state.device), proposals=trials)
    batch_records = state.budget.records[start:]
    for lane in range(2):
        expected = tensor.mutate(parents.take([lane]), state, state.budget.window("offspring", 200),
            indices=torch.tensor([0], device=state.device), proposals=trials[:, lane:lane+1])
        np.testing.assert_allclose(actual.routes.routes()[lane].towers, expected.routes.routes()[0].towers)
    assert len(batch_records) == 2*state.core.mutation_tries


def test_ordered_scoring_clips_before_objective_and_reuses_recent_identity(tensor_state):
    state = tensor_state
    routes = TowerBatch.from_routes([Route(np.array([[float(i), 10.]])) for i in [8, 10, 12]], state.device)
    allowed = torch.tensor([False, True, True], device=state.device)
    window = state.budget.window("offspring", 1)
    result = state.score(routes, window, allowed=allowed)
    assert result.ids.tolist() == [-1, 0, -1] and window.used == 1
    assert state.budget.counts == {"offspring": 1}
    assert state.reuse(routes, 0).ids.tolist() == [-1, 0, -1]
    assert state.reuse(routes, 1).ids.tolist() == [-1, -1, -1]


def test_offspring_zero_budget_returns_only_completed_and_reuses_rechecked_parent(tensor_state, monkeypatch):
    state = tensor_state
    parent = scored(state, [[[14., 10.]]])
    state.config = replace(state.config, pilot=replace(state.config.pilot, enabled_mechanisms=["nearby_crossover"],
        core=replace(state.core, crossover_probability=1.)))
    state.core = state.config.pilot.core
    def crossover(a, b, state, window, **kwargs):
        state.score(a.routes, window)
        return a
    monkeypatch.setattr(tensor, "crossover", crossover)
    monkeypatch.setattr(tensor, "encode_candidate", lambda *args: parent.routes)
    result = tensor.offspring(parent, parent, TowerRange(0, 4, 4), state, state.budget.window("offspring", 1))
    assert result.ids.tolist() == [1] and len(state.budget.records) == 2
    exhausted = tensor.offspring(parent, parent, TowerRange(0, 4, 4), state, state.budget.window("offspring", 0))
    assert exhausted.ids.tolist() == parent.ids.tolist()
