"""One search ledger shared by initialization, operators and bounded phase calls."""

import time


class EvaluationBudget:
    def __init__(self, evaluator, total_limit, started, *, clock=time.perf_counter, phase_limits=None):
        self.evaluator, self.total_limit, self.started = evaluator, total_limit, started
        self.clock = clock
        self.records, self.times = [], []
        self.counts = {}
        self.evaluation_s = 0.
        self.stop_reason = "evaluation_budget"
        self.phase_limits = dict(phase_limits or {})
        if any(not isinstance(name, str) or type(limit) is not int or limit < 0
               for name, limit in self.phase_limits.items()):
            raise ValueError("phase limits require names and non-negative integer evaluation limits")

    def remaining_for(self, source):
        if source not in self.phase_limits:
            return self.remaining
        return min(self.remaining, max(0, self.phase_limits[source]-self.counts.get(source, 0)))

    @property
    def remaining(self):
        return max(0, self.total_limit - len(self.records))

    @property
    def history(self):
        """Read-only sequence view; entries retain their original evaluation identity."""
        return tuple(self.records)

    def window(self, source, limit):
        return EvaluationWindow(self, source, limit)

    def evaluate_many(self, routes, source):
        routes = routes[:self.remaining_for(source)]
        if not routes:
            return []
        started = self.clock()
        values = self.evaluator.evaluate_many(routes, details=False)
        self._commit(routes, values, source, started)
        return values

    def evaluate_tensors(self, batch, source):
        from modeling.routing.tensor_types import TowerBatch, TensorEvaluationBatch
        count = min(len(batch.xy), self.remaining_for(source))
        selected = TowerBatch(batch.xy[:count], batch.counts[:count])
        if not count:
            return TensorEvaluationBatch.from_records([], batch.xy.device)
        started = self.clock()
        native = getattr(self.evaluator, "evaluate_tensors", None)
        if native is not None:
            values = native(selected)
            routes, records = selected.routes(), values.records()
        else:
            routes = selected.routes()
            records = self.evaluator.evaluate_many(routes, details=False)
            values = TensorEvaluationBatch.from_records(records, batch.xy.device)
        self._commit(routes, records, source, started)
        return values

    def _commit(self, routes, values, source, started):
        self.evaluation_s += self.clock() - started
        if len(values) != len(routes):
            raise RuntimeError("routing evaluator returned the wrong batch size")
        self.records.extend(zip(routes, values))
        self.times.extend([self.clock() - self.started] * len(values))
        self.counts[source] = self.counts.get(source, 0) + len(values)



class EvaluationWindow:
    def __init__(self, budget, source, limit):
        if type(limit) is not int or limit < 0:
            raise ValueError("evaluation window limit must be a non-negative integer")
        self.budget, self.source, self.limit = budget, source, limit
        self.used = 0

    @property
    def remaining(self):
        return min(max(0, self.limit - self.used), self.budget.remaining_for(self.source))

    @property
    def history(self):
        return self.budget.history

    def evaluate_many(self, routes):
        values = self.budget.evaluate_many(routes[:max(0, self.limit - self.used)], self.source)
        self.used += len(values)
        return values

    def evaluate_tensors(self, batch):
        from modeling.routing.tensor_types import TowerBatch
        count = min(len(batch.xy), self.remaining)
        selected = TowerBatch(batch.xy[:count], batch.counts[:count])
        values = self.budget.evaluate_tensors(selected, self.source)
        self.used += len(values)
        return values

    def evaluate(self, route):
        values = self.evaluate_many([route])
        return values[0] if values else None
