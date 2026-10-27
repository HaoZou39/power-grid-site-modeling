"""A device run with ordered, budgeted batch scoring and a compact CPU archive."""

import torch

from modeling.routing.tensor_types import TowerBatch, TensorEvaluationBatch, connected_points
from .tensor_population import TensorPopulation, better


class TensorRunState:
    def __init__(self, host, geometry, generator):
        self.host, self.geometry, self.generator = host, geometry, generator
        self.config, self.core, self.budget = host.config, host.core, host.budget
        self.device, self.problem, self.scale = geometry.device, host.problem, host.scale
        self.diagnostics = host.diagnostics
        self._remembered = len(self.budget.records)

    def count(self, name, amount=1):
        self.host.count(name, int(amount))

    def checkpoint(self):
        self.host.checkpoint("正在执行 PILOT 张量批处理")

    def points(self, routes):
        return connected_points(routes.xy, routes.counts, routes.xy.new_tensor(self.problem.start.copy()),
                                routes.xy.new_tensor(self.problem.end.copy()))

    def pending(self, routes):
        xy = routes.xy
        return TensorPopulation(routes, TensorEvaluationBatch(xy.new_full((len(routes), 4), torch.inf),
            xy.new_full((len(routes), 8), torch.inf), xy.new_full((len(routes),), torch.inf)),
            torch.full((len(routes),), -1, device=xy.device, dtype=torch.long))

    def remember(self, origin):
        from .runtime import Candidate
        for index in range(self._remembered, len(self.budget.records)):
            route, checked = self.budget.records[index]
            candidate = Candidate(route, checked, index)
            self.host.candidates[candidate.key] = candidate
            self.host.origins[candidate.key] = origin
        self._remembered = len(self.budget.records)

    def score(self, routes, window, *, allowed=None, origin=None):
        self.checkpoint()
        result = self.pending(routes)
        if allowed is None:
            allowed = torch.ones(len(routes), device=self.device, dtype=torch.bool)
        indices = allowed.nonzero().flatten()[:window.remaining]
        if not len(indices):
            return result
        start = len(self.budget.records)
        values = window.evaluate_tensors(routes.take(indices))
        for name in ("objectives", "violations", "violation"):
            getattr(result.values, name)[indices] = getattr(values, name)
        result.ids[indices] = torch.arange(start, start + len(indices), device=self.device)
        self.remember(origin or window.source)
        return result

    def reuse(self, routes, since):
        # One transfer per logical batch, using the already-required CPU archive.
        # No device history of every trial is retained.
        result = self.pending(routes)
        indices, records, ids = [], [], []
        for index, route in enumerate(routes.routes()):
            candidate = self.host.candidates.get(route.towers.tobytes())
            if candidate is not None and candidate.evaluation_index >= since:
                indices.append(index)
                records.append(candidate.evaluation)
                ids.append(candidate.evaluation_index)
        if indices:
            indices = torch.tensor(indices, device=self.device)
            values = TensorEvaluationBatch.from_records(records, self.device)
            for name in ("objectives", "violations", "violation"):
                getattr(result.values, name)[indices] = getattr(values, name)
            result.ids[indices] = torch.tensor(ids, device=self.device)
        return result

    def better(self, first, second, **kwargs):
        return better(first, second, self.core, **kwargs)

    def from_candidates(self, candidates):
        return TensorPopulation(TowerBatch.from_routes([c.route for c in candidates], self.device),
            TensorEvaluationBatch.from_records([c.evaluation for c in candidates], self.device),
            torch.tensor([c.evaluation_index for c in candidates], device=self.device))

