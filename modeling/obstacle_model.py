from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F


def compute_obstacle_soft_loss(
    obstacle_mask: torch.Tensor,
    grid: torch.Tensor,
    soft_mask: torch.Tensor,
) -> torch.Tensor:
    if obstacle_mask.shape[:2] != (1, 1):
        raise ValueError(f"obstacle_mask must have shape [1, 1, H, W], got {tuple(obstacle_mask.shape)}")
    if not (obstacle_mask.is_cuda and grid.is_cuda and soft_mask.is_cuda):
        raise ValueError("obstacle_mask, grid, and soft_mask must all be CUDA tensors")
    if not torch.isfinite(obstacle_mask).all() or not torch.isfinite(grid).all() or not torch.isfinite(soft_mask).all():
        raise ValueError("obstacle soft loss inputs contain NaN or Inf")
    b = grid.shape[0]
    patch = F.grid_sample(
        obstacle_mask.expand(b, -1, -1, -1),
        grid,
        mode="bilinear",
        padding_mode="border",
        align_corners=False,
    )
    values = patch[:, 0, :, :]
    denom = soft_mask.sum(dim=(1, 2)).clamp_min(torch.finfo(obstacle_mask.dtype).eps)
    return (soft_mask * values).sum(dim=(1, 2)) / denom


def compute_obstacle_hard_loss(
    obstacle_mask: np.ndarray,
    hard_indices: list[np.ndarray],
    device: str = "cuda",
) -> dict[str, torch.Tensor]:
    if obstacle_mask.ndim != 2 or obstacle_mask.size == 0 or not np.isfinite(obstacle_mask).all():
        raise ValueError("obstacle_mask must be a finite non-empty 2D array")
    counts: list[float] = []
    ratios: list[float] = []
    for idx in hard_indices:
        if idx.ndim != 2 or idx.shape[1] != 2 or idx.size == 0:
            raise ValueError("hard_indices entries must have shape [N, 2]")
        values = obstacle_mask[idx[:, 0], idx[:, 1]] > 0
        counts.append(float(np.count_nonzero(values)))
        ratios.append(float(np.mean(values)))
    return {
        "obstacle_hard_count": torch.tensor(counts, dtype=torch.float32, device=device),
        "obstacle_hard_ratio": torch.tensor(ratios, dtype=torch.float32, device=device),
    }

