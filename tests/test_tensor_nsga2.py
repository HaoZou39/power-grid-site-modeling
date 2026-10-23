"""Compare tensor operators to small independent scalar NSGA-II calculations."""

import numpy as np
import pytest
import torch

from algorithms.guided_search import tensor_nsga2
from algorithms.guided_search.tensor_nsga2 import (
    crowding_distance, dominance_matrix, environmental_selection,
    nondominated_rank, run_evolution, tournament, vary,
)


def _reference(objectives, violation):
    def dominates(i, j):
        a, b = max(violation[i], 0), max(violation[j], 0)
        return a < b or (a == b and np.all(objectives[i] <= objectives[j]) and np.any(objectives[i] < objectives[j]))

    edges = np.array([[dominates(i, j) for j in range(len(violation))] for i in range(len(violation))])
    pending, rank, distance = set(range(len(violation))), np.zeros(len(violation), dtype=int), np.zeros(len(violation))
    level = 0
    while pending:
        front = sorted(i for i in pending if not any(edges[j, i] for j in pending))
        assert front
        rank[front] = level
        for column in range(objectives.shape[1]):
            ordered = sorted(front, key=lambda i: objectives[i, column])
            distance[ordered[0]] = distance[ordered[-1]] = np.inf
            span = objectives[ordered[-1], column] - objectives[ordered[0], column]
            if span > 0:
                for previous, current, following in zip(ordered, ordered[1:], ordered[2:]):
                    distance[current] += (objectives[following, column] - objectives[previous, column]) / span
        pending.difference_update(front)
        level += 1
    return edges, rank, distance


@pytest.mark.parametrize("tile_pairs", [7, 1 << 26])
@pytest.mark.parametrize("device_name", ["cpu", "cuda"])
@pytest.mark.parametrize("fixture", ["random", "equal", "chain", "tradeoff"])
def test_sort_crowding_and_selection_match_scalar_reference(device_name, fixture, tile_pairs, monkeypatch):
    if device_name == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    monkeypatch.setattr(tensor_nsga2, "TILE_PAIRS", tile_pairs)
    rng = np.random.default_rng(20)
    objectives = rng.integers(0, 8, (37, 4)).astype(float)
    cv = rng.integers(-1, 4, 37).astype(float)
    if fixture == "equal":
        objectives[:] = 1
        cv[:] = 0
    elif fixture == "chain":
        objectives[:] = np.arange(37)[:, None]
    elif fixture == "tradeoff":
        objectives = np.column_stack((np.arange(37), -np.arange(37))).astype(float)
        cv[:] = 0
    expected_edges, expected_rank, expected_distance = _reference(objectives, cv)
    values, violation = torch.tensor(objectives, device=device_name), torch.tensor(cv, device=device_name)
    np.testing.assert_array_equal(dominance_matrix(values, violation).cpu(), expected_edges)
    rank = nondominated_rank(values, violation)
    np.testing.assert_array_equal(rank.cpu(), expected_rank)
    np.testing.assert_allclose(crowding_distance(values, rank).cpu(), expected_distance, rtol=1e-14)
    genes = torch.arange(len(cv), device=device_name, dtype=torch.float64)[:, None]
    selected = environmental_selection(genes, values, violation, 16)
    expected = sorted(range(len(cv)), key=lambda i: (expected_rank[i], -expected_distance[i], i))[:16]
    np.testing.assert_array_equal(selected.genes[:, 0].cpu(), expected)
    np.testing.assert_array_equal(selected.rank.cpu(), nondominated_rank(selected.objectives, selected.violation).cpu())
    np.testing.assert_allclose(selected.crowding.cpu(), _reference(objectives[expected], cv[expected])[2])


def test_batched_tournaments_and_variation_use_the_existing_operators():
    genes = torch.arange(18, dtype=torch.float64).reshape(6, 3)
    rank = torch.tensor([0, 0, 1, 1, 2, 2])
    crowding = torch.tensor([torch.inf, 2, 1, 1, 3, 4])
    pairs = torch.tensor([[[0, 1], [2, 3]], [[1, 0], [4, 5]], [[2, 3], [5, 0]], [[4, 2], [3, 3]]])
    parents = tournament(rank, crowding, pairs)
    expected = []
    for tournaments in pairs.tolist():
        expected.append([a if rank[a] < rank[b] or (rank[a] == rank[b] and crowding[a] > crowding[b]) else b for a, b in tournaments])
    assert parents.tolist() == expected
    cross = torch.tensor([0.0, 0.899, 0.9, 1.0])
    noise = torch.arange(12, dtype=torch.float64).reshape(4, 3) / 10
    result = vary(genes, parents, cross, noise, 0.2)
    for i, (a, b) in enumerate(expected):
        child = (genes[a] + genes[b]) / 2 if cross[i] < 0.9 else genes[a]
        torch.testing.assert_close(result[i], child + 0.2 * noise[i], rtol=0, atol=0)


def test_evolution_is_reproducible_and_rejects_bad_evaluation():
    def evaluate(raw):
        return torch.stack((raw.square().sum(1), (raw - 1).square().sum(1)), 1), torch.zeros(len(raw))
    kwargs = dict(popsize=16, generations=4, seed=17, sigma=0.3)
    first, second = run_evolution(evaluate, **kwargs), run_evolution(evaluate, **kwargs)
    torch.testing.assert_close(first.genes, second.genes, rtol=0, atol=0)
    with pytest.raises(ValueError, match="NaN or Inf"):
        run_evolution(lambda raw: (torch.full((len(raw), 1), torch.nan), torch.zeros(len(raw))), **kwargs)
