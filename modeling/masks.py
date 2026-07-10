from __future__ import annotations

import math

import numpy as np
import torch


def compute_soft_footprint(
    pose_batch: torch.Tensor,
    rect_w_m: float,
    rect_h_m: float,
    matrix_shape: tuple[int, int],
    sharpness: float = 8.0,
) -> dict[str, torch.Tensor]:
    if pose_batch.ndim != 2 or pose_batch.shape[1] != 3:
        raise ValueError(f"pose_batch must have shape [B, 3], got {tuple(pose_batch.shape)}")
    if not pose_batch.is_cuda:
        raise ValueError("pose_batch must be a CUDA tensor")
    if rect_w_m <= 0 or rect_h_m <= 0 or sharpness <= 0:
        raise ValueError("rectangle dimensions and sharpness must be positive")
    if not torch.isfinite(pose_batch).all():
        raise ValueError("pose_batch contains NaN or Inf")
    h, w = matrix_shape
    half_diag = 0.5 * math.sqrt(rect_w_m**2 + rect_h_m**2)
    win = int(math.ceil(2.0 * half_diag)) + 4
    if win < 3:
        raise ValueError("soft footprint window is invalid")
    offsets = torch.arange(win, device=pose_batch.device, dtype=pose_batch.dtype) - (win - 1) / 2.0
    oy, ox = torch.meshgrid(offsets, offsets, indexing="ij")
    cos_t = torch.cos(pose_batch[:, 2])[:, None, None]
    sin_t = torch.sin(pose_batch[:, 2])[:, None, None]
    dx = ox[None, :, :]
    dy = oy[None, :, :]
    x_rot = cos_t * dx + sin_t * dy
    y_rot = -sin_t * dx + cos_t * dy
    weights = torch.sigmoid(sharpness * (rect_w_m / 2.0 - torch.abs(x_rot)))
    weights = weights * torch.sigmoid(sharpness * (rect_h_m / 2.0 - torch.abs(y_rot)))
    x_sample = pose_batch[:, 0, None, None] + dx
    y_sample = pose_batch[:, 1, None, None] + dy
    grid_x = (2.0 * x_sample / float(w)) - 1.0
    grid_y = (2.0 * y_sample / float(h)) - 1.0
    grid = torch.stack([grid_x.expand_as(weights), grid_y.expand_as(weights)], dim=-1)
    return {"grid": grid, "weights": weights}


def compute_hard_footprint_indices(
    pose_batch: torch.Tensor | np.ndarray,
    rect_w_m: float,
    rect_h_m: float,
    matrix_shape: tuple[int, int],
) -> list[np.ndarray]:
    if rect_w_m <= 0 or rect_h_m <= 0:
        raise ValueError("rectangle dimensions must be positive")
    pose_np = pose_batch.detach().cpu().numpy() if isinstance(pose_batch, torch.Tensor) else np.asarray(pose_batch)
    if pose_np.ndim != 2 or pose_np.shape[1] != 3:
        raise ValueError(f"pose_batch must have shape [B, 3], got {pose_np.shape}")
    if not np.isfinite(pose_np).all():
        raise ValueError("pose_batch contains NaN or Inf")
    h, w = matrix_shape
    half_diag = 0.5 * math.sqrt(rect_w_m**2 + rect_h_m**2)
    out: list[np.ndarray] = []
    for x, y, theta in pose_np:
        cmin = max(0, int(math.floor(x - half_diag - 1)))
        cmax = min(w - 1, int(math.ceil(x + half_diag + 1)))
        rmin = max(0, int(math.floor(y - half_diag - 1)))
        rmax = min(h - 1, int(math.ceil(y + half_diag + 1)))
        rows, cols = np.meshgrid(np.arange(rmin, rmax + 1), np.arange(cmin, cmax + 1), indexing="ij")
        cx = cols.astype(np.float64) + 0.5
        cy = rows.astype(np.float64) + 0.5
        dx = cx - x
        dy = cy - y
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        x_rot = cos_t * dx + sin_t * dy
        y_rot = -sin_t * dx + cos_t * dy
        mask = (np.abs(x_rot) <= rect_w_m / 2.0) & (np.abs(y_rot) <= rect_h_m / 2.0)
        idx = np.column_stack([rows[mask], cols[mask]]).astype(np.int64)
        if idx.size == 0:
            raise ValueError("hard footprint contains no pixels")
        out.append(idx)
    return out

