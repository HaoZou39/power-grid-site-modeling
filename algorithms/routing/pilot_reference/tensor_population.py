"""Device candidates and neutral PILOT selection, identities and survival."""

from dataclasses import dataclass
import math

import torch

from algorithms.common.tensor_nsga2 import nondominated_rank, crowding_distance
from modeling.routing.device_memory import require_workspace
from modeling.routing.tensor_types import TowerBatch, TensorEvaluationBatch
from ..selection import tensor_order


@dataclass
class TensorPopulation:
    routes: TowerBatch
    values: TensorEvaluationBatch
    ids: torch.Tensor

    def __len__(self):
        return len(self.routes)

    def take(self, indices):
        return TensorPopulation(self.routes.take(indices), self.values.take(indices), self.ids[indices])

    def where(self, selected, other):
        return TensorPopulation(self.routes.where(selected, other.routes), self.values.where(selected, other.values),
                                torch.where(selected, self.ids, other.ids))

    @classmethod
    def concatenate(cls, populations):
        return cls(TowerBatch.concatenate([p.routes for p in populations]),
                   TensorEvaluationBatch.concatenate([p.values for p in populations]),
                   torch.cat([p.ids for p in populations]))


def better(current, candidate, core, *, target=None, margin=0.):
    first, second = current.values, candidate.values
    first_ok, second_ok = first.violation <= 0, second.violation <= 0
    accepted = (second.objectives <= first.objectives + core.dominance_tolerance).all(-1)
    accepted &= (second.objectives < first.objectives - core.dominance_tolerance).any(-1)
    if target is not None:
        targeted = second.objectives[:, target] < first.objectives[:, target] - margin
        targeted &= (second.objectives <= first.objectives + core.weak_tolerance).all(-1)
        accepted |= targeted
    accepted = torch.where(~first_ok & ~second_ok,
                           second.violation < first.violation - core.cv_tolerance, accepted)
    return torch.where(first_ok != second_ok, second_ok, accepted) & (candidate.ids >= 0)


def ranked(population, config, workspace_bytes):
    size = len(population)
    if not bool((population.ids >= 0).all()):
        raise ValueError("selection requires fully evaluated candidates")
    tile = max(1, workspace_bytes // 8)
    require_workspace(population.ids.device, min(tile, size * size) * 8, config.gpu_memory_budget_mib)
    rank = nondominated_rank(population.values.objectives, population.values.violation, tile_pairs=tile)
    return rank, crowding_distance(population.values.objectives, rank)


def _finite_crowding(values):
    return torch.nan_to_num(values, nan=-1., posinf=1e9)


def tournament(population, rank, crowding, contenders, coins, core):
    a, b = contenders.unbind(-1)
    cv = population.values.violation
    first_ok, second_ok = cv[a] <= 0, cv[b] <= 0
    ca, cb = _finite_crowding(crowding[a]), _finite_crowding(crowding[b])
    choose_a = torch.where(ca > cb + core.crowding_tolerance, True,
                           torch.where(cb > ca + core.crowding_tolerance, False, coins < .5))
    choose_a = torch.where(rank[a] != rank[b], rank[a] < rank[b], choose_a)
    choose_a = torch.where(~first_ok & ~second_ok, ~(cv[b] < cv[a] - core.cv_tolerance), choose_a)
    choose_a = torch.where(first_ok != second_ok, first_ok, choose_a)
    return torch.where(choose_a, a, b)


def _draw_contenders(size, shape, device, generator):
    first = torch.randint(size, shape, device=device, generator=generator)
    other = torch.randint(size - 1, shape, device=device, generator=generator)
    second = other + (other >= first)
    return torch.stack((first, second), -1), torch.rand(shape, device=device, generator=generator, dtype=torch.float64)


def parent_pairs(population, count, rank, crowding, config, generator, *, distinct):
    if not len(population):
        raise ValueError("PILOT parent selection requires a population")
    device, core = population.ids.device, config.pilot.core
    retries = torch.zeros(count, device=device, dtype=torch.long)
    if len(population) == 1:
        return torch.zeros((count, 2), device=device, dtype=torch.long), retries
    contenders, coins = _draw_contenders(len(population), (count, 2), device, generator)
    result = tournament(population, rank, crowding, contenders, coins, core)
    if distinct:
        for _ in range(core.parent_retries):
            pending = result[:, 0] == result[:, 1]
            if not bool(pending.any()):
                break
            contenders, coins = _draw_contenders(len(population), (count,), device, generator)
            replacement = tournament(population, rank, crowding, contenders, coins, core)
            result[:, 1] = torch.where(pending, replacement, result[:, 1])
            retries += pending.long()
    return result, retries


def identity_groups(routes, budget_mib):
    width = routes.xy.shape[1]
    require_workspace(routes.xy.device, len(routes) * (2 * width + 1) * 32, budget_mib)
    safe = torch.where(routes.valid[..., None], routes.xy, 0)
    bits = safe.reshape(len(routes), 2 * width).view(torch.int64)
    keys = torch.cat((routes.counts[:, None], bits), 1)
    unique, inverse = torch.unique(keys, dim=0, return_inverse=True)
    return inverse, len(unique)


def deduplicated_indices(population, config):
    require_workspace(population.ids.device, len(population) * 256, config.gpu_memory_budget_mib)
    groups, count = identity_groups(population.routes, config.gpu_memory_budget_mib)
    size, cv = len(population), population.values.violation
    rows = torch.arange(size, device=groups.device)
    first = torch.full((count,), size, device=groups.device, dtype=torch.long)
    first.scatter_reduce_(0, groups, rows, reduce="amin")
    feasible = torch.full_like(first, size)
    feasible.scatter_reduce_(0, groups, torch.where(cv <= 0, rows, size), reduce="amin")
    representatives = torch.where(feasible < size, feasible, first)
    low, high = cv.new_full((count,), torch.inf), cv.new_full((count,), -torch.inf)
    low.scatter_reduce_(0, groups, cv, reduce="amin")
    high.scatter_reduce_(0, groups, cv, reduce="amax")
    # Identical evaluated routes normally share CV. Preserve non-transitive
    # tolerance comparisons if injected/corrected records differ within a group.
    difficult = ((feasible == size) & (low < high - config.pilot.core.cv_tolerance)).nonzero().flatten()
    if len(difficult):
        order = groups.argsort(stable=True)
        lengths = torch.bincount(groups, minlength=count)
        starts = lengths.cumsum(0) - lengths
        best = representatives[difficult]
        for offset in range(1, int(lengths[difficult].max())):
            candidate = order[(starts[difficult] + offset).clamp_max(size - 1)]
            replace = (lengths[difficult] > offset) & (cv[candidate] < cv[best] - config.pilot.core.cv_tolerance)
            best = torch.where(replace, candidate, best)
        representatives[difficult] = best
    return representatives.sort().values


def select_population(population, size, config, workspace_bytes, diagnostics, *, deduplicate):
    if deduplicate:
        unique = deduplicated_indices(population, config)
        if len(unique) >= size:
            diagnostics["population_duplicates_removed"] = diagnostics.get("population_duplicates_removed", 0) + len(population) - len(unique)
            population = population.take(unique)
        else:
            diagnostics["population_dedup_rollbacks"] = diagnostics.get("population_dedup_rollbacks", 0) + 1
    rank, distance = ranked(population, config, workspace_bytes)
    return population.take(tensor_order(rank, distance, size))


def elite_indices(population, rank, crowding, config):
    front = ((population.values.violation <= 0) & (rank == 0)).nonzero().flatten()
    if not len(front):
        return front, torch.empty(0, device=front.device, dtype=torch.bool)
    core = config.pilot.core
    boundary = torch.unique(front[population.values.objectives[front].argmin(0)])
    pool = front[(front[:, None] != boundary[None, :]).all(1)]
    count = min(len(pool), max(core.sparse_min_elites, math.ceil(core.sparse_fraction * len(front))))
    sparse = pool[torch.argsort(-_finite_crowding(crowding[pool]), stable=True)[:count]]
    priority = torch.cat((boundary, sparse))
    exhaustive_count = len(priority)
    if core.local_include_rest:
        rest = front[(front[:, None] != priority[None, :]).all(1)]
        priority = torch.cat((priority, rest))
    limit = min(len(priority), max(core.local_min_elites, math.ceil(config.popsize * core.local_fraction)))
    return priority[:limit], torch.arange(limit, device=front.device) < exhaustive_count


def inherited_survival(previous, counts, current, budget_mib):
    if previous is None:
        return torch.zeros(len(current), device=current.xy.device, dtype=torch.long)
    width = max(previous.xy.shape[1], current.xy.shape[1])
    require_workspace(current.xy.device, (len(previous) + len(current)) * max(1, width) * 64, budget_mib)
    joined = TowerBatch.concatenate([previous, current])
    groups, size = identity_groups(joined, budget_mib)
    history = torch.zeros(size, device=groups.device, dtype=torch.long)
    history.scatter_reduce_(0, groups[:len(previous)], counts, reduce="amax")
    return history[groups[len(previous):]]


def updated_survival(previous, counts, current, budget_mib):
    return inherited_survival(previous, counts, current, budget_mib) + 1
