"""Original soft evaluation, CPU hard footprints and exact haul queries."""

from __future__ import annotations

import numpy as np
import torch

from .context import building_hard_mask, soft_obstacle_tensor
from .haul_field import query_exact
from .pose import decode_raw_pose
from .site_model import default_site_model


class NumpySiteEvaluator:
    def __init__(self, problem, modeling, field, *, include_demand=False, pose_bounds=None):
        self.problem, self.modeling, self.field = problem, modeling, field
        self.pose_bounds = pose_bounds
        self.names = ("dem_soft", "demand_distance") if include_demand else ("dem_soft",)
        self.mask = building_hard_mask(problem)
        self.model = default_site_model()

    @torch.no_grad()
    def __call__(self, raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        problem, model = self.problem, self.modeling
        pose = decode_raw_pose(torch.as_tensor(raw, dtype=torch.float32, device=problem.device),
            problem.dem.shape, model.rect_w_m, model.rect_h_m, self.pose_bounds)
        values = self.model.evaluate_objectives(problem.dem_tensor, soft_obstacle_tensor(problem),
            problem.road_segments_tensor, problem.road_voronoi_tensor,
            problem.demand_points_tensor, problem.demand_weights_tensor, pose,
            model.rect_w_m, model.rect_h_m, model.soft_mask_sharpness)
        hard = self.model.hard_metrics(problem.dem, self.mask, pose, model.rect_w_m, model.rect_h_m, problem.device)
        decoded = pose.cpu().numpy().astype(np.float64)
        objectives = np.stack([values[name].cpu().numpy().astype(np.float64) for name in self.names], axis=1)
        haul, blocked = query_exact(self.field, decoded[:, :2])
        return np.concatenate((objectives, haul), axis=1), hard["constraint_violation"].cpu().numpy().astype(np.float64) + blocked
