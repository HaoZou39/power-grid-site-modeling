"""Packed tower coordinates shared by modeling and evolution."""

from dataclasses import dataclass

import numpy as np
import torch

from .types import Route


@dataclass
class TowerBatch:
    xy: torch.Tensor
    counts: torch.Tensor

    def __len__(self):
        return len(self.xy)

    @property
    def valid(self):
        return torch.arange(self.xy.shape[1], device=self.xy.device)[None, :] < self.counts[:, None]

    def clone(self):
        return TowerBatch(self.xy.clone(), self.counts.clone())

    def padded(self, width):
        if width < self.xy.shape[1]:
            raise ValueError("cannot shrink chromosome capacity")
        return TowerBatch(torch.nn.functional.pad(self.xy, (0, 0, 0, width - self.xy.shape[1])),
                          self.counts.clone())

    def where(self, selected, other):
        width = max(self.xy.shape[1], other.xy.shape[1])
        first, second = self.padded(width), other.padded(width)
        return TowerBatch(torch.where(selected[:, None, None], first.xy, second.xy),
                          torch.where(selected, first.counts, second.counts))

    @classmethod
    def concatenate(cls, batches):
        width = max(batch.xy.shape[1] for batch in batches)
        padded = [batch.padded(width) for batch in batches]
        return cls(torch.cat([batch.xy for batch in padded]), torch.cat([batch.counts for batch in padded]))

    @classmethod
    def from_routes(cls, routes, device, capacity=None):
        capacity = max((len(r.towers) for r in routes), default=0) if capacity is None else capacity
        packed = np.zeros((len(routes), capacity, 2), dtype=np.float64)
        counts = np.array([len(r.towers) for r in routes], dtype=np.int64)
        if counts.size and counts.max() > capacity:
            raise ValueError("tower batch capacity is smaller than route count")
        for i, route in enumerate(routes):
            packed[i, :len(route.towers)] = route.towers
        return cls(torch.tensor(packed, device=device), torch.tensor(counts, device=device))

    def routes(self):
        xy, counts = self.xy.detach().cpu().numpy(), self.counts.cpu().numpy()
        return [Route(row[:n]) for row, n in zip(xy, counts)]

    def take(self, indices):
        return TowerBatch(self.xy[indices], self.counts[indices])

    def capacity(self, width):
        if width < self.xy.shape[1]:
            raise ValueError("cannot shrink chromosome capacity")
        self.xy = torch.nn.functional.pad(self.xy, (0, 0, 0, width - self.xy.shape[1]))


def connected_points(xy, counts, start, end):
    start, end = start.to(xy), end.to(xy)
    points = torch.cat((start.expand(len(xy), 1, 2), xy, end.expand(len(xy), 1, 2)), dim=1)
    points[torch.arange(len(xy), device=xy.device), counts + 1] = end
    return points


@dataclass
class TensorEvaluationBatch:
    objectives: torch.Tensor
    violations: torch.Tensor
    violation: torch.Tensor

    def __len__(self):
        return len(self.objectives)

    def take(self, indices):
        return TensorEvaluationBatch(self.objectives[indices], self.violations[indices], self.violation[indices])

    def where(self, selected, other):
        return TensorEvaluationBatch(torch.where(selected[:, None], self.objectives, other.objectives),
                                     torch.where(selected[:, None], self.violations, other.violations),
                                     torch.where(selected, self.violation, other.violation))

    @classmethod
    def concatenate(cls, batches):
        return cls(*(torch.cat([getattr(batch, name) for batch in batches])
                     for name in ("objectives", "violations", "violation")))

    @classmethod
    def from_records(cls, records, device):
        from .compiled_evaluator import VIOLATION_NAMES
        objectives = np.array([item.objectives for item in records], dtype=np.float64).reshape(-1, 4)
        violations = np.array([[item.violations[name] for name in VIOLATION_NAMES] for item in records],
                              dtype=np.float64).reshape(-1, len(VIOLATION_NAMES))
        return cls(torch.tensor(objectives, device=device), torch.tensor(violations, device=device),
                   torch.tensor([item.violation for item in records], device=device, dtype=torch.float64))

    def records(self):
        from .compiled_evaluator import VIOLATION_NAMES
        from .types import RouteEvaluation
        objectives = self.objectives.detach().cpu().numpy()
        violations = self.violations.detach().cpu().numpy()
        violation = self.violation.detach().cpu().numpy()
        return [RouteEvaluation(f, dict(zip(VIOLATION_NAMES, v)), float(cv), np.empty(0), [], [])
                for f, v, cv in zip(objectives, violations, violation)]
