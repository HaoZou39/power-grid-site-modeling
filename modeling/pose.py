"""站址姿态。

把无界的 raw pose `[x, y, theta]` 变成场地内的连续 1 m 坐标。搜索算法优化 raw pose，边界转换只在这里。
"""

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
    pose_bounds: tuple[float, float, float, float] | None = None,
) -> torch.Tensor:
    if raw_pose.ndim != 2 or raw_pose.shape[1] != 3:
        raise ValueError(f"raw_pose must have shape [B, 3], got {tuple(raw_pose.shape)}")
    if raw_pose.device.type not in {"cpu", "cuda"}:
        raise ValueError("raw_pose must be a CPU or CUDA tensor")
    if not torch.isfinite(raw_pose).all():
        raise ValueError("raw_pose contains NaN or Inf")
    h, w = matrix_shape
    safe_margin = compute_safe_margin(rect_w_m, rect_h_m)
    xmin, xmax = safe_margin, w - 1 - safe_margin
    ymin, ymax = safe_margin, h - 1 - safe_margin
    if xmax <= xmin or ymax <= ymin:
        raise ValueError("matrix shape is too small for the configured rectangle")
    if pose_bounds is not None:
        xmin, xmax, ymin, ymax = (float(value) for value in pose_bounds)
        if not all(math.isfinite(value) for value in (xmin, xmax, ymin, ymax)):
            raise ValueError("pose_bounds must contain finite values")
        if (
            xmin < safe_margin
            or xmax > w - 1 - safe_margin
            or ymin < safe_margin
            or ymax > h - 1 - safe_margin
            or xmax <= xmin
            or ymax <= ymin
        ):
            raise ValueError("pose_bounds must be a non-empty subset of the safe scene bounds")
    u = torch.sigmoid(raw_pose)
    x = xmin + (xmax - xmin) * u[:, 0]
    y = ymin + (ymax - ymin) * u[:, 1]
    theta = -math.pi + 2.0 * math.pi * u[:, 2]
    return torch.stack([x, y, theta], dim=1)
