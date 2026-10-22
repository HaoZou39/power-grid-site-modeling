"""Prepared, bounded-memory evaluation for device-resident site populations."""

from __future__ import annotations

import numpy as np
import torch

from .context import building_hard_mask, soft_obstacle_tensor
from .haul_field import haul_column_names, query_exact
from .pose import decode_raw_pose
from .site_model import default_site_model


class TensorHaulLookup:
    """Exact non-road grid lookup, retaining the continuous road-cell evaluator."""

    def __init__(self, field, device):
        self.field = field
        self.names = haul_column_names(field.origin is not None)
        self.values = torch.stack([torch.as_tensor(getattr(field, {"offroad_haul_m": "offroad_m", "haul_rise_m": "access_rise_m", "road_haul_m": "road_m"}[name]), device=device, dtype=torch.float64) for name in self.names], dim=-1)
        self.reachable = torch.as_tensor(field.reachable, device=device, dtype=torch.bool)
        self.road_cells = torch.as_tensor(field.road_cells, device=device, dtype=torch.bool)

    def __call__(self, sites: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        sites = sites.to(torch.float64)
        height, width = self.reachable.shape
        cols, rows = sites.floor().long().unbind(1)
        inside = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
        rows, cols = rows.clamp(0, height - 1), cols.clamp(0, width - 1)
        reachable = inside & self.reachable[rows, cols]
        values = self.values[rows, cols].clone()
        extra = torch.linalg.vector_norm(sites - torch.stack((cols + 0.5, rows + 0.5), dim=1), dim=1)
        offroad = self.names.index("offroad_haul_m")
        values[:, offroad] += torch.where(extra > 0.05, extra, 0)
        values = torch.where(reachable[:, None], values, 0)
        blocked = (~reachable).to(torch.float64)
        # Road cells need nearest continuous contact + network routing, not a
        # grid-center approximation. Only this subset leaves the device.
        road = torch.where(inside & self.road_cells[rows, cols])[0]
        if road.numel():
            exact, flags = query_exact(self.field, sites[road].cpu().numpy())
            values[road] = torch.as_tensor(exact, device=sites.device)
            blocked[road] = torch.as_tensor(flags, device=sites.device)
        return values, blocked


class TensorSiteEvaluator:
    def __init__(self, problem, modeling, field, *, include_demand=False, batch_size=256, pose_bounds=None):
        if batch_size < 1:
            raise ValueError("evaluation_batch_size must be positive")
        self.problem, self.modeling = problem, modeling
        self.batch_size, self.pose_bounds = int(batch_size), pose_bounds
        self.names = ("dem_soft", "demand_distance") if include_demand else ("dem_soft",)
        self.model = default_site_model()
        mask = building_hard_mask(problem)
        if mask.shape != problem.dem.shape or not np.isfinite(mask).all():
            raise ValueError("building mask must be finite and match the DEM shape")
        self.mask = torch.as_tensor(mask > 0, device=problem.device)
        self.haul = TensorHaulLookup(field, problem.device)

    @torch.no_grad()
    def __call__(self, raw: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        problem, model = self.problem, self.modeling
        objectives, violation = [], []
        for chunk in raw.split(self.batch_size):
            pose = decode_raw_pose(chunk.to(torch.float32), problem.dem.shape, model.rect_w_m, model.rect_h_m, self.pose_bounds)
            values = self.model.evaluate_objectives(problem.dem_tensor, soft_obstacle_tensor(problem),
                problem.road_segments_tensor, problem.road_voronoi_tensor,
                problem.demand_points_tensor, problem.demand_weights_tensor, pose,
                model.rect_w_m, model.rect_h_m, model.soft_mask_sharpness, self.names)
            cv = self.model.constraint.violation(self.mask, pose, model.rect_w_m, model.rect_h_m)
            haul, blocked = self.haul(pose[:, :2])
            objectives.append(torch.cat((torch.stack([values[name] for name in self.names], dim=1).to(torch.float64), haul), dim=1))
            violation.append(cv + blocked)
        return torch.cat(objectives), torch.cat(violation)
