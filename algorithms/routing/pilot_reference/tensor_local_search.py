"""Equal elite quotas, all elites as parallel VNS lanes, and post-encoding acceptance on device candidates."""

import torch

from .tensor_population import TensorPopulation, ranked, elite_indices, identity_groups
from .tensor_refinement import vns
from .tensor_variation import encode_candidate


def refine_population(population, bounds, state, select):
    if not state.budget.remaining_for("local_search"):
        return population
    rank, crowd = ranked(population, state.config, state.geometry.geometry.workspace_bytes)
    priority, exhaustive = elite_indices(population, rank, crowd, state.config)
    if not len(priority):
        return population
    state.count("local_calls")
    state.count("local_selected_elites", len(priority))
    start = len(state.budget.records)
    limit = min(state.budget.remaining_for("local_search"), state.config.pilot.local_budget_factor * state.config.popsize)
    # 平分额度，余数按精英优先顺序各加 1；每人含一次编码后评价。
    quota = torch.full((len(priority),), limit // len(priority), device=state.device, dtype=torch.long)
    quota[:limit % len(priority)] += 1
    lanes = (quota > 0).nonzero().flatten()
    if not len(lanes):
        return population
    current = population.take(priority[lanes])
    state.count("local_refined_elites", len(lanes))
    candidate = vns(current, state, state.budget.window("local_search", int(quota[lanes].sum() - len(lanes))),
                    exhaustive=exhaustive[lanes], quota=quota[lanes] - 1)
    raw = state.better(current, candidate)
    state.count("local_raw_accepts", raw.sum())
    if not bool(raw.any()):
        state.count("local_evaluations", len(state.budget.records)-start)
        return population
    current, candidate = current.take(raw.nonzero().flatten()), candidate.take(raw.nonzero().flatten())
    routes = encode_candidate(candidate, current.routes.counts, bounds, state)
    width = max(routes.xy.shape[1], candidate.routes.xy.shape[1])
    first, second = routes.padded(width), candidate.routes.padded(width)
    same = (first.counts == second.counts) & ((first.xy == second.xy) | ~first.valid[..., None]).all(-1).all(-1)
    state.count("local_encoded_reuses", same.sum())
    rescored = state.score(routes, state.budget.window("local_search", int((~same).sum())), allowed=~same,
                           origin="local_encoding")
    encoded = candidate.where(same, rescored)
    accepted = state.better(current, encoded)
    state.count("local_encoded_accepts", accepted.sum())
    state.count("local_evaluations", len(state.budget.records)-start)
    if not bool(accepted.any()):
        return population
    added = encoded.take(accepted.nonzero().flatten())
    result = select(TensorPopulation.concatenate([population, added]))
    joined = type(added.routes).concatenate([added.routes, result.routes])
    groups, _ = identity_groups(joined, state.config.gpu_memory_budget_mib)
    state.count("local_surviving_proposals", (groups[:len(added), None] == groups[None, len(added):]).any(1).sum())
    return result
