"""Batch geometry predicates, separate from budgeted objective evaluation."""

import math

import torch

from .device_memory import require_workspace
from .evaluator import RouteEvaluator
from .geometry import DISTANCE_TOL_M
from .tensor_geometry import clearance_miss, crossing_lengths, tower_flags
from .tensor_types import TowerBatch, connected_points


class TensorRouteGeometry:
    def __init__(self, evaluator, workspace_bytes=None):
        self.evaluator = evaluator
        self.problem = evaluator.problem
        self.reference = RouteEvaluator(self.problem)
        self.workspace_bytes = evaluator.workspace_bytes if workspace_bytes is None else workspace_bytes
        if self.workspace_bytes < 1:
            raise ValueError("geometry workspace must be positive")
        self.tower_queries = self.span_queries = self.path_queries = self.cpu_rechecks = 0

    def _check_points(self, points):
        if (points.ndim != 2 or points.shape[1] != 2 or points.dtype != torch.float64
                or points.device != self.evaluator.device):
            raise ValueError("geometry query requires float64 points [N,2] on its device")

    def _exact(self, result, selected, check, *points):
        indices = selected.nonzero().flatten()
        if len(indices):
            arrays = [item[indices].detach().cpu().numpy() for item in points]
            values = [check(*args) for args in zip(*arrays)]
            result[indices] = torch.tensor(values, device=result.device, dtype=torch.bool)
            self.cpu_rechecks += len(indices)
        return result

    @torch.no_grad()
    def towers(self, points):
        self._check_points(points)
        require_workspace(points.device, len(points) * 4, self.evaluator.config.gpu_memory_budget_mib)
        self.tower_queries += len(points)
        radius = self.problem.constraints.tower_radius_m
        tile = max(1, self.workspace_bytes // 256)
        result = torch.zeros(len(points), device=points.device, dtype=torch.bool)
        for begin in range(0, len(points), tile):
            xy = points[begin:begin + tile]
            finite = torch.isfinite(xy).all(-1)
            safe = torch.where(finite[:, None], xy, 0)
            outside, hit, missing, near = tower_flags(
                self.evaluator.dem, self.evaluator.blocked, safe, radius, self.workspace_bytes,
                self.evaluator.blocked_distance, self.evaluator.missing_distance)
            allowed = finite & ~(outside | hit | missing)
            if self.problem.no_tower_zones:
                missed = clearance_miss(self.evaluator.tower_zone_distance, safe, radius + DISTANCE_TOL_M)
                near = near | ~missed
            allowed = self._exact(allowed, near & finite, self.reference.tower_allowed, safe)
            result[begin:begin + len(xy)] = allowed
        return result

    @torch.no_grad()
    def spans(self, starts, ends):
        self._check_points(starts)
        self._check_points(ends)
        if starts.shape != ends.shape:
            raise ValueError("span query requires matching endpoints [N,2]")
        self.span_queries += len(starts)
        require_workspace(starts.device, len(starts) * 4, self.evaluator.config.gpu_memory_budget_mib)
        result = torch.zeros(len(starts), device=starts.device, dtype=torch.bool)
        tile = max(1, self.workspace_bytes // 128)
        for begin in range(0, len(starts), tile):
            result[begin:begin + tile] = self._spans(starts[begin:begin + tile], ends[begin:begin + tile])
        return result

    def _spans(self, starts, ends):
        limit = starts.new_tensor([self.problem.frame.width, self.problem.frame.height])
        finite = torch.isfinite(starts).all(-1) & torch.isfinite(ends).all(-1)
        within = (starts >= 0).all(-1) & (ends >= 0).all(-1)
        within &= (starts <= limit).all(-1) & (ends <= limit).all(-1)
        length = torch.linalg.vector_norm(ends - starts, dim=-1)
        maximum = self.problem.constraints.max_span_m
        result = finite & within & (length > 0) & (length <= maximum + DISTANCE_TOL_M)
        near = (length - maximum - DISTANCE_TOL_M).abs() <= 128 * torch.finfo(starts.dtype).eps * length.clamp_min(maximum)
        if self.problem.no_cross_zones:
            near = near | (crossing_lengths(starts, ends, self.evaluator.nocross_mask, self.workspace_bytes) > 0)
        return self._exact(result, near & finite, self.reference.span_allowed, starts, ends)

    def _reference_path(self, route):
        points = route.points(self.problem.start, self.problem.end)
        return all(self.reference.extension_allowed(points[:i], points[i], fixed_endpoint=i == len(points) - 1)
                   for i in range(1, len(points)))

    @torch.no_grad()
    def paths(self, batch):
        self.path_queries += len(batch.xy)
        require_workspace(batch.xy.device, len(batch.xy) * 4, self.evaluator.config.gpu_memory_budget_mib)
        result = torch.zeros(len(batch.xy), device=batch.xy.device, dtype=torch.bool)
        tile = max(1, self.workspace_bytes // max(1, batch.xy.shape[1]) // 128)
        for begin in range(0, len(batch.xy), tile):
            piece = TowerBatch(batch.xy[begin:begin + tile], batch.counts[begin:begin + tile])
            result[begin:begin + tile] = self._paths(piece)
        return result

    def _paths(self, batch):
        xy, counts = batch.xy, batch.counts
        size, width = xy.shape[:2]
        valid = torch.arange(width, device=xy.device)[None, :] < counts[:, None]
        safe = torch.where(valid[..., None], xy, 0)
        towers = torch.ones_like(valid)
        towers[valid] = self.towers(safe[valid])
        result = towers.all(1)
        points = connected_points(safe, counts, xy.new_tensor(self.problem.start.copy()),
                                  xy.new_tensor(self.problem.end.copy()))
        span_valid = torch.arange(width + 1, device=xy.device)[None, :] <= counts[:, None]
        spans = torch.ones_like(span_valid)
        spans[span_valid] = self.spans(points[:, :-1][span_valid], points[:, 1:][span_valid])
        result &= spans.all(1)
        delta = points[:, 1:] - points[:, :-1]
        unit = delta / torch.linalg.vector_norm(delta, dim=-1).clamp_min(torch.finfo(xy.dtype).tiny)[..., None]
        cross = unit[:, :-1, 0] * unit[:, 1:, 1] - unit[:, :-1, 1] * unit[:, 1:, 0]
        turns = torch.atan2(cross.abs(), (unit[:, :-1] * unit[:, 1:]).sum(-1))
        excess = turns - math.radians(self.problem.constraints.max_turn_deg)
        result &= ~(valid & (excess > 1e-12)).any(1)
        near = (valid & ((excess - 1e-12).abs() <= 128 * torch.finfo(xy.dtype).eps)).any(1)
        step = max(1, self.workspace_bytes // max(1, size * max(1, width)) // 64)
        for begin in range(0, width, step):
            require_workspace(xy.device, size * width * min(step, width - begin) * 64,
                              self.evaluator.config.gpu_memory_budget_mib)
            distance = torch.linalg.vector_norm(safe[:, :, None] - safe[:, None, begin:begin + step], dim=-1)
            columns = torch.arange(begin, min(begin + step, width), device=xy.device)
            pairs = valid[:, :, None] & (columns[None, None, :] < counts[:, None, None])
            pairs &= torch.arange(width, device=xy.device)[None, :, None] < columns[None, None, :]
            overlap = 2 * self.problem.constraints.tower_radius_m - distance
            result &= ~(pairs & (overlap > DISTANCE_TOL_M)).any((1, 2))
            near |= (pairs & ((overlap - DISTANCE_TOL_M).abs()
                              <= 128 * torch.finfo(xy.dtype).eps * distance.clamp_min(1))).any((1, 2))
        indices = near.nonzero().flatten()
        if len(indices):
            exact = [self._reference_path(route) for route in batch.take(indices).routes()]
            result[indices] = torch.tensor(exact, device=xy.device, dtype=torch.bool)
            self.cpu_rechecks += len(indices)
        return result
