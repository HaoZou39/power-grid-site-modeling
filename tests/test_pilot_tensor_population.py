from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from algorithms.common.nsga2 import Individual, nondominated_sort
from algorithms.routing.pilot_reference.population import deduplicate
from algorithms.routing.pilot_reference.global_search import update_survival
from algorithms.routing.pilot_reference.tensor_population import (
    TensorPopulation, better, ranked, tournament, parent_pairs, identity_groups,
    deduplicated_indices, select_population, inherited_survival, updated_survival, elite_indices,
)
from modeling.routing.tensor_types import TowerBatch, TensorEvaluationBatch
from modeling.routing.types import Route
from pilot_reference import original_functions
from test_pilot_components import state_for, value, candidate_is_better


def population(f, cv, device, genes=None):
    genes = [[[i + 3., 8.]] for i in range(len(cv))] if genes is None else genes
    routes = TowerBatch.from_routes([Route(np.array(row, dtype=float).reshape(-1, 2)) for row in genes], device)
    values = TensorEvaluationBatch(torch.tensor(np.array(f), device=device, dtype=torch.float64),
                                   torch.zeros((len(cv), 8), device=device, dtype=torch.float64),
                                   torch.tensor(cv, device=device, dtype=torch.float64))
    return TensorPopulation(routes, values, torch.arange(len(cv), device=device))


@pytest.fixture(params=["cpu", "cuda:0"])
def device(request):
    if request.param.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    return request.param


def test_candidate_acceptance_vector_matches_cpu_and_rejects_pending(device):
    config = state_for().config
    a = [[3, 10, 2, 5], [3, 10, 2, 5], [3, 10, 2, 5], [3] * 4, [3] * 4]
    b = [[2, 9, 1, 4], [3, 8, 2 + 1e-7, 5], [3, 8, 3, 5], [100] * 4, [1] * 4]
    ca, cb = [0, 0, 0, 1, 0], [0, 0, 0, 0, 1]
    first, second = population(a, ca, device), population(b, cb, device)
    for target in [None, 1]:
        expected = [candidate_is_better(value(x, c), value(y, d), config.pilot.core, target=target, margin=1.)
                    for x, y, c, d in zip(a, b, ca, cb)]
        np.testing.assert_array_equal(better(first, second, config.pilot.core, target=target, margin=1.).cpu(), expected)
    second.ids[:] = -1
    assert not bool(better(first, second, config.pilot.core).any())


def test_tournament_matches_frozen_neutral_comparisons_with_fixed_coins(device):
    config = state_for().config
    f = np.ones((6, 4))
    cv = np.array([0., 0., 0., 1., 1., 2.])
    ranks = np.array([0, 0, 1, 2, 2, 3])
    crowd = np.array([np.inf, 2., np.nan, 0., 1., 0.])
    pairs = np.array([[0, 1], [1, 0], [2, 1], [3, 4], [4, 3], [5, 3], [4, 2], [1, 1]])
    coins = np.array([.2, .8, .2, .1, .9, .7, .2, .8])
    random = SimpleNamespace(random=lambda: random.coin)
    source = original_functions("population.py", ["_tournament_better_index"], {
        "random": random, "_is_pinsga2_official_profile": lambda *a: False,
        "_is_search_guidance_disabled_profile": lambda *a: False})["_tournament_better_index"]
    context = {"feasible": cv <= 0, "cv": cv, "rank": ranks, "crowding": crowd,
               "pref_scores": np.zeros(6), "has_guidance": False}
    expected = []
    for (a, b), coin in zip(pairs, coins):
        random.coin = coin
        expected.append(source(a, b, context))
    actual = tournament(population(f, cv, device), torch.tensor(ranks, device=device),
                        torch.tensor(crowd, device=device), torch.tensor(pairs, device=device),
                        torch.tensor(coins, device=device), config.pilot.core)
    np.testing.assert_array_equal(actual.cpu(), expected)


def test_parent_retries_are_bounded_and_single_parent_draws_nothing(device):
    config = state_for().config
    pop = population([[0] * 4, [1] * 4], [0, 0], device)
    generator = torch.Generator(device=device).manual_seed(config.seed)
    rank, crowd = ranked(pop, config, 128)
    pairs, retries = parent_pairs(pop, 13, rank, crowd, config, generator, distinct=True)
    assert bool((pairs == 0).all())
    assert bool((retries == config.pilot.core.parent_retries).all())
    single = pop.take(torch.tensor([0], device=device))
    before = generator.get_state()
    pairs, retries = parent_pairs(single, 4, rank[:1], crowd[:1], config, generator, distinct=True)
    assert bool((pairs == 0).all()) and not bool(retries.any())
    assert torch.equal(before, generator.get_state())


def test_exact_dedup_matches_cpu_nontransitive_tolerance_and_signed_zero(device):
    state = state_for()
    tol = state.core.cv_tolerance
    cv = [1 + .75 * tol, 1 + .1 * tol, 1 - .5 * tol, 0, 0, 0, 0]
    genes = [[[1., 2.]]] * 3 + [[[2., 3.]]] * 2 + [[[0., 8.]], [[-0., 8.]]]
    f = np.arange(len(cv) * 4, dtype=float).reshape(-1, 4)
    pop = population(f, cv, device, genes)
    expected = deduplicate([Individual(np.array(g), v, c) for g, v, c in zip(genes, f, cv)], state)
    actual = pop.take(deduplicated_indices(pop, state.config))
    assert [r.towers.tobytes() for r in actual.routes.routes()] == [p.genes.tobytes() for p in expected]
    np.testing.assert_array_equal(actual.values.objectives.cpu(), [p.objectives for p in expected])
    padded = pop.routes.padded(5)
    padded.xy[~padded.valid] = float("nan")
    before, n = identity_groups(pop.routes, state.config.gpu_memory_budget_mib)
    after, m = identity_groups(padded, state.config.gpu_memory_budget_mib)
    assert n == m and torch.equal(before, after)


def test_environment_dedup_rollback_and_pending_candidates(device):
    config = state_for().config
    pop = population([[1] * 4] * 4, [0] * 4, device, [[[1., 2.]]] * 3 + [[[3., 4.]]])
    diagnostics = {}
    selected = select_population(pop, 3, config, 128, diagnostics, deduplicate=True)
    assert len(selected) == 3 and diagnostics["population_dedup_rollbacks"] == 1
    pop.ids[0] = -1
    with pytest.raises(ValueError, match="fully evaluated"):
        ranked(pop, config, 128)


def test_survival_counts_match_cpu_for_duplicate_disappearance_and_reentry(device):
    config = state_for().config
    a = population([[1] * 4] * 3, [0] * 3, device, [[[1., 2.]], [[1., 2.]], [[3., 4.]]])
    old_cpu = [Individual(r.towers, np.ones(4), 0.) for r in a.routes.routes()]
    previous = update_survival(old_cpu, {})
    counts = updated_survival(None, None, a.routes, config.gpu_memory_budget_mib)
    assert counts.tolist() == [1, 1, 1]
    b = a.take(torch.tensor([2], device=device))
    next_counts = updated_survival(a.routes, counts, b.routes, config.gpu_memory_budget_mib)
    previous = update_survival([old_cpu[2]], previous)
    assert next_counts.tolist() == [previous[old_cpu[2].genes.tobytes()]]
    inherited = inherited_survival(b.routes, next_counts, a.routes, config.gpu_memory_budget_mib)
    assert inherited.tolist() == [0, 0, 2]
    restored = updated_survival(b.routes, next_counts, a.routes, config.gpu_memory_budget_mib)
    assert restored.tolist() == [1, 1, 3]


def test_rank_crowding_and_elite_priority_use_shared_math(device):
    from algorithms.routing.pilot_reference.local_search import elite_indices as cpu_elites
    config = state_for().config
    f = np.array([[i, 100 - i, i * i, 5000 - i**3] for i in range(16)], dtype=float)
    pop = population(f, np.zeros(16), device)
    cpu = [Individual(np.array([[i + 3., 8.]]), row, 0.) for i, row in enumerate(f)]
    nondominated_sort(cpu)
    for workspace in [128, 8192]:
        rank, crowd = ranked(pop, config, workspace)
        np.testing.assert_array_equal(rank.cpu(), [p.rank for p in cpu])
        np.testing.assert_allclose(crowd.cpu(), [p.crowding for p in cpu], rtol=1e-12, atol=1e-12)
        for include_rest in [False, True]:
            cfg = replace(config, pilot=replace(config.pilot, core=replace(config.pilot.core, local_include_rest=include_rest)))
            expected, exhaustive = cpu_elites(cpu, cfg.pilot.core, cfg.popsize)
            indices, flags = elite_indices(pop, rank, crowd, cfg)
            assert indices.tolist() == expected
            assert flags.tolist() == [i in exhaustive for i in expected]
