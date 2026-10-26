"""Synchronous device shards; global evolution and candidate order stay unchanged."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import torch

from .compiled_evaluator import CompiledRouteEvaluator
from .tensor_evaluator import TensorRouteEvaluator


class MultiDeviceRouteEvaluator(CompiledRouteEvaluator):
    def __init__(self, problem, config):
        super().__init__(problem)
        self.engines = [TensorRouteEvaluator(problem, replace(config, devices=[name])) for name in config.devices]
        self.pool = ThreadPoolExecutor(max_workers=len(self.engines), thread_name_prefix="routing-eval")

    @property
    def boundary_rechecks(self):
        return sum(engine.boundary_rechecks for engine in self.engines)

    def evaluate_many(self, routes, *, details=True):
        if not routes:
            return []
        width = (len(routes) + len(self.engines) - 1) // len(self.engines)
        def run(engine, chunk):
            with torch.cuda.device(engine.device):
                return engine.evaluate_many(chunk, details=details)
        futures = [self.pool.submit(run, engine, routes[index * width:(index + 1) * width])
                   for index, engine in enumerate(self.engines) if index * width < len(routes)]
        return [value for future in futures for value in future.result()]

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        for engine in self.engines:
            engine.close()
        self.engines.clear()
