"""One search ledger shared by initialization, operators and bounded phase calls."""

import time


class EvaluationBudget:
    def __init__(self, evaluator, total_limit, started, *, clock=time.perf_counter):
        self.evaluator, self.total_limit, self.started = evaluator, total_limit, started
        self.clock = clock
        self.records, self.times = [], []
        self.counts = {}
        self.evaluation_s = 0.

    def window(self, source, limit):
        return EvaluationWindow(self, source, limit)

    def evaluate_many(self, routes, source):
        routes = routes[:max(0, self.total_limit - len(self.records))]
        if not routes:
            return []
        started = self.clock()
        values = self.evaluator.evaluate_many(routes, details=False)
        self.evaluation_s += self.clock() - started
        if len(values) != len(routes):
            raise RuntimeError("routing evaluator returned the wrong batch size")
        self.records.extend(zip(routes, values))
        self.times.extend([self.clock() - self.started] * len(values))
        self.counts[source] = self.counts.get(source, 0) + len(values)
        return values


class EvaluationWindow:
    def __init__(self, budget, source, limit):
        if type(limit) is not int or limit < 0:
            raise ValueError("evaluation window limit must be a non-negative integer")
        self.budget, self.source, self.limit = budget, source, limit
        self.used = 0

    def evaluate_many(self, routes):
        values = self.budget.evaluate_many(routes[:max(0, self.limit - self.used)], self.source)
        self.used += len(values)
        return values

    def evaluate(self, route):
        values = self.evaluate_many([route])
        return values[0] if values else None
