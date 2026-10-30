"""Batched constrained NSGA-II with a population resident on one torch device."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

import torch

from .evolution import generation_sigma


@dataclass
class TensorPopulation:
    genes: torch.Tensor
    objectives: torch.Tensor
    violation: torch.Tensor
    rank: torch.Tensor
    crowding: torch.Tensor


# 一块里最多比较的个体对数。只决定显存占用，不改变名次。
TILE_PAIRS = 1 << 26


from algorithms.common.tensor_nsga2 import crowding_distance, dominance_matrix, pareto_dominance, tournament
from algorithms.common.tensor_nsga2 import nondominated_rank as _shared_rank


def nondominated_rank(objectives: torch.Tensor, violation: torch.Tensor) -> torch.Tensor:
    return _shared_rank(objectives, violation, tile_pairs=TILE_PAIRS)


def vary(genes: torch.Tensor, parents: torch.Tensor, cross: torch.Tensor, noise: torch.Tensor, sigma: float) -> torch.Tensor:
    first, second = genes[parents[:, 0]], genes[parents[:, 1]]
    return torch.where(cross[:, None] < 0.9, 0.5 * (first + second), first) + sigma * noise


def environmental_selection(genes: torch.Tensor, objectives: torch.Tensor, violation: torch.Tensor, popsize: int) -> TensorPopulation:
    rank = nondominated_rank(objectives, violation)
    distance = crowding_distance(objectives, rank)
    order = torch.argsort(distance, descending=True, stable=True)
    order = order[torch.argsort(rank[order], stable=True)][:popsize]
    # Truncating the final retained front cannot change any survivor's rank.
    selected_rank = rank[order]
    selected_objectives = objectives[order]
    return TensorPopulation(genes[order], selected_objectives, violation[order], selected_rank,
                            crowding_distance(selected_objectives, selected_rank))


def _evaluate(evaluate: Callable, genes: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    objectives, violation = evaluate(genes)
    if objectives.ndim != 2 or objectives.shape[0] != len(genes) or objectives.shape[1] < 1 or violation.shape != (len(genes),):
        raise ValueError("evaluate must return [N, M] objectives and [N] violation, with M >= 1")
    if objectives.device != genes.device or violation.device != genes.device:
        raise ValueError("evaluation tensors must stay on the population device")
    if not bool(torch.isfinite(objectives).all() & torch.isfinite(violation).all()):
        raise ValueError("evaluation contains NaN or Inf")
    return objectives.to(torch.float64), violation.to(torch.float64)


@torch.no_grad()
def run_evolution(
    evaluate: Callable[[torch.Tensor], tuple[torch.Tensor, torch.Tensor]],
    *, popsize: int, generations: int, seed: int, sigma: float, n_var: int = 3,
    initial: torch.Tensor | None = None,
    on_generation: Callable[[int, int], None] | None = None,
    anneal_last: int = 0, anneal_sigma_end: float | None = None, step_control: Any = None,
) -> TensorPopulation:
    if popsize < 4 or generations < 1 or sigma <= 0 or n_var < 1:
        raise ValueError("popsize must be at least 4, generations at least 1, and sigma positive")
    device = initial.device if initial is not None else torch.device("cpu")
    rng = torch.Generator(device=device).manual_seed(seed)
    genes = torch.randn((popsize, n_var), device=device, dtype=torch.float64, generator=rng) * sigma if initial is None else initial.to(torch.float64)
    if genes.shape != (popsize, n_var) or not bool(torch.isfinite(genes).all()):
        raise ValueError(f"initial population must be finite with shape [{popsize}, {n_var}]")
    objectives, violation = _evaluate(evaluate, genes)
    rank = nondominated_rank(objectives, violation)
    population = TensorPopulation(genes, objectives, violation, rank, crowding_distance(objectives, rank))
    for generation in range(generations):
        step_sigma = step_control.sigma if step_control is not None else generation_sigma(generation, generations, sigma, anneal_last, anneal_sigma_end)
        pairs = torch.randint(popsize, (popsize, 2, 2), device=device, generator=rng)
        parents = tournament(population.rank, population.crowding, pairs)
        cross = torch.rand(popsize, device=device, dtype=genes.dtype, generator=rng)
        noise = torch.randn(genes.shape, device=device, dtype=genes.dtype, generator=rng)
        children = vary(population.genes, parents, cross, noise, step_sigma)
        child_objectives, child_violation = _evaluate(evaluate, children)
        population = environmental_selection(torch.cat((population.genes, children)),
                                               torch.cat((population.objectives, child_objectives)),
                                               torch.cat((population.violation, child_violation)), popsize)
        if step_control is not None:
            step_control.observe(population.objectives.cpu().numpy())
        if on_generation is not None:
            on_generation(generation, generations)
    return population
