"""Ordered PILOT operators, parallel across independent route lanes."""

import torch

from modeling.routing.tensor_types import TowerBatch
from modeling.routing.device_memory import require_workspace
from .tensor_repair import sample_routes


def _replace(routes, indices, positions):
    result = routes.clone()
    result.xy[torch.arange(len(routes), device=routes.xy.device), indices] = positions
    return result


def _fold(best, routes, allowed, state, window, name, **comparison):
    candidate = state.score(routes, window, allowed=allowed, origin=name)
    accepted = state.better(best, candidate, **comparison)
    state.count(name + "_evaluations", (candidate.ids >= 0).sum())
    state.count(name + "_accepts", accepted.sum())
    return candidate.where(accepted, best), accepted


def crossover(first, second, state, window, *, active=None):
    a, b = first.routes, second.routes
    best = second.where(state.better(first, second), first)
    if not len(a) or not a.xy.shape[1] or not b.xy.shape[1]:
        return best
    active = torch.ones(len(a), device=a.xy.device, dtype=torch.bool) if active is None else active.clone()
    active &= (a.counts > 0) & (b.counts > 0)
    # Only the nearest point in B for each A point is needed. Tile the A axis.
    require_workspace(a.xy.device, len(a) * (a.xy.shape[1] + b.xy.shape[1]) * 128,
                      state.config.gpu_memory_budget_mib)
    nearest, distance = torch.zeros_like(a.counts[:, None].expand(-1, a.xy.shape[1])), a.xy.new_empty(a.xy.shape[:2])
    tile = max(1, state.geometry.geometry.workspace_bytes // max(1, len(a) * b.xy.shape[1] * 32))
    for start in range(0, a.xy.shape[1], tile):
        squared = (a.xy[:, start:start + tile, None] - b.xy[:, None]).square().sum(-1)
        squared.masked_fill_(~b.valid[:, None], torch.inf)
        distance[:, start:start + tile], nearest[:, start:start + tile] = squared.min(-1)
    distance.masked_fill_(~a.valid, torch.inf)
    pairs = distance.argsort(dim=1, stable=True)
    rows = torch.arange(len(a), device=a.xy.device)
    for trial in range(min(a.xy.shape[1], max(1, state.core.crossover_max_pairs))):
        if not window.remaining or not bool(active.any()):
            break
        i = pairs[:, trial]
        j = nearest[rows, i]
        live = active & (trial < a.counts)
        state.count("crossover_pairs", live.sum())
        live &= state.geometry.geometry.spans(a.xy[rows, i], b.xy[rows, j])
        improved = torch.zeros_like(live)
        for left, right, li, ri in ((a, b, i, j), (b, a, j, i)):
            width = left.xy.shape[1] + right.xy.shape[1]
            require_workspace(a.xy.device, len(a) * max(1, width) * 64, state.config.gpu_memory_budget_mib)
            # 未入选的行不参与本次拼接。其下标可能落在有效塔之外，塔数会变成负数，
            # connected_points 随后会把终点写到起点上。
            counts = torch.where(live, li + 1 + right.counts - ri, torch.zeros_like(li))
            columns = torch.arange(width, device=a.xy.device)[None].expand(len(a), -1)
            prefix = columns <= li[:, None]
            lidx = columns.clamp_max(left.xy.shape[1] - 1)
            ridx = (ri[:, None] + columns - li[:, None] - 1).clamp(0, right.xy.shape[1] - 1)
            xy = torch.where(prefix[..., None], left.xy.gather(1, lidx[..., None].expand(-1, -1, 2)),
                             right.xy.gather(1, ridx[..., None].expand(-1, -1, 2)))
            raw = TowerBatch(xy, counts)
            state.count("crossover_raw_candidates", live.sum())
            clean = state.geometry.sanitize(raw)
            allowed = live & state.geometry.geometry.paths(clean)
            best, accepted = _fold(best, clean, allowed, state, window, "crossover")
            improved |= accepted
        active &= ~improved
    return best


def mutate(current, state, window, *, active=None, indices=None, proposals=None):
    routes = current.routes
    if not routes.xy.shape[1] or not window.remaining:
        return current
    rows = torch.arange(len(routes), device=routes.xy.device)
    if indices is None:
        indices = (torch.rand(len(routes), device=rows.device, generator=state.generator, dtype=torch.float64)
                   * routes.counts).long()
    active = routes.counts > 0 if active is None else active & (routes.counts > 0)
    base = routes.xy[rows, indices]
    radius = state.geometry.radii(base)
    projection = (radius / state.scale).round().clamp_min(state.core.projection_min_radius) * state.scale
    points = state.points(routes)
    best = current
    for attempt in range(max(1, state.core.mutation_tries)):
        if not window.remaining or not bool(active.any()):
            break
        if proposals is None:
            draw = torch.rand((len(routes), 2), device=rows.device, dtype=torch.float64, generator=state.generator)
            angle = draw[:, 0] * (2 * torch.pi)
            distance = (state.core.mutation_min_fraction + draw[:, 1] * (1 - state.core.mutation_min_fraction)) * radius
            moved = base + distance[:, None] * torch.stack((angle.cos(), angle.sin()), -1)
        else:
            moved = proposals[attempt]
        state.count("mutation_draws", active.sum())
        moved = state.geometry.project(moved, projection, prefer_clearance=state.core.mutation_clearance_bias)
        allowed = active & state.geometry.geometry.spans(points[rows, indices], moved)
        allowed &= state.geometry.geometry.spans(moved, points[rows, indices + 2])
        candidate = state.geometry.deduplicate(_replace(routes, indices, moved))
        allowed &= state.geometry.geometry.paths(candidate)
        best, _ = _fold(best, candidate, allowed, state, window, "mutation")
    return best


def shorten(current, state, window):
    routes, best = current.routes, current
    width = routes.xy.shape[1]
    points = state.points(routes)
    rows = torch.arange(len(routes), device=routes.xy.device)
    for index in range(width):
        if not window.remaining:
            break
        allowed = (routes.counts > 1) & (routes.counts > index)
        allowed &= state.geometry.geometry.spans(points[:, index], points[:, index + 2])
        columns = torch.arange(width, device=rows.device)
        source = (columns + (columns >= index)).clamp_max(max(0, width - 1))
        candidate = TowerBatch(routes.xy[:, source], (routes.counts - 1).clamp_min(0))
        best, _ = _fold(best, candidate, allowed, state, window, "shorten", target=1,
                        margin=state.core.shorten_margin * state.scale)
    return best


def smooth(current, state, window):
    routes, best = current.routes, current
    if not routes.xy.shape[1]:
        return best
    points = state.points(routes)
    normalized = points / state.scale
    a, b = normalized[:, 1:-1] - normalized[:, :-2], normalized[:, 2:] - normalized[:, 1:-1]
    denominator = torch.linalg.vector_norm(a, dim=-1) * torch.linalg.vector_norm(b, dim=-1) + 1e-8
    angles = ((a * b).sum(-1) / denominator).clamp(-1, 1).acos().masked_fill(~routes.valid, -torch.inf)
    priority = angles.argsort(dim=1, descending=True, stable=True)
    rows = torch.arange(len(routes), device=routes.xy.device)
    for position in range(min(routes.xy.shape[1], state.core.smooth_max_points)):
        index = priority[:, position]
        previous, center, following = points[rows, index], points[rows, index + 1], points[rows, index + 2]
        radius = state.geometry.radii(center)
        projection = (radius / state.scale).round().clamp_min(state.core.projection_min_radius) * state.scale
        for moved in (previous + state.core.smooth_previous_fraction * (center - previous),
                      center + state.core.smooth_next_fraction * (following - center)):
            if not window.remaining:
                return best
            moved = state.geometry.project(moved, projection, prefer_clearance=state.core.smooth_clearance_bias)
            candidate = state.geometry.deduplicate(_replace(routes, index, moved))
            allowed = (position < routes.counts) & state.geometry.geometry.paths(candidate)
            best, _ = _fold(best, candidate, allowed, state, window, "smooth", target=2, margin=state.core.smooth_margin)
    return best


def encode_candidate(best, hint, bounds, state):
    clean = state.geometry.sanitize(best.routes)
    desired = hint.clamp(bounds.lower, bounds.upper)
    route = sample_routes(clean, desired, state.geometry, state.generator)
    bad = ~state.geometry.geometry.paths(route)
    if bool(bad.any()):
        natural = clean.counts[bad].clamp(bounds.lower, bounds.upper)
        replacement = sample_routes(clean.take(bad), natural, state.geometry, state.generator)
        width = max(route.xy.shape[1], replacement.xy.shape[1])
        route = route.padded(width)
        route.xy[bad], route.counts[bad] = replacement.padded(width).xy, replacement.counts
    return route


def offspring(first, second, bounds, state, window, *, target_count=None):
    since = len(state.budget.records)
    best = second.where(state.better(first, second), first)
    hint = best.routes.counts.clone() if target_count is None else target_count
    mechanisms = state.config.pilot.enabled_mechanisms
    for name, probability, operation in (("nearby_crossover", state.core.crossover_probability, crossover),
                                          ("path_mutation", state.core.mutation_probability, mutate)):
        if name not in mechanisms:
            continue
        active = torch.rand(len(best), device=state.device, generator=state.generator, dtype=torch.float64) < probability
        state.count("crossover_calls" if name == "nearby_crossover" else "mutation_calls", active.sum())
        candidate = operation(first, second, state, window, active=active) if name == "nearby_crossover" else operation(best, state, window, active=active)
        best = candidate.where(state.better(best, candidate), best)
    for name, operation in (("shorten", shorten), ("smooth", smooth)):
        if name in mechanisms:
            state.count(name + "_calls", len(best))
            candidate = operation(best, state, window)
            best = candidate.where(state.better(best, candidate), best)
    routes = encode_candidate(best, hint, bounds, state)
    reused = state.reuse(routes, since)
    state.count("evaluated_offspring_reuses", (reused.ids >= 0).sum())
    scored = state.score(routes, window, allowed=reused.ids < 0, origin="offspring_encoding")
    complete = reused.where(reused.ids >= 0, scored)
    valid = (best.routes.counts >= bounds.lower) & (best.routes.counts <= bounds.upper)
    fallback = best.where(valid, first)
    return complete.where(complete.ids >= 0, fallback)
