"""One search ledger shared by initialization, operators and bounded phase calls."""

from collections import OrderedDict
import time


class EvaluationBudget:
    def __init__(self, evaluator, total_limit, started, *, clock=time.perf_counter, phase_limits=None):
        self.evaluator, self.total_limit, self.started = evaluator, total_limit, started
        self.clock = clock
        self.records, self.times = [], []
        self.counts = {}
        self._evaluation_cache = OrderedDict()
        self._evaluation_cache_capacity = max(1, min(total_limit, 8192))
        self.cache_hits = 0
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
        unique_routes, unique_keys, slots = [], [], []
        unique_indices = {}
        for position, route in enumerate(routes):
            towers = getattr(route, "towers", None)
            key = None if towers is None else towers.tobytes()
            index = unique_indices.get(key) if key is not None else None
            if index is None:
                index = len(unique_routes)
                if key is not None:
                    unique_indices[key] = index
                unique_routes.append(route)
                unique_keys.append(key)
                slots.append([])
            else:
                self.cache_hits += 1
            slots[index].append(position)
        resolved = [None] * len(unique_routes)
        missing, missing_indices = [], []
        for index, (route, key) in enumerate(zip(unique_routes, unique_keys)):
            if key is not None and key in self._evaluation_cache:
                resolved[index] = self._evaluation_cache[key]
                self._evaluation_cache.move_to_end(key)
                self.cache_hits += 1
            else:
                missing.append(route)
                missing_indices.append(index)
        if missing:
            fresh = self.evaluator.evaluate_many(missing, details=False)
            for index, route, value in zip(missing_indices, missing, fresh):
                resolved[index] = value
                key = unique_keys[index]
                if key is not None:
                    self._evaluation_cache[key] = value
                    if len(self._evaluation_cache) > self._evaluation_cache_capacity:
                        self._evaluation_cache.popitem(last=False)
        values = [None] * len(routes)
        for index, positions in enumerate(slots):
            for position in positions:
                values[position] = resolved[index]
        self._commit(routes, values, source, started)
        return values

    def evaluate_tensors(self, batch, source):
        from modeling.routing.tensor_types import TowerBatch, TensorEvaluationBatch
        import torch
        count = min(len(batch.xy), self.remaining_for(source))
        selected = TowerBatch(batch.xy[:count], batch.counts[:count])
        if not count:
            return TensorEvaluationBatch.from_records([], batch.xy.device)
        started = self.clock()
        native = getattr(self.evaluator, "evaluate_tensors", None)
        routes = selected.routes()
        unique_routes, unique_indices, unique_positions, inverse = [], {}, [], []
        for position, route in enumerate(routes):
            key = route.towers.tobytes()
            index = unique_indices.get(key)
            if index is None:
                index = len(unique_routes)
                unique_indices[key] = index
                unique_routes.append(route)
                unique_positions.append(position)
            inverse.append(index)
        if native is not None:
            if len(unique_routes) != len(routes):
                unique = selected.take(torch.tensor(unique_positions, device=batch.xy.device))
                unique_values = native(unique)
                inverse_tensor = torch.tensor(inverse, device=batch.xy.device)
                values = TensorEvaluationBatch(unique_values.objectives[inverse_tensor],
                                               unique_values.violations[inverse_tensor],
                                               unique_values.violation[inverse_tensor])
            else:
                values = native(selected)
            records = values.records()
        else:
            unique_records = self.evaluator.evaluate_many(unique_routes, details=False)
            records = [unique_records[index] for index in inverse]
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
