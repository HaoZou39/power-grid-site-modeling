from __future__ import annotations

import numpy as np
import torch

from .demand_model import compute_demand_distance_loss
from .dem_model import compute_dem_hard_loss, compute_dem_soft_loss
from .masks import compute_hard_footprint_indices, compute_soft_footprint
from .obstacle_model import compute_obstacle_hard_loss, compute_obstacle_soft_loss
from .road_model import compute_road_distance_loss


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
    footprint = compute_soft_footprint(pose_batch, rect_w_m, rect_h_m, dem_tensor.shape[-2:], soft_mask_sharpness)
    return {
        "dem_soft": compute_dem_soft_loss(dem_tensor, footprint["grid"], footprint["weights"]),
        "obstacle_soft": compute_obstacle_soft_loss(obstacle_tensor, footprint["grid"], footprint["weights"]),
        "road_distance": compute_road_distance_loss(road_segments_tensor, road_voronoi_tensor, pose_batch),
        "demand_distance": compute_demand_distance_loss(demand_points_tensor, demand_weights_tensor, pose_batch),
    }


def compute_hard_constraints(
    dem: np.ndarray,
    obstacle_mask: np.ndarray,
    pose_batch: torch.Tensor,
    rect_w_m: float,
    rect_h_m: float,
    device: str = "cuda",
) -> dict[str, torch.Tensor]:
    hard_indices = compute_hard_footprint_indices(pose_batch, rect_w_m, rect_h_m, dem.shape)
    dem_metrics = compute_dem_hard_loss(dem, hard_indices, device=device)
    obstacle_metrics = compute_obstacle_hard_loss(obstacle_mask, hard_indices, device=device)
    is_feasible = obstacle_metrics["obstacle_hard_count"] == 0
    return {**dem_metrics, **obstacle_metrics, "is_feasible": is_feasible}
