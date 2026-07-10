from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F


def compute_dem_soft_loss(dem: torch.Tensor, grid: torch.Tensor, soft_mask: torch.Tensor) -> torch.Tensor:
    if dem.shape[:2] != (1, 1):
        raise ValueError(f"dem must have shape [1, 1, H, W], got {tuple(dem.shape)}")
    if not (dem.is_cuda and grid.is_cuda and soft_mask.is_cuda):
        raise ValueError("dem, grid, and soft_mask must all be CUDA tensors")
    if not torch.isfinite(dem).all() or not torch.isfinite(grid).all() or not torch.isfinite(soft_mask).all():
        raise ValueError("DEM soft loss inputs contain NaN or Inf")
    b = grid.shape[0]
    patch = F.grid_sample(dem.expand(b, -1, -1, -1), grid, mode="bilinear", padding_mode="border", align_corners=False)
    z = patch[:, 0, :, :]
    denom = soft_mask.sum(dim=(1, 2)).clamp_min(torch.finfo(dem.dtype).eps)
    mean = (soft_mask * z).sum(dim=(1, 2)) / denom
    var = (soft_mask * (z - mean[:, None, None]) ** 2).sum(dim=(1, 2)) / denom
    return var


def compute_dem_hard_loss(dem: np.ndarray, hard_indices: list[np.ndarray], device: str = "cuda") -> dict[str, torch.Tensor]:
    if dem.ndim != 2 or dem.size == 0 or not np.isfinite(dem).all():
        raise ValueError("dem must be a finite non-empty 2D array")
    vars_: list[float] = []
    ranges: list[float] = []
    for idx in hard_indices:
        if idx.ndim != 2 or idx.shape[1] != 2 or idx.size == 0:
            raise ValueError("hard_indices entries must have shape [N, 2]")
        z = dem[idx[:, 0], idx[:, 1]].astype(np.float64)
        vars_.append(float(np.var(z)))
        ranges.append(float(np.max(z) - np.min(z)))
    return {
        "dem_hard_var": torch.tensor(vars_, dtype=torch.float32, device=device),
        "dem_hard_range": torch.tensor(ranges, dtype=torch.float32, device=device),
    }

