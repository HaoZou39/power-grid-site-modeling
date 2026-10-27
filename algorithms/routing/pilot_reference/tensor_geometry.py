"""PILOT metric hints and ordered path transforms on tensor batches."""

import numpy as np
import torch
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Point

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
            blocked = self.problem.tower_blocked | ~np.isfinite(self.problem.dem)
            self._clearance = False
            if blocked.any():
                require_workspace(self.device, blocked.size * 4,
                                  self.geometry.evaluator.config.gpu_memory_budget_mib)
                field = distance_transform_edt(~blocked).astype(np.float32)
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

    @torch.no_grad()
    def project(self, points, radii, *, prefer_clearance=0.):
        result = points.clone()
        if not len(points):
            return result
        radii = torch.as_tensor(radii, device=points.device, dtype=points.dtype).expand(len(points))
        rings = (radii / self.scale).ceil().long().clamp_min(1)
        active = ~self.geometry.towers(points)
        for ring in range(1, int(rings.max()) + 1):
            indices = (active & (rings >= ring)).nonzero().flatten()
            if not len(indices):
                break
            axis = torch.arange(-ring, ring + 1, device=points.device, dtype=points.dtype)
            dy, dx = torch.meshgrid(axis, axis, indexing="ij")
            offsets = torch.stack((dx.flatten(), dy.flatten()), -1)
            distance2 = offsets.square().sum(-1)
            tile = max(1, self.geometry.workspace_bytes // len(offsets) // 128)
            for begin in range(0, len(indices), tile):
                selected = indices[begin:begin + tile]
                require_workspace(points.device, len(selected) * len(offsets) * 128,
                                  self.geometry.evaluator.config.gpu_memory_budget_mib)
                candidates = points[selected, None] + self.scale * offsets
                allowed = self.geometry.towers(candidates.reshape(-1, 2)).reshape(candidates.shape[:2])
                clearance = self.clearance(candidates.reshape(-1, 2)).reshape(allowed.shape) / self.scale
                score = (1 - prefer_clearance) * distance2 - prefer_clearance * 2 * clearance
                best = allowed & (score == score.masked_fill(~allowed, torch.inf).amin(1)[:, None])
                best &= distance2 == torch.where(best, distance2, torch.inf).amin(1)[:, None]
                best &= clearance == clearance.masked_fill(~best, -torch.inf).amax(1)[:, None]
                positions = best.long().argmax(1)
                found = allowed.any(1)
                result[selected[found]] = candidates[torch.arange(len(selected), device=points.device), positions][found]
                active[selected[found]] = False
        return result

    @torch.no_grad()
    def deduplicate(self, batch):
        if not len(batch):
            return batch.clone()
        safe = torch.where(batch.valid[..., None], batch.xy, 0)
        points = connected_points(safe, batch.counts, safe.new_tensor(self.problem.start.copy()),
                                  safe.new_tensor(self.problem.end.copy()))
        valid = torch.arange(points.shape[1], device=safe.device)[None, :] < batch.counts[:, None] + 2
        keep = torch.cat((torch.ones((len(batch), 1), device=safe.device, dtype=torch.bool),
                          torch.linalg.vector_norm(points[:, 1:] - points[:, :-1], dim=-1) > DISTANCE_TOL_M), 1) & valid
        counts = keep.sum(1)
        columns = torch.arange(points.shape[1], device=safe.device).expand(len(batch), -1)
        order = torch.where(keep, columns, columns + points.shape[1]).argsort(dim=1, stable=True)
        packed = points.gather(1, order[..., None].expand(-1, -1, 2))
        ends = packed[torch.arange(len(batch), device=safe.device), (counts - 1).clamp_min(0)]
        if bool((counts < 2).any()) or not bool((ends == safe.new_tensor(self.problem.end.copy())).all()):
            raise ValueError("PILOT path deduplication changed fixed endpoints")
        counts = counts - 2
        xy = packed[:, 1:batch.xy.shape[1] + 1]
        mask = torch.arange(xy.shape[1], device=safe.device)[None, :] < counts[:, None]
        return TowerBatch(torch.where(mask[..., None], xy, 0), counts)

    def sanitize(self, batch):
        result = batch.clone()
        result.xy[batch.valid] = self.project(batch.xy[batch.valid], self.core.sanitize_radius * self.scale)
        return self.deduplicate(result)

    @torch.no_grad()
    def resample(self, batch, counts):
        if counts.dtype != torch.int64 or counts.shape != batch.counts.shape or bool((counts < 0).any()):
            raise ValueError("resampling requires non-negative int64 target counts")
        if not len(batch):
            return TowerBatch(batch.xy[:, :0].clone(), counts.clone())
        width = int(counts.max())
        require_workspace(batch.xy.device, len(batch) * max(1, batch.xy.shape[1] + width) * 96,
                          self.geometry.evaluator.config.gpu_memory_budget_mib)
        safe = torch.where(batch.valid[..., None], batch.xy, 0)
        points = connected_points(safe, batch.counts, safe.new_tensor(self.problem.start.copy()),
                                  safe.new_tensor(self.problem.end.copy()))
        lengths = torch.linalg.vector_norm(points[:, 1:] - points[:, :-1], dim=-1)
        spans = torch.arange(lengths.shape[1], device=safe.device)[None, :] <= batch.counts[:, None]
        cumulative = torch.cat((lengths.new_zeros((len(batch), 1)), torch.where(spans, lengths, 0).cumsum(1)), 1)
        locations = torch.arange(width + 2, device=safe.device)[None, :] * (cumulative[:, -1] / (counts + 1))[:, None]
        right = torch.searchsorted(cumulative.contiguous(), locations.contiguous(), right=True).clamp_min(1)
        right = right.minimum(batch.counts[:, None] + 1)
        left = right - 1
        a = points.gather(1, left[..., None].expand(-1, -1, 2))
        b = points.gather(1, right[..., None].expand(-1, -1, 2))
        lower, upper = cumulative.gather(1, left), cumulative.gather(1, right)
        ratio = (locations - lower) / (upper - lower).clamp_min(torch.finfo(safe.dtype).tiny)
        samples = a + ratio[..., None] * (b - a)
        xy = samples[:, 1:width + 1]
        valid = torch.arange(width, device=safe.device)[None, :] < counts[:, None]
        return TowerBatch(torch.where(valid[..., None], xy, 0), counts.clone())
