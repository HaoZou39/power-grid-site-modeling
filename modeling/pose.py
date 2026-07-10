from __future__ import annotations

import math

import torch


def compute_safe_margin(rect_w_m: float, rect_h_m: float) -> float:
    if rect_w_m <= 0 or rect_h_m <= 0:
        raise ValueError("rectangle dimensions must be positive")
    return 0.5 * math.sqrt(rect_w_m**2 + rect_h_m**2)


def decode_raw_pose(
    raw_pose: torch.Tensor,
    matrix_shape: tuple[int, int],
    rect_w_m: float,
    rect_h_m: float,
) -> torch.Tensor:
    if raw_pose.ndim != 2 or raw_pose.shape[1] != 3:
        raise ValueError(f"raw_pose must have shape [B, 3], got {tuple(raw_pose.shape)}")
    if not raw_pose.is_cuda:
        raise ValueError("raw_pose must be a CUDA tensor")
    if not torch.isfinite(raw_pose).all():
        raise ValueError("raw_pose contains NaN or Inf")
    h, w = matrix_shape
    safe_margin = compute_safe_margin(rect_w_m, rect_h_m)
    xmin = safe_margin
    xmax = w - 1 - safe_margin
    ymin = safe_margin
    ymax = h - 1 - safe_margin
    if xmax <= xmin or ymax <= ymin:
        raise ValueError("matrix shape is too small for the configured rectangle")
    u = torch.sigmoid(raw_pose)
    x = xmin + (xmax - xmin) * u[:, 0]
    y = ymin + (ymax - ymin) * u[:, 1]
    theta = -math.pi + 2.0 * math.pi * u[:, 2]
    return torch.stack([x, y, theta], dim=1)

