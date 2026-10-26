"""Batched exact tensor evaluation; polygon and critical-boundary checks stay CPU."""

import math

import numpy as np
import torch

from .tensor_types import TowerBatch, connected_points
from .compiled_evaluator import CompiledRouteEvaluator, VIOLATION_NAMES, total_violation
from .evaluator import RouteEvaluator
from .geometry import DISTANCE_TOL_M
from .device_memory import require_workspace
from .tensor_geometry import crossing_lengths, sample_dem, tower_flags
from .types import RouteEvaluation


class TensorRouteEvaluator(CompiledRouteEvaluator):
    def __init__(self, problem, config):
        super().__init__(problem)
        self.config = config
        self.device = torch.device(config.devices[0])
        self.boundary_rechecks = 0
        budget = config.gpu_memory_budget_mib * 1024**2
        self.workspace_bytes = min(64 * 1024**2, budget // 16)
        estimated = problem.dem.nbytes + problem.tower_blocked.nbytes + problem.crossing_mask.nbytes
        if self.device.type == "cuda":
            if not torch.cuda.is_available():
                raise ValueError("routing explicitly requested CUDA but CUDA is unavailable")
            free, _ = torch.cuda.mem_get_info(self.device)
            allocated = torch.cuda.memory_allocated(self.device)
            if estimated + 4 * self.workspace_bytes > min(budget - allocated, free):
                raise MemoryError("routing scene and workspace exceed configured GPU memory budget")
        self.dem = torch.tensor(np.array(problem.dem), device=self.device)
        self.blocked = torch.tensor(np.array(problem.tower_blocked), device=self.device)
        self.crossing = torch.tensor(np.array(problem.crossing_mask), device=self.device)

    def close(self):
        self.dem = self.blocked = self.crossing = None
        if self.device.type == "cuda":
            with torch.cuda.device(self.device):
                torch.cuda.empty_cache()

    @torch.no_grad()
    def numeric(self, batch):
        p, c = self.problem, self.problem.constraints
        xy, counts = batch.xy, batch.counts
        require_workspace(xy.device, 4 * self.workspace_bytes + xy.numel() * 64, self.config.gpu_memory_budget_mib)
        rows = torch.arange(len(xy), device=xy.device)
        k = xy.shape[1]
        tower_valid = torch.arange(k, device=xy.device)[None, :] < counts[:, None]
        xy = torch.where(tower_valid[..., None], xy, 0)
        points = connected_points(xy, counts, xy.new_tensor(p.start.copy()), xy.new_tensor(p.end.copy()))
        point_valid = torch.arange(k + 2, device=xy.device)[None, :] < counts[:, None] + 2
        elevations = sample_dem(self.dem, points)
        spans_valid = torch.arange(k + 1, device=xy.device)[None, :] < counts[:, None] + 1
        delta = points[:, 1:] - points[:, :-1]
        horizontal = torch.linalg.vector_norm(delta, dim=2)
        spatial = torch.hypot(horizontal, elevations[:, 1:] - elevations[:, :-1])
        unit = delta / horizontal.clamp_min(torch.finfo(torch.float64).tiny)[..., None]
        cross = unit[:, :-1, 0] * unit[:, 1:, 1] - unit[:, :-1, 1] * unit[:, 1:, 0]
        dot = (unit[:, :-1] * unit[:, 1:]).sum(-1)
        turns = torch.atan2(cross.abs(), dot)
        values = xy.new_zeros((len(xy), 8))
        values[:, 0] = ((horizontal == 0) & spans_valid).sum(1)
        values[:, 3] = (~torch.isfinite(elevations[rows, 0])).long() + (~torch.isfinite(elevations[rows, counts + 1])).long()
        near = torch.zeros(len(xy), device=xy.device, dtype=torch.bool)
        outside, hit, missing, critical = tower_flags(self.dem, self.blocked, xy[tower_valid], c.tower_radius_m, self.workspace_bytes)
        for column, flags in ((1, outside), (2, hit), (3, missing)):
            work = xy.new_zeros((len(xy), k)); work[tower_valid] = flags.double()
            values[:, column] += work.sum(1)
        work = torch.zeros_like(tower_valid); work[tower_valid] = critical
        near |= work.any(1)
        pair_step = max(1, self.workspace_bytes // max(1, len(xy) * max(1, k)) // 64)
        for begin in range(0, k, pair_step):
            dist = torch.linalg.vector_norm(xy[:, :, None] - xy[:, None, begin:begin + pair_step], dim=-1)
            cols = torch.arange(begin, min(begin + pair_step, k), device=xy.device)
            valid = tower_valid[:, :, None] & (cols[None, None, :] < counts[:, None, None])
            valid &= torch.arange(k, device=xy.device)[None, :, None] < cols[None, None, :]
            overlap = 2 * c.tower_radius_m - dist
            values[:, 4] += torch.where(valid & (overlap > DISTANCE_TOL_M), overlap, 0).sum((1, 2))
            near |= (valid & ((overlap - DISTANCE_TOL_M).abs() <= 128 * torch.finfo(xy.dtype).eps * dist.clamp_min(1))).any((1, 2))
        excess = horizontal - c.max_span_m
        values[:, 5] = torch.where(spans_valid & (excess > DISTANCE_TOL_M), excess, 0).sum(1)
        excess_turn = turns - math.radians(c.max_turn_deg)
        values[:, 6] = torch.where(tower_valid & (excess_turn > 1e-12), excess_turn, 0).sum(1)
        near |= (spans_valid & ((excess - DISTANCE_TOL_M).abs() <= 128 * torch.finfo(xy.dtype).eps * horizontal.clamp_min(c.max_span_m))).any(1)
        near |= (tower_valid & ((excess_turn - 1e-12).abs() <= 128 * torch.finfo(xy.dtype).eps)).any(1)
        within = point_valid & (points >= 0).all(-1) & (points[..., 0] <= p.frame.width) & (points[..., 1] <= p.frame.height)
        traversal = spans_valid & (horizontal > 0) & within[:, :-1] & within[:, 1:]
        crossings = xy.new_zeros(horizontal.shape)
        planar = crossing_lengths(points[:, :-1][traversal], points[:, 1:][traversal], self.crossing, self.workspace_bytes)
        crossings[traversal] = spatial[traversal] * planar / horizontal[traversal]
        objectives = torch.stack((counts.double(), torch.where(spans_valid, spatial, 0).sum(1),
            torch.where(tower_valid, turns, 0).sum(1), torch.where(spans_valid, crossings, 0).sum(1)), 1)
        objectives = torch.where(torch.isfinite(objectives), objectives, torch.inf)
        spans = torch.stack((horizontal, spatial, crossings), -1)
        return objectives, values, elevations, spans, near

    def evaluate_many(self, routes, *, details=True):
        results = []
        for begin in range(0, len(routes), self.config.evaluation_batch_size):
            selected = routes[begin:begin + self.config.evaluation_batch_size]
            batch = TowerBatch.from_routes(selected, self.device)
            outputs = [a.cpu().numpy() for a in self.numeric(batch)]
            objectives, values, elevations, spans, near = outputs
            for i, route in enumerate(selected):
                # Shared closed-cell/threshold semantics win over device round-off.
                if near[i] or self.problem.no_tower_zones or self.problem.no_cross_zones:
                    self.boundary_rechecks += 1
                    value = RouteEvaluator(self.problem).evaluate(route)
                    results.append(value if details else value.compact())
                else:
                    n = len(route.towers)
                    results.append(RouteEvaluation(objectives[i], dict(zip(VIOLATION_NAMES, values[i])),
                        total_violation(values[i], self.problem.constraints.tower_radius_m, self.problem.constraints.max_span_m),
                        elevations[i, :n + 2] if details else np.empty(0),
                        [dict(zip(("horizontal_m", "length_3d_m", "crossing_3d_m"), row)) for row in spans[i, :n + 1]] if details else [], []))
        return results
