from dataclasses import replace

import numpy as np
import pytest
import torch

from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.tensor_types import TowerBatch
from modeling.routing.types import Route, RoutingConstraints
from test_routing_context import make_problem


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
@pytest.mark.parametrize("batch_size", [1, 17])
def test_tensor_evaluation_matches_every_objective_and_constraint(device, batch_size):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA required")
    rng = np.random.default_rng(40)
    dem = rng.uniform(-20, 100, (32, 32));dem[20, 20] = np.nan
    land = rng.integers(0, 6, (32, 32), dtype=np.int32)
    problem = make_problem(dem=dem, landuse=land)
    config = replace(load_default_config().routing, devices=[device], evaluation_backend="tensor", evaluation_batch_size=batch_size)
    fast = TensorRouteEvaluator(problem, config)
    routes = [Route(rng.uniform(-1, 33, (i % 6, 2))) for i in range(23)]
    for route, actual in zip(routes, fast.evaluate_many(routes)):
        expected = RouteEvaluator(problem).evaluate(route)
        assert expected.is_feasible == actual.is_feasible
        np.testing.assert_allclose(expected.objectives, actual.objectives, atol=1e-8, rtol=1e-10)
        np.testing.assert_allclose(list(expected.violations.values()), list(actual.violations.values()), atol=1e-10)


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_tensor_closed_edges_tangency_nodata_and_ignored_padding(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA required")
    land = np.zeros((32, 32), dtype=np.int32);land[8, 10] = 2
    problem = make_problem(landuse=land, constraints=RoutingConstraints(13, .4, 90, 0, 0))
    config = replace(load_default_config().routing, devices=[device], evaluation_backend="tensor")
    fast = TensorRouteEvaluator(problem, config)
    routes = [Route(np.array(r).reshape(-1, 2)) for r in ([], [[9.6, 8.5]], [[9.59, 8.5]], [[15, 8]], [[2, 8]])]
    for route, actual in zip(routes, fast.evaluate_many(routes)):
        expected = RouteEvaluator(problem).evaluate(route)
        assert actual.is_feasible == expected.is_feasible
        np.testing.assert_allclose(actual.objectives, expected.objectives, atol=1e-8)
    batch = TowerBatch.from_routes(routes, device, 4)
    batch.xy[torch.arange(4, device=device)[None, :] >= batch.counts[:, None]] = torch.nan
    outputs = fast.numeric(batch)
    assert torch.isfinite(outputs[0]).all()
    assert fast.boundary_rechecks > 0


def test_tensor_exact_polygon_boundary_is_reference_checked():
    polygon = [[[14, 5], [17, 5], [17, 11], [14, 11]]]
    problem = make_problem(no_tower_zones=polygon, no_cross_zones=polygon)
    evaluator = TensorRouteEvaluator(problem, load_default_config().routing)
    routes = [Route(np.empty((0, 2))), Route(np.array([[15, 8]]))]
    for route, result in zip(routes, evaluator.evaluate_many(routes)):
        expected = RouteEvaluator(problem).evaluate(route)
        assert result.violations == expected.violations
    assert evaluator.boundary_rechecks == 2


def test_cuda_scene_budget_rejected_before_allocation():
    if not torch.cuda.is_available():
        pytest.skip("CUDA required")
    problem = make_problem(landuse=np.zeros((1024, 1024), dtype=np.int32), start=(2, 8), end=(28, 8))
    config = replace(load_default_config().routing, devices=["cuda:0"], gpu_memory_budget_mib=1)
    before = torch.cuda.memory_allocated()
    with pytest.raises(MemoryError, match="budget"):
        TensorRouteEvaluator(problem, config)
    assert torch.cuda.memory_allocated() == before


def test_tensor_search_uses_exact_batched_evaluation():
    from algorithms.routing.search import routing_search
    problem = make_problem()
    config = replace(load_default_config().routing, evolution_backend="tensor", evaluation_backend="tensor",
                     popsize=8, max_generations=2, max_evaluations=57, reference_count=2, expansion_interval=1)
    first, second = routing_search(problem, config), routing_search(problem, config)
    assert first.generation_count == second.generation_count == config.max_generations
    assert first.evaluation_count == second.evaluation_count
    assert first.pareto_indices == second.pareto_indices
    for a, b in zip(first.routes, second.routes):
        np.testing.assert_array_equal(a.towers, b.towers)
