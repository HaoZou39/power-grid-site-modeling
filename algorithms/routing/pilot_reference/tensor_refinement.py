"""Ordered VNS trials, parallel across independent route lanes."""

import torch

from .tensor_variation import _replace


def vns(current, state, window, *, exhaustive=False, indices=None, noise=None, quota=None):
    """`quota` is each lane's own evaluation allowance; lanes never borrow from each other."""
    routes, best = current.routes, current
    width, size = routes.xy.shape[1], len(routes)
    if not width or not window.remaining:
        return current
    rows = torch.arange(size, device=state.device)
    quota = (torch.full((size,), window.remaining, device=state.device, dtype=torch.long)
             if quota is None else quota.to(state.device).clone())
    exhaustive = torch.as_tensor(exhaustive, device=state.device).expand(size)
    if indices is None:
        ordered = torch.arange(width, device=state.device).expand(size, -1)
        random = torch.rand((size, width), device=state.device, dtype=torch.float64, generator=state.generator)
        shuffled = random.masked_fill(~routes.valid, torch.inf).argsort(dim=1, stable=True)
        indices = torch.where(exhaustive[:, None], ordered, shuffled)
    for position in range(indices.shape[1]):
        if not window.remaining:
            break
        index = indices[:, position]
        live = (index >= 0) & (index < best.routes.counts) & (quota > 0)
        live &= exhaustive | (position < state.core.vns_fast_points)
        if not bool(live.any()):
            continue
        index = index.clamp(0, best.routes.xy.shape[1]-1)
        base = best.routes.xy[rows, index].clone()
        radius = state.geometry.radii(base)
        reference_radius = radius / state.scale
        tries = torch.where(exhaustive,
            reference_radius.round().long().clamp_min(state.core.vns_exhaustive_min_tries),
            (state.core.vns_fast_try_factor * reference_radius).round().long().clamp_min(state.core.vns_fast_min_tries))
        projection = reference_radius.round().clamp_min(state.core.projection_min_radius) * state.scale
        sigma = torch.where(exhaustive, torch.full_like(radius, state.core.vns_exhaustive_sigma),
                            torch.full_like(radius, state.core.vns_fast_sigma)) * radius
        local_best = best
        for attempt in range(int(tries[live].max())):
            if not window.remaining:
                break
            active = live & (index < local_best.routes.counts) & (attempt < tries) & (quota > 0)
            if not bool(active.any()):
                continue
            state.count("vns_draws", active.sum())
            normal = (torch.randn((size, 2), device=state.device, dtype=torch.float64, generator=state.generator)
                      if noise is None else noise[position, attempt])
            moved = state.geometry.project(base + sigma[:, None] * normal, projection,
                                           prefer_clearance=state.core.vns_clearance_bias)
            points = state.points(local_best.routes)
            allowed = active & state.geometry.geometry.spans(points[rows, index], moved)
            allowed &= state.geometry.geometry.spans(moved, points[rows, index + 2])
            candidate = state.geometry.deduplicate(_replace(local_best.routes, index, moved))
            changed = candidate.counts != local_best.routes.counts
            if bool(changed.any()):
                allowed[changed] &= state.geometry.geometry.paths(candidate.take(changed))
            scored = state.score(candidate, window, allowed=allowed, origin="vns")
            accepted = state.better(local_best, scored)
            quota -= (scored.ids >= 0).long()
            state.count("vns_evaluations", (scored.ids >= 0).sum())
            state.count("vns_accepts", accepted.sum())
            local_best = scored.where(accepted, local_best)
        best = local_best
    return best
