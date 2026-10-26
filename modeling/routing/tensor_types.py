"""Packed tower coordinates shared by modeling and evolution."""

from dataclasses import dataclass

import numpy as np
import torch

from .types import Route


@dataclass
class TowerBatch:
    xy: torch.Tensor
    counts: torch.Tensor

    @classmethod
    def from_routes(cls, routes, device, capacity=None):
        capacity = max((len(r.towers) for r in routes), default=0) if capacity is None else capacity
        xy = torch.zeros((len(routes), capacity, 2), dtype=torch.float64, device=device)
        counts = torch.tensor([len(r.towers) for r in routes], device=device)
        for i, route in enumerate(routes):
            xy[i, :len(route.towers)] = torch.as_tensor(np.array(route.towers), device=device)
        return cls(xy, counts)

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
