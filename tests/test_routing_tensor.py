from dataclasses import replace

import numpy as np
import pytest
import torch

from algorithms.common.nsga2 import Individual, nondominated_sort
from algorithms.common.tensor_nsga2 import crowding_distance, nondominated_rank
from algorithms.routing.search import routing_search
from algorithms.routing.tensor_operators import TowerBatch, vary
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import Route
from test_routing_context import make_problem


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_tensor_rank_matches_reference_and_tiles(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA required")
    rng = np.random.default_rng(12)
    values = rng.integers(0, 8, (35, 4)).astype(float)
    cv = rng.choice([0., 0., .1, .2], 35)
    reference = [Individual(np.empty(0), value, violation) for value, violation in zip(values, cv)]
    fronts = nondominated_sort(reference)
    tensor = torch.tensor(values, device=device)
    actual = nondominated_rank(tensor, torch.tensor(cv, device=device), tile_pairs=39)
    assert actual.cpu().tolist() == [p.rank for p in reference]
    # Crowding ties use stable input order in the tensor backend.
    canonical = [Individual(np.empty(0), value, violation) for value, violation in zip(values, cv)]
    from algorithms.common.nsga2 import _assign_crowding
    for front in fronts:
        _assign_crowding(canonical, sorted(front))
    np.testing.assert_allclose(crowding_distance(tensor, actual).cpu(), [p.crowding for p in canonical])
    invalid = torch.tensor([[0., 0., 0., 0.], [float("inf")] * 4, [float("inf")] * 4], device=device)
    assert not torch.isnan(crowding_distance(invalid, torch.tensor([0, 1, 1], device=device))).any()


def test_controlled_tensor_move_insert_delete_and_crossover():
    route = Route(np.array([[6., 8.], [12., 8.], [20., 8.]]))
    first = TowerBatch.from_routes([route] * 4, "cpu", 4)
    second = TowerBatch.from_routes([Route(np.array([[5., 10.], [15., 10.]]))] * 4, "cpu", 4)
    result = vary(first, second, start=torch.tensor([2., 8.]), end=torch.tensor([28., 8.]),
        lower=0, upper=4, sigma=1., radius=.4, size=(32, 32), generator=torch.Generator().manual_seed(9),
        actions=torch.arange(4), locations=torch.tensor([.4, .3, .4, .1]),
        cuts=torch.tensor([[.3, .4]] * 4), noise=torch.tensor([[1., 2.]] * 4))
    expected = [np.array([[6, 8], [13, 10], [20, 8]]), np.array([[6, 8], [10, 10], [12, 8], [20, 8]]),
                np.array([[6, 8], [20, 8]]), np.array([[6, 8], [15, 10]])]
    for actual, wanted in zip(result.routes(), expected):
        np.testing.assert_allclose(actual.towers, wanted)


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_tensor_search_budget_reproduction_and_fixed_endpoints(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA required")
    problem = make_problem()
    config = replace(load_default_config().routing, evolution_backend="tensor", devices=[device],
        popsize=8, max_generations=2, max_evaluations=57, reference_count=2, expansion_interval=1)
    first, second = routing_search(problem, config), routing_search(problem, config)
    assert first.generation_count == second.generation_count == config.max_generations
    assert first.evaluation_count == second.evaluation_count
    assert first.stop_reason == "generation_limit"
    assert first.final_upper > first.initial_upper and first.pareto_indices
    assert len(first.routes) == len(second.routes)
    for a, b in zip(first.routes, second.routes):
        np.testing.assert_array_equal(a.towers, b.towers)
        np.testing.assert_array_equal(a.points(problem.start, problem.end)[[0, -1]], [problem.start, problem.end])
    for index in first.pareto_indices:
        assert RouteEvaluator(problem).evaluate(first.routes[index]).is_feasible


def test_zero_towers_and_forced_capacity_growth():
    empty = TowerBatch.from_routes([Route(np.empty((0, 2)))], "cpu")
    kwargs = dict(start=torch.tensor([2., 8.]), end=torch.tensor([28., 8.]), lower=0, sigma=0.,
                  radius=.4, size=(32, 32), generator=torch.Generator().manual_seed(3))
    result = vary(empty, empty, upper=0, **kwargs)
    assert result.xy.shape == (1, 0, 2) and result.counts.item() == 0
    result = vary(empty, empty, upper=3, target_count=torch.tensor([3]), **kwargs)
    assert result.counts.item() == 3 and torch.isfinite(result.xy).all()


def test_large_population_runs_in_small_explicit_cuda_budget():
    if not torch.cuda.is_available():
        pytest.skip("CUDA required")
    torch.cuda.empty_cache()
    before = torch.cuda.memory_allocated("cuda:0")
    torch.cuda.reset_peak_memory_stats("cuda:0")
    config = replace(load_default_config().routing, evolution_backend="tensor", evaluation_backend="tensor",
        devices=["cuda:0"], popsize=1024, max_generations=2, max_evaluations=3072, reference_count=2,
        evaluation_batch_size=64, gpu_memory_budget_mib=64)
    result = routing_search(make_problem(), config)
    assert result.generation_count == config.max_generations
    assert result.stop_reason == "generation_limit"
    assert result.pareto_indices
    assert torch.cuda.max_memory_allocated("cuda:0") - before < 64 * 1024**2
    assert all(not value.spans and not value.elevations.size for value in result.evaluations)
