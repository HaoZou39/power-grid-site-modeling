"""一次搜索共用的数据包。

`SiteProblemContext` 只保存已经对齐的 1 m 数组和张量。它不是目标或约束的父类。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch


@dataclass(frozen=True)
class SiteProblemContext:
    """Prepared 1 m data and tensors shared by all search algorithms."""

    dem: np.ndarray
    obstacle_mask: np.ndarray
    road_segments: np.ndarray
    dem_tensor: torch.Tensor
    obstacle_tensor: torch.Tensor
    road_segments_tensor: torch.Tensor
    road_voronoi_tensor: torch.Tensor
    demand_points: np.ndarray
    demand_weights: np.ndarray | None
    demand_points_tensor: torch.Tensor
    demand_weights_tensor: torch.Tensor | None
    device: torch.device
    obstacle_soft_mask: np.ndarray | None = None
    obstacle_soft_tensor: torch.Tensor | None = None


def soft_obstacle_tensor(context: SiteProblemContext) -> torch.Tensor:
    """Soft-cost mask. Missing means the hard mask, which is the default policy."""

    if context.obstacle_soft_tensor is None:
        return context.obstacle_tensor
    return context.obstacle_soft_tensor
