from dataclasses import replace

import numpy as np
import pytest

from algorithms.common.nsga2 import Individual, nondominated_sort
from algorithms.routing.search import routing_search
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from test_routing_context import make_problem


def small_config():
    base = load_default_config().routing
    return replace(base, search_strategy="standard", pilot=replace(base.pilot, enabled_mechanisms=[], initialization_mode="legacy"),
                   evaluation_backend="compiled_cpu", popsize=8, max_generations=4, max_evaluations=64, reference_count=2,
                   expansion_interval=1, navigation_step_m=2)


def test_search_reproduces_and_respects_budget_and_fixed_connections():
    problem, config = make_problem(), small_config()
    first, second = routing_search(problem, config), routing_search(problem, config)
    assert first.generation_count == config.max_generations
    assert first.stop_reason == "generation_limit"
    assert first.evaluation_count == first.initialization_evaluations + config.max_generations * config.popsize
    assert first.final_upper > first.initial_upper
    assert first.expansions and first.pareto_indices
    for a, b in zip(first.routes, second.routes):
        np.testing.assert_array_equal(a.towers, b.towers)
        points = a.points(problem.start, problem.end)
        np.testing.assert_array_equal(points[[0, -1]], [problem.start, problem.end])
    for index in first.pareto_indices:
        assert RouteEvaluator(problem).evaluate(first.routes[index]).is_feasible
    assert any(len(route.towers) > first.initial_upper for route in first.routes)


def test_extra_towers_keep_a_lower_crossing_tradeoff():
    landuse = np.zeros((32, 32), dtype=np.int32); landuse[7:10, 14:17] = 2
    problem = make_problem(landuse=landuse)
    result = routing_search(problem, small_config())
    front = [result.evaluations[i].objectives for i in result.pareto_indices]
    assert any(value[0] == 0 and value[3] > 0 for value in front)
    assert any(value[0] > 0 and value[3] == 0 for value in front)


def test_shared_ranking_is_constraint_first_and_handles_more_than_three_objectives():
    population = [Individual(np.empty((0, 2)), np.array(f, dtype=float), cv) for f, cv in [
        ([0, 10, 0, 4], 0), ([1, 12, 1, 0], 0), ([2, 20, 2, 5], 0), ([0, 0, 0, 0], 1)]]
    assert nondominated_sort(population) == [[0, 1], [2], [3]]


def test_no_solution_is_reported_as_budget_exhaustion():
    problem = make_problem(no_cross_zones=[[[0, 0], [32, 0], [32, 32], [0, 32]]])
    result = routing_search(problem, small_config())
    assert not result.pareto_indices
    assert result.stop_reason == "generation_limit"
    assert result.generation_count == small_config().max_generations


@pytest.mark.parametrize("backend", ["numpy", "tensor"])
@pytest.mark.parametrize("generations", [1, 3])
def test_generations_finish_after_initialization_without_a_short_last_generation(backend, generations):
    config = replace(small_config(), evolution_backend=backend, devices=["cpu"],
                     popsize=4, max_generations=generations, reference_count=6)
    result = routing_search(make_problem(), config)
    assert result.initialization_evaluations > 0
    assert result.generation_count == generations
    assert result.evaluation_count == result.initialization_evaluations + generations * config.popsize
