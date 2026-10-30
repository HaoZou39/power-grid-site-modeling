"""Device-resident tower repair for the standard tensor search."""

import torch

from modeling.routing.tensor_geometry import tower_flags


def supports_tensor_repair(evaluator):
    """Whether exact raster tower checks are available on one tensor device."""
    problem = getattr(evaluator, "problem", None)
    device = getattr(evaluator, "device", None)
    return (problem is not None and getattr(device, "type", None) == "cuda" and not problem.no_tower_zones
            and all(hasattr(evaluator, name) for name in
                    ("dem", "blocked", "blocked_distance", "missing_distance", "workspace_bytes")))


@torch.no_grad()
def repair_towers_batch(batch, evaluator, config, generator):
    """Repair invalid active towers in parallel, preserving packed route shape.

    Polygon tower zones intentionally use the existing CPU repair because their
    exact Shapely check is not represented by the raster tensor fields.
    """
    problem = evaluator.problem
    radius = problem.constraints.tower_radius_m
    upper = batch.xy.new_tensor([problem.frame.width - radius, problem.frame.height - radius])
    if (min(problem.frame.width, problem.frame.height) < 2 * radius or not len(batch)
            or config.repair_attempts <= 0):
        return batch.clone()
    valid = batch.valid
    outside, hit, missing, _ = tower_flags(
        evaluator.dem, evaluator.blocked, batch.xy[valid], radius, evaluator.workspace_bytes,
        evaluator.blocked_distance, evaluator.missing_distance)
    allowed = torch.ones_like(valid)
    allowed[valid] = ~(outside | hit | missing)
    pending = valid & ~allowed
    result = batch.clone()
    sigma = config.mutation_scale * problem.constraints.max_span_m
    for _ in range(config.repair_attempts):
        normal = torch.randn(batch.xy.shape, device=batch.xy.device, dtype=batch.xy.dtype, generator=generator)
        candidate = (batch.xy + sigma * normal).clamp_min(radius).minimum(upper)
        outside, hit, missing, _ = tower_flags(
            evaluator.dem, evaluator.blocked, candidate[pending], radius, evaluator.workspace_bytes,
            evaluator.blocked_distance, evaluator.missing_distance)
        accepted = torch.zeros_like(pending)
        accepted[pending] = ~(outside | hit | missing)
        result.xy[accepted] = candidate[accepted]
        pending &= ~accepted
    return result
