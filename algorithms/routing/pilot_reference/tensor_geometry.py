"""PILOT metric hints and ordered path transforms on tensor batches."""

import numpy as np
import torch
from shapely.geometry import Point

from modeling.routing.compiled_geometry import project_clearance_points
from modeling.routing.context import tower_clearance
from modeling.routing.device_memory import require_workspace
from modeling.routing.geometry import DISTANCE_TOL_M
from modeling.routing.tensor_types import TowerBatch, connected_points


class PilotTensorGeometry:
    def __init__(self, geometry, config):
        self.geometry, self.config = geometry, config
        self.core = config.pilot.core
        self.problem = geometry.problem
        self.device = geometry.evaluator.device
        self.scale = self.problem.constraints.max_span_m / self.core.reference_max_step
        self._clearance = None

    def close(self):
        self._clearance = None

    @torch.no_grad()
    def clearance(self, points):
        if self._clearance is None:
            field = tower_clearance(self.problem)
            self._clearance = False
            if field is not None:
                require_workspace(self.device, field.nbytes, self.geometry.evaluator.config.gpu_memory_budget_mib)
                self._clearance = torch.tensor(field, device=self.device)
        radius = self.problem.constraints.tower_radius_m
        x, y = points.unbind(-1)
        margin = torch.stack((x, y, self.problem.frame.width - x, self.problem.frame.height - y), -1).amin(-1) - radius
        if self._clearance is not False:
            columns = x.floor().long().clamp(0, self.problem.frame.width - 1)
            rows = y.floor().long().clamp(0, self.problem.frame.height - 1)
            margin = margin.minimum(self._clearance[rows, columns].double() - radius)
        if self.problem.no_tower_zones:
            values = [min(Point(point).distance(zone) for zone in self.problem.no_tower_zones) - radius
                      for point in points.detach().cpu().numpy()]
            margin = margin.minimum(points.new_tensor(values))
        return margin.clamp_min(0)

    def radii(self, points):
        return (self.scale * self.core.radius_base + self.core.radius_clearance_factor * self.clearance(points)).clamp(
            self.scale * self.core.radius_min, self.scale * self.core.radius_max)

    def _clearance_arrays(self):
        if getattr(self, "_clearance_array_cache", None) is None:
            evaluator = self.geometry.evaluator
            self._clearance_array_cache = (
                np.ascontiguousarray(evaluator.blocked_distance.detach().cpu().numpy()),
                np.ascontiguousarray(evaluator.missing_distance.detach().cpu().numpy()),
                np.ascontiguousarray(np.asarray(self.problem.dem)),
                np.ascontiguousarray(np.asarray(self.problem.tower_blocked, dtype=bool)))
        return self._clearance_array_cache

    def _score_distance(self):
        if getattr(self, "_score_distance_values", None) is None:
            field = tower_clearance(self.problem)
            self._score_distance_values = np.zeros(1, np.float32) if field is None else np.ascontiguousarray(field)
        return self._score_distance_values

    @torch.no_grad()
    def project(self, points, radii, *, prefer_clearance=0.):
        if self.problem.no_tower_zones:
            return self._project_reference(points, radii, prefer_clearance=prefer_clearance)
        return self._project_table(points, radii, prefer_clearance=prefer_clearance)

    @torch.no_grad()
    def _project_table(self, points, radii, *, prefer_clearance=0.):
        result = points.clone()
        if not len(points):
            return result
        radii = torch.as_tensor(radii, device=points.device, dtype=points.dtype).expand(len(points))
        rings = (radii / self.scale).ceil().long().clamp_min(1)
        blocked_distance, missing_distance, dem, blocked = self._clearance_arrays()
        xs, ys = project_clearance_points(
            points[:, 0].detach().cpu().numpy(), points[:, 1].detach().cpu().numpy(), rings.detach().cpu().numpy(),
            blocked_distance, missing_distance, dem, blocked, self._score_distance(),
            float(self.scale), float(self.problem.constraints.tower_radius_m), float(prefer_clearance),
            float(self.problem.frame.width), float(self.problem.frame.height))
        result[:, 0] = torch.as_tensor(xs, device=points.device, dtype=points.dtype)
        result[:, 1] = torch.as_tensor(ys, device=points.device, dtype=points.dtype)
        return result

    @torch.no_grad()
    def _project_reference(self, points, radii, *, prefer_clearance=0.):
        require_workspace(points.device, points.numel() * 8,
                          self.geometry.evaluator.config.gpu_memory_budget_mib)
        result = points.clone()
        if not len(points):
            return result
        radii = torch.as_tensor(radii, device=points.device, dtype=points.dtype).expand(len(points))
        rings = (radii / self.scale).ceil().long().clamp_min(1)
        active = ~self.geometry.towers(points)
        chosen = active.nonzero().flatten()
        if not len(chosen):
            return result
        # One square per point. The winner is still the first ring that contains a legal cell,
        # then the same (score, squared distance, clearance) order as the ring walk.
        limit = int(rings[chosen].max())
        axis = torch.arange(-limit, limit + 1, device=points.device, dtype=points.dtype)
        dy, dx = torch.meshgrid(axis, axis, indexing="ij")
        offsets = torch.stack((dx.flatten(), dy.flatten()), -1)
        chebyshev = offsets.abs().amax(-1)
        distance2 = offsets.square().sum(-1)
        tile = max(1, self.geometry.workspace_bytes // len(offsets) // 128)
        rows = torch.arange(tile, device=points.device)
        for begin in range(0, len(chosen), tile):
            selected = chosen[begin:begin + tile]
            require_workspace(points.device, len(selected) * len(offsets) * 128,
                              self.geometry.evaluator.config.gpu_memory_budget_mib)
            candidates = points[selected, None] + self.scale * offsets
            allowed = self.geometry.towers(candidates.reshape(-1, 2)).reshape(candidates.shape[:2])
            allowed &= chebyshev <= rings[selected][:, None]
            clearance = self.clearance(candidates.reshape(-1, 2)).reshape(allowed.shape) / self.scale
            ring_id = torch.where(allowed, chebyshev, torch.inf)
            nearest = ring_id.amin(1)
            found = torch.isfinite(nearest)
            square = allowed & (chebyshev <= nearest[:, None])
            score = (1 - prefer_clearance) * distance2 - prefer_clearance * 2 * clearance
            best = square & (score == torch.where(square, score, torch.inf).amin(1)[:, None])
            best &= distance2 == torch.where(best, distance2, torch.inf).amin(1)[:, None]
            best &= clearance == torch.where(best, clearance, -torch.inf).amax(1)[:, None]
            positions = best.long().argmax(1)
            take = selected[found]
            result[take] = candidates[rows[:len(selected)][found], positions[found]]
        return result

    @torch.no_grad()
    def _compact_points(self, batch):
        require_workspace(batch.xy.device, batch.xy.numel() * 48,
                          self.geometry.evaluator.config.gpu_memory_budget_mib)
        safe = torch.where(batch.valid[..., None], batch.xy, 0)
        points = connected_points(safe, batch.counts, safe.new_tensor(self.problem.start.copy()),
                                  safe.new_tensor(self.problem.end.copy()))
        valid = torch.arange(points.shape[1], device=safe.device)[None, :] < batch.counts[:, None] + 2
        keep = torch.cat((torch.ones((len(batch), 1), device=safe.device, dtype=torch.bool),
                          torch.linalg.vector_norm(points[:, 1:] - points[:, :-1], dim=-1) > DISTANCE_TOL_M), 1) & valid
        # 端点固定：与终点重合时删掉前一座塔，而不是终点。
        rows = torch.arange(len(batch), device=safe.device)
        last = batch.counts + 1
        merged = ~keep[rows, last] & (last > 1)
        keep[rows, last] = True
        keep[rows[merged], last[merged] - 1] = False
        counts = keep.sum(1)
        columns = torch.arange(points.shape[1], device=safe.device).expand(len(batch), -1)
        order = torch.where(keep, columns, columns + points.shape[1]).argsort(dim=1, stable=True)
        packed = points.gather(1, order[..., None].expand(-1, -1, 2))
        return packed, counts

    @torch.no_grad()
    def deduplicate(self, batch):
        if not len(batch):
            return batch.clone()
        packed, counts = self._compact_points(batch)
        safe = batch.xy
        ends = packed[torch.arange(len(batch), device=safe.device), (counts - 1).clamp_min(0)]
        if bool((counts < 2).any()) or not bool((ends == safe.new_tensor(self.problem.end.copy())).all()):
            raise ValueError("PILOT path deduplication changed fixed endpoints")
        counts = counts - 2
        xy = packed[:, 1:batch.xy.shape[1] + 1]
        mask = torch.arange(xy.shape[1], device=safe.device)[None, :] < counts[:, None]
        return TowerBatch(torch.where(mask[..., None], xy, 0), counts)

    def sanitize(self, batch):
        require_workspace(batch.xy.device, batch.xy.numel() * 16,
                          self.geometry.evaluator.config.gpu_memory_budget_mib)
        result = batch.clone()
        result.xy[batch.valid] = self.project(batch.xy[batch.valid], self.core.sanitize_radius * self.scale)
        return self.deduplicate(result)

    @torch.no_grad()
    def resample(self, batch, counts):
        if counts.dtype != torch.int64 or counts.shape != batch.counts.shape or bool((counts < 0).any()):
            raise ValueError("resampling requires non-negative int64 target counts")
        if not len(batch):
            return TowerBatch(batch.xy[:, :0].clone(), counts.clone())
        safe = torch.where(batch.valid[..., None], batch.xy, 0)
        points = connected_points(safe, batch.counts, safe.new_tensor(self.problem.start.copy()),
                                  safe.new_tensor(self.problem.end.copy()))
        return self._resample_points(points, batch.counts + 2, counts)

    def _resample_points(self, points, sizes, counts):
        width = int(counts.max())
        require_workspace(points.device, len(points) * max(1, points.shape[1] + width) * 96,
                          self.geometry.evaluator.config.gpu_memory_budget_mib)
        lengths = torch.linalg.vector_norm(points[:, 1:] - points[:, :-1], dim=-1)
        spans = torch.arange(lengths.shape[1], device=points.device)[None, :] < sizes[:, None] - 1
        cumulative = torch.cat((lengths.new_zeros((len(points), 1)), torch.where(spans, lengths, 0).cumsum(1)), 1)
        locations = torch.arange(width + 2, device=points.device)[None, :] * (cumulative[:, -1] / (counts + 1))[:, None]
        right = torch.searchsorted(cumulative.contiguous(), locations.contiguous(), right=True).clamp_min(1)
        right = right.minimum((sizes[:, None] - 1).clamp_min(1))
        left = right - 1
        a = points.gather(1, left[..., None].expand(-1, -1, 2))
        b = points.gather(1, right[..., None].expand(-1, -1, 2))
        lower, upper = cumulative.gather(1, left), cumulative.gather(1, right)
        ratio = (locations - lower) / (upper - lower).clamp_min(torch.finfo(points.dtype).tiny)
        samples = a + ratio[..., None] * (b - a)
        samples = torch.where((cumulative[:, -1] <= DISTANCE_TOL_M)[:, None, None], points[:, :1], samples)
        xy = samples[:, 1:width + 1]
        valid = torch.arange(width, device=points.device)[None, :] < counts[:, None]
        return TowerBatch(torch.where(valid[..., None], xy, 0), counts.clone())

    @torch.no_grad()
    def resample_duplicates(self, batch, counts):
        """CPU sampling may drop the temporary endpoint before restoring it."""
        points, sizes = self._compact_points(batch)
        indices = (sizes != counts + 2).nonzero().flatten()
        if not len(indices):
            return batch
        second = self._resample_points(points[indices], sizes[indices], counts[indices])
        second.xy[second.valid] = self.project(second.xy[second.valid], self.core.resample_radius * self.scale)
        result = batch.padded(max(batch.xy.shape[1], second.xy.shape[1]))
        result.xy[indices] = second.padded(result.xy.shape[1]).xy
        result.counts[indices] = second.counts
        return result
