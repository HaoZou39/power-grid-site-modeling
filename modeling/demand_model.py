from __future__ import annotations

import torch


def compute_demand_distance_loss(
    demand_points: torch.Tensor,
    demand_weights: torch.Tensor | None,
    pose_batch: torch.Tensor,
    eps: float = 1e-9,
) -> torch.Tensor:
    if demand_points.ndim != 2 or demand_points.shape[1] != 2 or demand_points.shape[0] == 0:
        raise ValueError("demand_points must have shape [N, 2] with N > 0")
    if pose_batch.ndim != 2 or pose_batch.shape[1] != 3:
        raise ValueError("pose_batch must have shape [B, 3]")
    if not (demand_points.is_cuda and pose_batch.is_cuda):
        raise ValueError("demand_points and pose_batch must be CUDA tensors")
    if not torch.isfinite(demand_points).all() or not torch.isfinite(pose_batch).all():
        raise ValueError("demand inputs contain NaN or Inf")
    xy = pose_batch[:, 0:2]
    diff = xy[:, None, :] - demand_points[None, :, :]
    dist = torch.sqrt((diff * diff).sum(dim=-1) + eps)
    if demand_weights is None:
        return dist.mean(dim=1)
    if demand_weights.ndim != 1 or demand_weights.shape[0] != demand_points.shape[0]:
        raise ValueError("demand_weights must have shape [N]")
    if not demand_weights.is_cuda:
        raise ValueError("demand_weights must be a CUDA tensor")
    if not torch.isfinite(demand_weights).all() or torch.any(demand_weights < 0) or demand_weights.sum() <= 0:
        raise ValueError("demand_weights must be finite, non-negative, and have positive sum")
    weights = demand_weights / demand_weights.sum()
    return (dist * weights[None, :]).sum(dim=1)

