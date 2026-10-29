"""Evaluation-budgeted NSGA-II on variable-length tower sequences."""

from __future__ import annotations

from typing import Callable
import time

import numpy as np

from config.project_config import RoutingConfig
from modeling.routing.context import RoutingProblem
from .evaluation_budget import EvaluationBudget
from .types import RoutingResult
from .archive import archive_result


def routing_search(problem: RoutingProblem, config: RoutingConfig,
                   reporter: Callable[[float, str, str], None] | None = None) -> RoutingResult:
    from .components import builtin_components
    return run_with_components(problem, config, builtin_components(config), reporter)


def run_with_components(problem, config, components, reporter=None):
    """Python research composition; the Jobs/config/public search contract stays unchanged."""
    from modeling.routing.evaluation_session import evaluation_session
    search_started = time.perf_counter()
    with evaluation_session(problem, config) as evaluator:
        return _routing_search(problem, config, reporter, evaluator, search_started, components)


def _routing_search(problem, config, reporter, evaluator, search_started, components):
    rng = np.random.default_rng(config.seed)
    budget = EvaluationBudget(evaluator, None, search_started)
    records = budget.records
    stage_times = {"evaluator_setup_s": time.perf_counter() - search_started, "evaluation_s": 0.,
                   "initialization_s": 0., "ranking_s": 0., "variation_and_repair_s": 0.}

    def report(stage: str, message: str):
        if reporter:
            reporter(budget.completed_generations / config.max_generations, stage, message)

    started = time.perf_counter()
    initial = components.initializer(evaluator, config, rng, budget, report)
    population, bounds, pilot_initialization = initial.population, initial.bounds, initial.diagnostics
    stage_times["initialization_s"] = time.perf_counter() - started
    initialization_evaluations = len(records)
    expansions, generation = [], 0
    active_devices = config.devices if config.evaluation_backend == "tensor" else (config.devices[:1] if config.evolution_backend == "tensor" else ["cpu"])
    execution = {"search_strategy": config.search_strategy, "enabled_mechanisms": list(config.pilot.enabled_mechanisms),
                 "evolution_backend": config.evolution_backend, "evaluation_backend": config.evaluation_backend,
                 "devices": active_devices, "requested_devices": config.devices, "dtype": "float64"}
    if config.search_strategy == "pilot_reference":
        from .pilot_reference.adapter import source_identity
        execution["pilot_source"] = source_identity()
        if pilot_initialization is not None:
            execution["pilot_initialization"] = pilot_initialization
        if config.evolution_backend == "tensor":
            execution.update(evolution_device=config.devices[0], geometry_device=config.devices[0],
                             planner_device="cpu", initialization_evaluation_backend="compiled_cpu",
                             global_seed_evaluation_backend="compiled_cpu", final_validation_device="cpu")
    if population:
        expansions, driver_times, generation = components.driver(evaluator, config, initial, budget, rng, report)
        stage_times.update({name: value for name, value in driver_times.items() if name != "evaluation_s"})
    stage_times["evaluation_s"] = budget.evaluation_s
    execution["phase_evaluations"] = budget.counts
    execution["evaluation_cache_hits"] = budget.cache_hits
    execution["timings"] = stage_times
    execution["boundary_rechecks"] = getattr(evaluator, "boundary_rechecks", 0)
    if any(name.startswith("cuda:") for name in active_devices):
        import torch
        execution["gpu_memory"] = {name: {"peak_allocated_mib": torch.cuda.max_memory_allocated(name) / 1024**2,
            "peak_reserved_mib": torch.cuda.max_memory_reserved(name) / 1024**2} for name in active_devices}
    return archive_result(problem, config, budget, bounds, expansions, generation,
                          initialization_evaluations, execution, report, reporter)
