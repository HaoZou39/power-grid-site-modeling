"""Synchronous device shards; global evolution and candidate order stay unchanged."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import torch

from .compiled_evaluator import CompiledRouteEvaluator
from .tensor_evaluator import TensorRouteEvaluator
from .tensor_types import TowerBatch, TensorEvaluationBatch
from .device_memory import require_workspace


class MultiDeviceRouteEvaluator(CompiledRouteEvaluator):
    def __init__(self, problem, config):
        super().__init__(problem)
        self.engines = []
        try:
            for name in config.devices:
                self.engines.append(TensorRouteEvaluator(problem, replace(config, devices=[name])))
        except BaseException:
            for engine in self.engines:
                engine.close()
            raise
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

    def evaluate_tensors(self, batch):
        if not len(batch):
            return TensorEvaluationBatch.from_records([], batch.xy.device)
        width = (len(batch)+len(self.engines)-1)//len(self.engines)
        def run(engine, start):
            with torch.cuda.device(engine.device):
                xy, counts = batch.xy[start:start+width], batch.counts[start:start+width]
                require_workspace(engine.device, xy.numel()*8+counts.numel()*8, engine.config.gpu_memory_budget_mib)
                return engine.evaluate_tensors(TowerBatch(xy.to(engine.device), counts.to(engine.device)))
        futures = [self.pool.submit(run, engine, index*width) for index, engine in enumerate(self.engines)
                   if index*width < len(batch)]
        values = []
        for future in futures:
            result = future.result()
            values.append(TensorEvaluationBatch(*(getattr(result, name).to(batch.xy.device)
                for name in ("objectives", "violations", "violation"))))
        return TensorEvaluationBatch.concatenate(values)

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        for engine in self.engines:
            engine.close()
        self.engines.clear()
