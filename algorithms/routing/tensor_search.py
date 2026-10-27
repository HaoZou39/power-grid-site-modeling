"""Tensor evolution with one global selection and an external exact evaluator."""

import time

import numpy as np
import torch

from modeling.routing.device_memory import require_workspace
from .repair import repair_towers
from .operators import offspring
from .tensor_operators import TowerBatch, vary
from .selection import tensor_selection
from .ranges import expand_range


@torch.no_grad()
def evolve(evaluator, config, bounds, records, evaluate_many, report, *, variation=None,
           repair=None, boundary_variation=None, selection=None, range_policy=None):
    variation = vary if variation is None else variation
    repair = repair_towers if repair is None else repair
    boundary_variation = offspring if boundary_variation is None else boundary_variation
    selection = tensor_selection() if selection is None else selection
    range_policy = expand_range if range_policy is None else range_policy
    device = torch.device(config.devices[0])
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("routing explicitly requested CUDA but CUDA is unavailable")
    generator = torch.Generator(device=device).manual_seed(config.seed)
    repair_rng = np.random.default_rng(config.seed)
    entries = [(r, e) for r, e in records if bounds.lower <= len(r.towers) <= bounds.upper]
    require_workspace(device, len(entries) * max(1, bounds.upper) * 16 * 4, config.gpu_memory_budget_mib)
    population = TowerBatch.from_routes([r for r, _ in entries], device, bounds.upper)
    objectives = torch.tensor([e.objectives.tolist() for _, e in entries], device=device, dtype=torch.float64)
    cv = torch.tensor([e.violation for _, e in entries], device=device, dtype=torch.float64)
    # Three boolean pair buffers plus indexing/reductions fit within this reserve.
    tile_pairs = max(1, min(1 << 26, config.gpu_memory_budget_mib * 1024**2 // 32))
    elapsed = {"ranking_s": 0., "variation_and_repair_s": 0., "evaluation_s": 0.}

    def select(batch, values, violations):
        started = time.perf_counter()
        require_workspace(device, min(tile_pairs, len(values)**2) * 8, config.gpu_memory_budget_mib)
        rank = selection.rank(values, violations, tile_pairs=tile_pairs)
        distance = selection.crowding(values, rank)
        order = selection.order(rank, distance, config.popsize)
        retained = batch.take(order)
        values, violations, rank = values[order], violations[order], rank[order]
        distance = selection.crowding(values, rank)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        elapsed["ranking_s"] += time.perf_counter() - started
        return retained, values, violations, rank, distance

    population, objectives, cv, rank, distance = select(population, objectives, cv)
    generation, expansions = 0, []
    while len(records) < config.max_evaluations:
        generation += 1
        expanded = range_policy(bounds, generation, config)
        if expanded:
            expansions.append({"generation": generation, "upper": bounds.upper, "evaluations": len(records)})
            population.capacity(bounds.upper)
        started = time.perf_counter()
        count = min(config.popsize, config.max_evaluations - len(records))
        require_workspace(device, max(1, bounds.upper) * count * 16 * 24, config.gpu_memory_budget_mib)
        pairs = torch.randint(len(population.xy), (count, 2, 2), device=device, generator=generator)
        parents = selection.parents(rank, distance, pairs)
        first, second = population.take(parents[:, 0]), population.take(parents[:, 1])
        # Other children keep their operator-determined count; only the boundary probe is forced.
        children = variation(first, second, start=population.xy.new_tensor(evaluator.problem.start.copy()),
            end=population.xy.new_tensor(evaluator.problem.end.copy()), lower=bounds.lower, upper=bounds.upper,
            sigma=config.mutation_scale * evaluator.problem.constraints.max_span_m,
            radius=evaluator.problem.constraints.tower_radius_m,
            size=(evaluator.problem.frame.width, evaluator.problem.frame.height), generator=generator)
        routes = children.routes()
        if expanded:
            index = torch.tensor([0], device=device)
            routes[0] = boundary_variation(first.take(index).routes()[0], second.take(index).routes()[0], evaluator,
                config, repair_rng, bounds.lower, bounds.upper, target_count=bounds.upper)
        routes = [route if expanded and i == 0 else repair(route, evaluator, config, repair_rng)
                  for i, route in enumerate(routes)]
        children = TowerBatch.from_routes(routes, device, bounds.upper)
        elapsed["variation_and_repair_s"] += time.perf_counter() - started
        started = time.perf_counter()
        checked = evaluate_many(routes)
        child_values = torch.tensor([e.objectives.tolist() for e in checked], device=device, dtype=torch.float64)
        child_cv = torch.tensor([e.violation for e in checked], device=device, dtype=torch.float64)
        elapsed["evaluation_s"] += time.perf_counter() - started
        combined = TowerBatch(torch.cat((population.xy, children.xy)), torch.cat((population.counts, children.counts)))
        population, objectives, cv, rank, distance = select(combined,
            torch.cat((objectives, child_values)), torch.cat((cv, child_cv)))
        report("evolution", f"第 {generation} 代，已评价 {len(records)}/{config.max_evaluations}，塔数范围 {bounds.lower}–{bounds.upper}（张量 {device}）")
    return expansions, elapsed, generation
