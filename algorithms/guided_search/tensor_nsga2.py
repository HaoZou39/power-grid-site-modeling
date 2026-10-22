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


def pareto_dominance(objectives: torch.Tensor) -> torch.Tensor:
    count, width = objectives.shape
    not_worse = torch.ones((count, count), dtype=torch.bool, device=objectives.device)
    better = torch.zeros_like(not_worse)
    for column in range(width):
        values = objectives[:, column]
        not_worse &= values[:, None] <= values[None, :]
        better |= values[:, None] < values[None, :]
    return not_worse & better


def dominance_matrix(objectives: torch.Tensor, violation: torch.Tensor) -> torch.Tensor:
    """Rows dominate columns; equal positive violations still compare objectives."""
    cv = violation.clamp_min(0)
    return (cv[:, None] < cv[None, :]) | ((cv[:, None] == cv[None, :]) & pareto_dominance(objectives))


def nondominated_rank(objectives: torch.Tensor, violation: torch.Tensor) -> torch.Tensor:
    # Different CV groups are totally ordered. Peel all groups concurrently,
    # then offset their local fronts, avoiding one GPU sync per distinct CV.
    cv = violation.clamp_min(0)
    order = torch.argsort(cv, stable=True)
    ordered_cv = cv[order]
    starts = torch.cat((torch.ones(1, device=cv.device, dtype=torch.bool), ordered_cv[1:] != ordered_cv[:-1]))
    group = torch.empty_like(order)
    group[order] = starts.long().cumsum(0) - 1
    dominated = pareto_dominance(objectives) & (group[:, None] == group[None, :])
    edges = dominated.to(torch.float32)
    degree = edges.sum(0)
    front = degree == 0
    rank = torch.zeros_like(order)
    level = 0
    while bool(front.any()):
        rank = torch.where(front, level, rank)
        degree = degree - torch.mv(edges.T, front.to(edges.dtype))
        degree = torch.where(front, -1, degree)
        front = degree == 0
        level += 1
    heights = torch.zeros_like(order).scatter_reduce_(0, group, rank + 1, reduce="amax")
    offsets = heights.cumsum(0) - heights
    return rank + offsets[group]


def crowding_distance(objectives: torch.Tensor, rank: torch.Tensor) -> torch.Tensor:
    """Stable objective sorting within every front, including zero-span boundaries."""
    count, width = objectives.shape
    order = torch.argsort(objectives, dim=0, stable=True)
    order = order.gather(0, torch.argsort(rank[order], dim=0, stable=True))
    levels = rank[order]
    positions = torch.arange(count, device=objectives.device)[:, None].expand(-1, width)
    first = torch.cat((torch.ones((1, width), device=rank.device, dtype=torch.bool), levels[1:] != levels[:-1]))
    last = torch.cat((levels[:-1] != levels[1:], torch.ones((1, width), device=rank.device, dtype=torch.bool)))
    starts = torch.where(first, positions, 0).cummax(0).values
    ends = torch.where(last, positions, count - 1).flip((0,)).cummin(0).values.flip((0,))
    values = objectives.gather(0, order)
    span = values.gather(0, ends) - values.gather(0, starts)
    previous = values.gather(0, (positions - 1).clamp_min(0))
    following = values.gather(0, (positions + 1).clamp_max(count - 1))
    distances = torch.where(span > 0, (following - previous) / torch.where(span > 0, span, 1), 0)
    distances = torch.where(first | last, torch.inf, distances)
    return torch.zeros_like(objectives).scatter_(0, order, distances).sum(1)


def tournament(rank: torch.Tensor, crowding: torch.Tensor, pairs: torch.Tensor) -> torch.Tensor:
    left, right = pairs[..., 0], pairs[..., 1]
    wins = (rank[left] < rank[right]) | ((rank[left] == rank[right]) & (crowding[left] > crowding[right]))
    return torch.where(wins, left, right)


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
