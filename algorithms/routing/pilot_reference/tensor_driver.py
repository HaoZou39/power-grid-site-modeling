"""Complete PILOT tensor evolution with explicit CPU planner boundaries."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
import math
import time

import torch

from algorithms.routing.evaluation_budget import UNBOUNDED
from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
from modeling.routing.tensor_queries import TensorRouteGeometry
from .driver import initialize as cpu_initialize
from .hybrid import build_population
from .local_search import local_due
from .tensor_geometry import PilotTensorGeometry
from .tensor_runtime import TensorRunState
from .tensor_population import (TensorPopulation, ranked, parent_pairs, select_population,
                                inherited_survival, updated_survival)
from .tensor_variation import offspring
from .tensor_local_search import refine_population


@contextmanager
def _cpu_scoring(budget, evaluator):
    original = budget.evaluator
    budget.evaluator = evaluator
    try:
        yield
    finally:
        budget.evaluator = original


def initialize(evaluator, config, rng, budget, report, *, corridor=True):
    cpu = CompiledRouteEvaluator(evaluator.problem)
    cpu_config = replace(config, evolution_backend="numpy", evaluation_backend="compiled_cpu", devices=["cpu"])
    with _cpu_scoring(budget, cpu):
        initial = cpu_initialize(cpu, cpu_config, rng, budget, report, corridor=corridor)
    initial.run_state.config = config
    initial.diagnostics.update(implementation="pilot_tensor", initialization_device="cpu",
        planner_device="cpu", initialization_evaluation_backend="compiled_cpu",
        elite_quota_schedule="ordered_dynamic", logical_batch_order="trial_then_route")
    return initial


def _host_candidates(population, state):
    return [state.host.candidates[state.budget.records[index][0].towers.tobytes()]
            for index in population.ids.cpu().tolist()]


def _inject(population, bounds, state, select, old_routes, old_survival, fresh_builder):
    if not state.budget.remaining_for("global_search"):
        return population
    rank, _ = ranked(population, state.config, state.geometry.geometry.workspace_bytes)
    front = ((population.values.violation <= 0) & (rank == 0)).nonzero().flatten()
    dominated = torch.ones(len(population), dtype=torch.bool, device=state.device)
    dominated[front] = False
    if not bool(dominated.any()):
        return population
    state.count("global_calls")
    target = max(state.core.global_min_new, math.ceil(state.config.popsize * state.core.global_fraction))
    survival = inherited_survival(old_routes, old_survival, population.routes, state.config.gpu_memory_budget_mib)
    stagnant = (dominated & (survival >= state.core.stagnation_limit)).nonzero().flatten()
    window = state.budget.window("global_search", state.config.pilot.global_budget_factor * state.config.popsize)
    count = max(1, target//2)
    if fresh_builder is None:
        with _cpu_scoring(state.budget, state.host.evaluator):
            fresh = build_population(state.host, bounds, window, count, include_astar=False, include_rrt=True,
                                     fallback=_host_candidates(population, state), anchor_for_fill=True, category="global")
        state.remember()
        fresh = state.from_candidates(fresh)
    else:
        fresh = fresh_builder(state, bounds, window, count, population)
    additions = [fresh]
    state.count("global_random_submitted", len(fresh))
    pool = front
    if len(pool) < 2:
        feasible = (population.values.violation <= 0).nonzero().flatten()
        pool = feasible if len(feasible) > 1 else torch.arange(len(population), device=state.device)
    if target > count and window.remaining:
        # Uniform without replacement within each pair; no tournament in this phase.
        pairs = torch.rand((target-count, len(pool)), device=state.device, dtype=torch.float64,
                           generator=state.generator).argsort(dim=1, stable=True)[:, :min(2, len(pool))]
        first, second = pool[pairs[:, 0]], pool[pairs[:, -1]]
        added = offspring(population.take(first), population.take(second), bounds, state, window)
        additions.append(added)
        state.count("global_offspring_submitted", len(added))
    added = TensorPopulation.concatenate(additions)
    remove = stagnant[:min(len(stagnant), len(added))]
    keep = torch.ones(len(population), device=state.device, dtype=torch.bool)
    keep[remove] = False
    state.count("global_stagnant_removed", len(remove))
    result = select(TensorPopulation.concatenate([population.take(keep), added]))
    known = inherited_survival(population.routes, torch.ones(len(population), device=state.device, dtype=torch.long),
                               result.routes, state.config.gpu_memory_budget_mib)
    state.count("global_new_survivors", (known == 0).sum())
    state.count("global_evaluations", window.used)
    return result


@torch.no_grad()
def evolve(evaluator, config, initial, budget, rng, report, *, fresh_builder=None, max_generations=None):
    if max_generations is not None and (type(max_generations) is not int or max_generations < 1):
        raise ValueError("max_generations must be a positive integer")
    if config.evolution_backend != "tensor" or config.evaluation_backend != "tensor":
        raise ValueError("PILOT tensor driver requires tensor evolution and evaluation")
    if max_generations is not None:
        config = replace(config, max_generations=max_generations)
    if set(config.pilot.enabled_mechanisms) <= {"cpu_driver", "rrt", "astar"}:
        from ..components import tensor_driver
        return tensor_driver(evaluator, config, initial, budget, rng, report)
    engine = evaluator.engines[0] if hasattr(evaluator, "engines") else evaluator
    geometry = PilotTensorGeometry(TensorRouteGeometry(engine), config)
    state = TensorRunState(initial.run_state, geometry, torch.Generator(device=engine.device).manual_seed(config.seed))
    expansions, generation = [], 0
    elapsed = {"ranking_s": 0., "variation_and_repair_s": 0., "local_search_s": 0., "global_search_s": 0.}
    def select(population):
        started = time.perf_counter()
        result = select_population(population, config.popsize, config, geometry.geometry.workspace_bytes,
                                   state.diagnostics, deduplicate="population_dedup" in config.pilot.enabled_mechanisms)
        # Crossover/repair scratch capacity is not an inherited chromosome length.
        width = int(result.routes.counts.max()) if len(result) else 0
        result.routes = type(result.routes)(result.routes.xy[:, :width].contiguous(), result.routes.counts)
        elapsed["ranking_s"] += time.perf_counter()-started
        return result
    try:
        from modeling.routing.types import Route
        population = state.from_candidates([state.host.lookup(Route(p.genes)) for p in initial.population])
        bounds = initial.bounds
        global_enabled = "global_injection" in config.pilot.enabled_mechanisms
        survival = updated_survival(None, None, population.routes, config.gpu_memory_budget_mib)
        window = budget.window("offspring", UNBOUNDED)
        while len(population) and generation < config.max_generations:
            state.checkpoint()
            generation += 1
            old_routes, old_survival = population.routes, survival
            expanded = bounds.expand(generation, config)
            if expanded:
                expansions.append({"generation": generation, "upper": bounds.upper, "evaluations": len(budget.records)})
                if bounds.probe_upper is not None:
                    expansions[-1]["probe_upper"] = bounds.probe_upper
            started = time.perf_counter()
            rank, crowd = ranked(population, config, geometry.geometry.workspace_bytes)
            pairs, retries = parent_pairs(population, config.popsize, rank, crowd, config, state.generator,
                                          distinct="distinct_parents" in config.pilot.enabled_mechanisms)
            state.count("parent_pairs", len(pairs))
            state.count("parent_retries", retries.sum())
            state.count("same_parent_pairs", (pairs[:, 0] == pairs[:, 1]).sum())
            elapsed["ranking_s"] += time.perf_counter()-started
            first, second = population.take(pairs[:, 0]), population.take(pairs[:, 1])
            hint = second.routes.counts.where(state.better(first, second), first.routes.counts)
            if expanded:
                hint[0] = bounds.probe_upper if bounds.probe_upper is not None else bounds.upper
            started, before_evaluation = time.perf_counter(), budget.evaluation_s
            children = offspring(first, second, bounds, state, window, target_count=hint)
            elapsed["variation_and_repair_s"] += time.perf_counter()-started-(budget.evaluation_s-before_evaluation)
            state.count("offspring_submitted", len(children))
            population = select(TensorPopulation.concatenate([population, children]))
            if "elite_local_search" in config.pilot.enabled_mechanisms and local_due(generation, state.core):
                state.diagnostics.setdefault("local_generations", []).append(generation)
                started = time.perf_counter()
                population = refine_population(population, bounds, state, select)
                elapsed["local_search_s"] += time.perf_counter()-started
            if global_enabled:
                started = time.perf_counter()
                population = _inject(population, bounds, state, select, old_routes, old_survival, fresh_builder)
                elapsed["global_search_s"] += time.perf_counter()-started
            survival = updated_survival(old_routes, old_survival, population.routes, config.gpu_memory_budget_mib)
            inherited = inherited_survival(old_routes, old_survival, population.routes, config.gpu_memory_budget_mib)
            totals = state.diagnostics.setdefault("new_survivor_sources", {})
            for candidate in _host_candidates(population.take(inherited == 0), state):
                origin = state.host.origins[candidate.key]
                totals[origin] = totals.get(origin, 0)+1
            budget.completed_generations = generation
            report("evolution", f"PILOT 张量 {engine.device} 第 {generation}/{config.max_generations} 代，已评价 {len(budget.records)} 次")
        budget.stop_reason = "generation_limit"
        state.diagnostics["final_population_sources"] = dict(Counter(state.host.origins[c.key] for c in _host_candidates(population, state)))
        state.diagnostics["survival_max"] = int(survival.max()) if len(survival) else 0
        state.diagnostics.update(geometry_queries={name: getattr(geometry.geometry, name) for name in
            ("tower_queries", "span_queries", "path_queries", "cpu_rechecks")},
            node_checks=state.host.adapter.node_checks, edge_checks=state.host.adapter.edge_checks)
        return expansions, elapsed, generation
    finally:
        geometry.close()
