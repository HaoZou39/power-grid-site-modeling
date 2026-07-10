from __future__ import annotations

import torch


def compute_road_distance_loss(
    road_segments_local: torch.Tensor,
    road_voronoi: torch.Tensor,
    pose_batch: torch.Tensor,
    eps: float = 1e-9,
) -> torch.Tensor:
    if road_segments_local.ndim != 2 or road_segments_local.shape[1] != 4:
        raise ValueError("road_segments_local must have shape [N_seg, 4]")
    if road_voronoi.ndim != 2 or road_voronoi.dtype != torch.long:
        raise ValueError("road_voronoi must be a 2D long tensor")
    if pose_batch.ndim != 2 or pose_batch.shape[1] != 3:
        raise ValueError("pose_batch must have shape [B, 3]")
    if not (road_segments_local.is_cuda and road_voronoi.is_cuda and pose_batch.is_cuda):
        raise ValueError("road inputs must all be CUDA tensors")
    if not torch.isfinite(road_segments_local).all() or not torch.isfinite(pose_batch).all():
        raise ValueError("road inputs contain NaN or Inf")
    h, w = road_voronoi.shape
    x = pose_batch[:, 0]
    y = pose_batch[:, 1]
    col = torch.floor(x).long().clamp(0, w - 2)
    row = torch.floor(y).long().clamp(0, h - 2)
    seg_ids = torch.stack(
        [
            road_voronoi[row, col],
            road_voronoi[row, col + 1],
            road_voronoi[row + 1, col],
            road_voronoi[row + 1, col + 1],
        ],
        dim=1,
    )
    if seg_ids.min() < 0 or seg_ids.max() >= road_segments_local.shape[0]:
        raise ValueError("road_voronoi contains invalid segment ids")
    segments = road_segments_local[seg_ids]
    p = pose_batch[:, None, 0:2]
    a = segments[:, :, 0:2]
    b = segments[:, :, 2:4]
    ab = b - a
    denom = (ab * ab).sum(dim=-1).clamp_min(eps)
    t = ((p - a) * ab).sum(dim=-1) / denom
    t = t.clamp(0.0, 1.0)
    proj = a + t[:, :, None] * ab
    d = torch.sqrt(((p - proj) ** 2).sum(dim=-1) + eps)
    a_frac = x - torch.floor(x)
    b_frac = y - torch.floor(y)
    weights = torch.stack(
        [
            (1.0 - a_frac) * (1.0 - b_frac),
            a_frac * (1.0 - b_frac),
            (1.0 - a_frac) * b_frac,
            a_frac * b_frac,
        ],
        dim=1,
    )
    return (weights * d).sum(dim=1)

