"""建筑矩形的足迹。

`compute_soft_footprint` 给可微目标用。`compute_hard_footprint_indices` 给硬约束用。
改建筑覆盖范围的几何时改这个文件。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

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
    if pose_batch.device.type not in {"cpu", "cuda"}:
        raise ValueError("pose_batch must be a CPU or CUDA tensor")
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


@dataclass(frozen=True)
class HardFootprint:
    """图内足迹格子，以及落在图外的足迹格子数。"""

    inside: np.ndarray
    outside_count: int


@dataclass(frozen=True)
class TensorHardFootprint:
    rows: torch.Tensor
    cols: torch.Tensor
    inside: torch.Tensor
    outside_count: torch.Tensor


def compute_tensor_hard_footprint(
    pose_batch: torch.Tensor,
    rect_w_m: float,
    rect_h_m: float,
    matrix_shape: tuple[int, int],
) -> TensorHardFootprint:
    """Batched hard geometry; the outside cells never contribute to in-grid loss."""
    if len(matrix_shape) != 2 or min(matrix_shape) < 1:
        raise ValueError("matrix_shape must describe a non-empty 2D grid")
    if pose_batch.ndim != 2 or pose_batch.shape[1] != 3:
        raise ValueError("pose_batch must have shape [B, 3]")
    if rect_w_m <= 0 or rect_h_m <= 0 or not bool(torch.isfinite(pose_batch).all()):
        raise ValueError("rectangle dimensions must be positive and poses finite")
    height, width = matrix_shape
    pose = pose_batch.to(torch.float64)
    x, y, theta = pose.unbind(1)
    half_diag = 0.5 * math.hypot(rect_w_m, rect_h_m)
    win = math.ceil(2 * half_diag) + 4
    offset = torch.arange(win, device=pose.device)
    rows = torch.floor(y - half_diag - 1).long()[:, None, None] + offset[None, :, None]
    cols = torch.floor(x - half_diag - 1).long()[:, None, None] + offset[None, None, :]
    dx = cols + 0.5 - x[:, None, None]
    dy = rows + 0.5 - y[:, None, None]
    cos_t, sin_t = theta.cos()[:, None, None], theta.sin()[:, None, None]
    covered = ((cos_t * dx + sin_t * dy).abs() <= rect_w_m / 2) & ((-sin_t * dx + cos_t * dy).abs() <= rect_h_m / 2)
    in_grid = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
    inside = covered & in_grid
    if not bool(inside.flatten(1).any(1).all()):
        raise ValueError("hard footprint contains no pixels")
    outside = (covered & ~in_grid).sum((1, 2))
    tolerance = 2 * torch.finfo(torch.float32).eps * max(width, height, rect_w_m, rect_h_m)
    half_x = theta.cos().abs() * rect_w_m / 2 + theta.sin().abs() * rect_h_m / 2
    half_y = theta.sin().abs() * rect_w_m / 2 + theta.cos().abs() * rect_h_m / 2
    leaves = (x - half_x < -tolerance) | (x + half_x > width + tolerance) | (y - half_y < -tolerance) | (y + half_y > height + tolerance)
    return TensorHardFootprint(rows.clamp(0, height - 1), cols.clamp(0, width - 1), inside,
                              torch.maximum(outside, leaves.long()))


def compute_hard_footprints(
    pose_batch: torch.Tensor | np.ndarray,
    rect_w_m: float,
    rect_h_m: float,
    matrix_shape: tuple[int, int],
) -> list[HardFootprint]:
    """旋转矩形盖到的 1 m 格子。图内格子留给高程和禁建统计，图外格子只计违例。"""

    if rect_w_m <= 0 or rect_h_m <= 0:
        raise ValueError("rectangle dimensions must be positive")
    pose_np = pose_batch.detach().cpu().numpy() if isinstance(pose_batch, torch.Tensor) else np.asarray(pose_batch)
    if pose_np.ndim != 2 or pose_np.shape[1] != 3:
        raise ValueError(f"pose_batch must have shape [B, 3], got {pose_np.shape}")
    if not np.isfinite(pose_np).all():
        raise ValueError("pose_batch contains NaN or Inf")
    height, width = matrix_shape
    half_diag = 0.5 * math.sqrt(rect_w_m**2 + rect_h_m**2)
    out: list[HardFootprint] = []
    for x, y, theta in pose_np:
        cmin = int(math.floor(x - half_diag - 1))
        cmax = int(math.ceil(x + half_diag + 1))
        rmin = int(math.floor(y - half_diag - 1))
        rmax = int(math.ceil(y + half_diag + 1))
        rows, cols = np.meshgrid(np.arange(rmin, rmax + 1), np.arange(cmin, cmax + 1), indexing="ij")
        cx = cols.astype(np.float64) + 0.5
        cy = rows.astype(np.float64) + 0.5
        dx = cx - float(x)
        dy = cy - float(y)
        cos_t = math.cos(float(theta))
        sin_t = math.sin(float(theta))
        x_rot = cos_t * dx + sin_t * dy
        y_rot = -sin_t * dx + cos_t * dy
        covered = (np.abs(x_rot) <= rect_w_m / 2.0) & (np.abs(y_rot) <= rect_h_m / 2.0)
        inside = covered & (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
        idx = np.column_stack([rows[inside], cols[inside]]).astype(np.int64)
        if idx.size == 0:
            raise ValueError("hard footprint contains no pixels")
        outside = int(np.count_nonzero(covered & ~inside))
        # 角点越出图幅但没有格子中心落在图外时，像素计数是 0。矩形和图幅都是凸的，四个角点够用。
        if outside == 0 and _rectangle_leaves_grid(float(x), float(y), float(theta), rect_w_m, rect_h_m, height, width):
            outside = 1
        out.append(HardFootprint(idx, outside))
    return out


def _rectangle_leaves_grid(
    x: float,
    y: float,
    theta: float,
    rect_w_m: float,
    rect_h_m: float,
    height: int,
    width: int,
) -> bool:
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    half_w = rect_w_m / 2.0
    half_h = rect_h_m / 2.0
    # 重算入口把前端坐标转为 float32；贴边位置和角度都会产生舍入误差。
    tolerance_m = 2.0 * np.finfo(np.float32).eps * max(width, height, rect_w_m, rect_h_m)
    for lx, ly in ((half_w, half_h), (half_w, -half_h), (-half_w, half_h), (-half_w, -half_h)):
        px = x + cos_t * lx - sin_t * ly
        py = y + sin_t * lx + cos_t * ly
        if px < -tolerance_m or py < -tolerance_m or px > width + tolerance_m or py > height + tolerance_m:
            return True
    return False


def compute_hard_footprint_indices(
    pose_batch: torch.Tensor | np.ndarray,
    rect_w_m: float,
    rect_h_m: float,
    matrix_shape: tuple[int, int],
) -> list[np.ndarray]:
    return [footprint.inside for footprint in compute_hard_footprints(pose_batch, rect_w_m, rect_h_m, matrix_shape)]

