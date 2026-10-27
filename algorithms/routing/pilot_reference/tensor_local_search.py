"""Original fair elite quotas and post-encoding acceptance on device candidates."""

import math
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
    additions = []
    for position in range(len(priority)):
        remaining = min(state.budget.remaining, limit - (len(state.budget.records)-start))
        if remaining <= 0:
            break
        quota = math.ceil(remaining / (len(priority)-position))
        current = population.take(priority[position:position+1])
        state.count("local_refined_elites")
        candidate = vns(current, state, state.budget.window("local_search", max(0, quota-1)),
                        exhaustive=bool(exhaustive[position]))
        if not bool(state.better(current, candidate).any()):
            continue
        state.count("local_raw_accepts")
        routes = encode_candidate(candidate, current.routes.counts, bounds, state)
        width = max(routes.xy.shape[1], candidate.routes.xy.shape[1])
        first, second = routes.padded(width), candidate.routes.padded(width)
        same = (first.counts == second.counts) & ((first.xy == second.xy) | ~first.valid[..., None]).all(-1).all(-1)
        if bool(same.all()):
            encoded = candidate
            state.count("local_encoded_reuses")
        else:
            encoded = state.score(routes, state.budget.window("local_search", 1), origin="local_encoding")
        if bool(state.better(current, encoded).any()):
            additions.append(encoded)
            state.count("local_encoded_accepts")
    state.count("local_evaluations", len(state.budget.records)-start)
    if not additions:
        return population
    added = TensorPopulation.concatenate(additions)
    result = select(TensorPopulation.concatenate([population, added]))
    joined = type(added.routes).concatenate([added.routes, result.routes])
    groups, _ = identity_groups(joined, state.config.gpu_memory_budget_mib)
    state.count("local_surviving_proposals", (groups[:len(added), None] == groups[None, len(added):]).any(1).sum())
    return result
