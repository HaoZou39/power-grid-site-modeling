"""Independent CPU composition for incrementally migrated PILOT control flow."""

from dataclasses import dataclass, replace

from ..initial_population import InitialPopulation, initialize_population
from ..numpy_search import evolve as baseline_evolve
from .adapter import PilotAdapter
from .runtime import RunState


@dataclass
class PilotInitialPopulation(InitialPopulation):
    run_state: RunState


def initialize(evaluator, config, rng, budget, report):
    hybrid = config.pilot.initialization_mode == "hybrid"
    base_config = replace(config, pilot=replace(config.pilot, initialization_mode="legacy", enabled_mechanisms=[])) if hybrid else config
    initial = initialize_population(evaluator, base_config, rng, budget, report)
    diagnostics = dict(initial.diagnostics or {})
    state = RunState(PilotAdapter(evaluator, config.seed), config, budget, report, diagnostics)
    state.remember()
    diagnostics["implementation"] = "pilot_cpu"
    result = PilotInitialPopulation(initial.population, initial.bounds, diagnostics, initial.candidates, state)
    if hybrid:
        from .hybrid import initialize_hybrid
        initialize_hybrid(result, state)
    elif "astar" in config.pilot.enabled_mechanisms:
        from .astar import append_astar_seeds
        append_astar_seeds(result, state)
    return result


def evolve(evaluator, config, initial, budget, rng, report):
    # Until a migrated operator is enabled, the new entry delegates unchanged CPU behavior.
    return baseline_evolve(evaluator, config, initial, budget, rng, report)
