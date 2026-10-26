"""Explicit backend lifetime; workers finish before cancellation can release a scene."""

from contextlib import contextmanager

from .evaluator import RouteEvaluator, tower_cache_budget


@contextmanager
def evaluation_session(problem, config):
    if config.evaluation_backend == "tensor":
        if len(config.devices) > 1:
            from .multi_device_evaluator import MultiDeviceRouteEvaluator
            evaluator = MultiDeviceRouteEvaluator(problem, config)
        else:
            from .tensor_evaluator import TensorRouteEvaluator
            evaluator = TensorRouteEvaluator(problem, config)
    elif config.evaluation_backend == "compiled_cpu":
        from .compiled_evaluator import CompiledRouteEvaluator
        evaluator = CompiledRouteEvaluator(problem)
    else:
        evaluator = RouteEvaluator(problem).cache_geometry_checks(tower_cache_budget(problem, config.context_cache_mib))
    try:
        yield evaluator
    finally:
        close = getattr(evaluator, "close", None)
        if close is not None:
            close()
