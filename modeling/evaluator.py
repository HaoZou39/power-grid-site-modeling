"""评估函数的对外入口。

`evaluate_site_objectives` 返回目标字典。`compute_hard_constraints` 返回硬指标和违例。
公式不写在这里，而写在 `site_model.py` 的子类里。已有调用方继续使用这两个函数。
"""

from __future__ import annotations

import numpy as np
import torch

from .site_model import default_site_model


def evaluate_site_objectives(
    dem_tensor: torch.Tensor,
    obstacle_tensor: torch.Tensor,
    road_segments_tensor: torch.Tensor,
    road_voronoi_tensor: torch.Tensor,
    demand_points_tensor: torch.Tensor,
    demand_weights_tensor: torch.Tensor | None,
    pose_batch: torch.Tensor,
    rect_w_m: float,
    rect_h_m: float,
    soft_mask_sharpness: float,
) -> dict[str, torch.Tensor]:
    return default_site_model().evaluate_objectives(
        dem_tensor,
        obstacle_tensor,
        road_segments_tensor,
        road_voronoi_tensor,
        demand_points_tensor,
        demand_weights_tensor,
        pose_batch,
        rect_w_m,
        rect_h_m,
        soft_mask_sharpness,
    )


def compute_hard_constraints(
    dem: np.ndarray,
    obstacle_mask: np.ndarray,
    pose_batch: torch.Tensor,
    rect_w_m: float,
    rect_h_m: float,
    device: str = "cuda",
) -> dict[str, torch.Tensor]:
    return default_site_model().hard_metrics(dem, obstacle_mask, pose_batch, rect_w_m, rect_h_m, device)
