"""Ordered finite repair over tensor paths; no objective evaluations."""

import torch

from modeling.routing.device_memory import require_workspace
from modeling.routing.geometry import DISTANCE_TOL_M
from modeling.routing.tensor_types import TowerBatch, connected_points
from ..tensor_operators import _insert


@torch.no_grad()
def repair_towers(batch, geometry, generator, *, noise=None, active=None):
    config, problem = geometry.config, geometry.problem
    radius = problem.constraints.tower_radius_m
    if noise is not None and (noise.shape != (config.repair_attempts, *batch.xy.shape)
                              or noise.dtype != batch.xy.dtype or noise.device != batch.xy.device):
        raise ValueError("tower repair noise must be a float64 [tries,B,K,2] tensor on its device")
    require_workspace(batch.xy.device, batch.xy.numel() * 24,
                      geometry.geometry.evaluator.config.gpu_memory_budget_mib)
    result = batch.clone()
    if min(problem.frame.width, problem.frame.height) < 2 * radius or not len(batch):
        return result
    valid = batch.valid
    if active is not None:
        valid &= active[:, None]
    allowed = torch.ones_like(valid)
    allowed[valid] = geometry.geometry.towers(batch.xy[valid])
    pending = valid & ~allowed
    upper = batch.xy.new_tensor([problem.frame.width - radius, problem.frame.height - radius])
    for attempt in range(config.repair_attempts):
        if not bool(pending.any()):
            break
        normal = (torch.randn(batch.xy.shape, device=batch.xy.device, dtype=batch.xy.dtype, generator=generator)
                  if noise is None else noise[attempt])
        candidate = (batch.xy + config.mutation_scale * problem.constraints.max_span_m * normal).clamp_min(radius).minimum(upper)
        accepted = torch.zeros_like(pending)
        accepted[pending] = geometry.geometry.towers(candidate[pending])
        result.xy[accepted] = candidate[accepted]
        pending &= ~accepted
    return result


@torch.no_grad()
def repair_spans(batch, geometry, generator, *, noise=None):
    if not len(batch):
        return batch.clone()
    config, problem = geometry.config, geometry.problem
    width = batch.xy.shape[1] + config.repair_attempts
    require_workspace(batch.xy.device, len(batch) * max(1, width) * 192,
                      geometry.geometry.evaluator.config.gpu_memory_budget_mib)
    result = batch.padded(width)
    for iteration in range(config.repair_attempts):
        points = connected_points(result.xy, result.counts, result.xy.new_tensor(problem.start.copy()),
                                  result.xy.new_tensor(problem.end.copy()))
        lengths = torch.linalg.vector_norm(points[:, 1:] - points[:, :-1], dim=-1)
        lengths.masked_fill_(torch.arange(width + 1, device=result.xy.device)[None, :] > result.counts[:, None], -torch.inf)
        maximum, index = lengths.max(1)
        active = maximum > problem.constraints.max_span_m + DISTANCE_TOL_M
        if not bool(active.any()):
            break
        rows = torch.arange(len(batch), device=result.xy.device)
        middle = (points[rows, index] + points[rows, index + 1]) / 2
        xy, counts = _insert(result.xy, result.counts, index, middle, active)
        result = repair_towers(TowerBatch(xy, counts), geometry, generator,
                               noise=None if noise is None else noise[iteration], active=active)
    return result


@torch.no_grad()
def sample_routes(batch, counts, geometry, generator, *, repair_noise=None):
    result = geometry.resample(batch, counts)
    result.xy[result.valid] = geometry.project(result.xy[result.valid], geometry.core.resample_radius * geometry.scale)
    clean = geometry.deduplicate(result)
    indices = (clean.counts != counts).nonzero().flatten()
    if len(indices):
        second = geometry.resample(clean.take(indices), counts[indices])
        second.xy[second.valid] = geometry.project(second.xy[second.valid], geometry.core.resample_radius * geometry.scale)
        width = max(clean.xy.shape[1], second.xy.shape[1])
        clean = clean.padded(width)
        clean.xy[indices] = second.padded(width).xy
        clean.counts[indices] = second.counts
    return repair_spans(clean, geometry, generator, noise=repair_noise)
