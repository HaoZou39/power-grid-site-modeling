from dataclasses import replace
import threading

import numpy as np
import pytest
import torch

from algorithms.routing.search import routing_search
from config.project_config import load_default_config
from modeling.routing.evaluation_session import evaluation_session
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.types import Route
from test_routing_context import make_problem


@pytest.mark.skipif(torch.cuda.device_count() < 2, reason="two CUDA devices required")
def test_dual_device_candidate_order_values_and_cleanup():
    problem = make_problem();rng = np.random.default_rng(48)
    routes = [Route(rng.uniform(1, 31, (i % 6, 2))) for i in range(19)]
    config = replace(load_default_config().routing, evolution_backend="tensor", evaluation_backend="tensor",
                     devices=["cuda:0", "cuda:1"], evaluation_batch_size=4)
    single = TensorRouteEvaluator(problem, replace(config, devices=["cuda:0"]))
    expected = single.evaluate_many(routes)
    with evaluation_session(problem, config) as dual:
        actual = dual.evaluate_many(routes)
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            assert a.is_feasible == b.is_feasible
            np.testing.assert_allclose(a.objectives, b.objectives, atol=1e-8, rtol=1e-10)
            np.testing.assert_allclose(list(a.violations.values()), list(b.violations.values()), atol=1e-10)
    assert not any(t.name.startswith("routing-eval") for t in threading.enumerate())


@pytest.mark.skipif(torch.cuda.device_count() < 2, reason="two CUDA devices required")
def test_dual_search_fixed_budget_repeats_and_cancels_cleanly():
    from backend.app.domain.jobs import JobCancelled
    problem = make_problem()
    config = replace(load_default_config().routing, evolution_backend="tensor", evaluation_backend="tensor",
        devices=["cuda:0", "cuda:1"], popsize=8, max_generations=2, max_evaluations=57, reference_count=2, expansion_interval=1)
    first, second = routing_search(problem, config), routing_search(problem, config)
    assert first.generation_count == second.generation_count == config.max_generations
    assert first.evaluation_count == second.evaluation_count
    for a, b in zip(first.routes, second.routes):
        np.testing.assert_array_equal(a.towers, b.towers)
    for index in first.pareto_indices:
        assert RouteEvaluator(problem).evaluate(first.routes[index]).is_feasible
    def cancel(_progress, stage, _message):
        if stage == "evolution":
            raise JobCancelled("test cancellation")
    with pytest.raises(JobCancelled):
        routing_search(problem, config, cancel)
    assert not any(t.name.startswith("routing-eval") for t in threading.enumerate())
