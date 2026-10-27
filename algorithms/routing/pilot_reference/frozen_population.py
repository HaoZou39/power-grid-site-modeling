"""Research composition: common cached seeds and device-random population fill."""

from functools import partial
import hashlib

import torch

from algorithms.common.nsga2 import Individual
from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
from modeling.routing.tensor_queries import TensorRouteGeometry
from modeling.routing.tensor_types import TowerBatch
from ..components import SearchComponents
from ..ranges import TowerRange
from .adapter import PilotAdapter
from .driver import PilotInitialPopulation
from .runtime import RunState
from .tensor_driver import evolve
from .tensor_geometry import PilotTensorGeometry
from .tensor_population import TensorPopulation
from .tensor_repair import repair_towers
from .tensor_runtime import TensorRunState


class FrozenPopulation:
    def __init__(self, routes, lower, upper, phase_limits, initial_seed, global_seed):
        if not routes or any(not lower <= len(route.towers) <= upper for route in routes):
            raise ValueError("frozen population requires in-range seed coordinates")
        self.routes, self.lower, self.upper = routes, lower, upper
        self.phase_limits, self.initial_seed, self.global_seed = phase_limits, initial_seed, global_seed
        self.bank = self.global_generator = None

    def close(self):
        self.bank = self.global_generator = None

    def draw(self, count, geometry, generator):
        bank = self.bank
        device = bank.xy.device
        selected = torch.randint(len(bank), (count,), device=device, generator=generator)
        result = bank.take(selected)
        if result.xy.shape[1] and count:
            rows = torch.arange(count, device=device)
            indices = (torch.rand(count, device=device, dtype=torch.float64, generator=generator)*result.counts).long()
            noise = torch.randn((count, 2), device=device, dtype=torch.float64, generator=generator)
            active = result.counts > 0
            result.xy[rows[active], indices[active]] += noise[active]*geometry.config.mutation_scale*geometry.problem.constraints.max_span_m
            radius = geometry.problem.constraints.tower_radius_m
            if min(geometry.problem.frame.width, geometry.problem.frame.height) >= 2*radius:
                high = result.xy.new_tensor([geometry.problem.frame.width-radius,geometry.problem.frame.height-radius])
                result.xy = result.xy.clamp_min(radius).minimum(high)
        return repair_towers(result, geometry, generator)

    def initialize(self, evaluator, config, rng, budget, report):
        if config.popsize < len(self.routes):
            raise ValueError("population must include the entire common seed bank")
        engine = evaluator.engines[0] if hasattr(evaluator,"engines") else evaluator
        geometry = PilotTensorGeometry(TensorRouteGeometry(engine), config)
        generator = torch.Generator(device=engine.device).manual_seed(self.initial_seed)
        self.global_generator = torch.Generator(device=engine.device).manual_seed(self.global_seed)
        self.bank = TowerBatch.from_routes(self.routes, engine.device)
        budget.phase_limits.update(self.phase_limits)
        host = RunState(PilotAdapter(CompiledRouteEvaluator(evaluator.problem), config.seed), config, budget, report)
        state = TensorRunState(host, geometry, generator)
        try:
            extra = self.draw(config.popsize-len(self.routes), geometry, generator)
            batch = TowerBatch.concatenate([self.bank, extra])
            checked = state.score(batch, budget.window("initialization", config.popsize), origin="frozen_initial")
            if not bool((checked.ids >= 0).all()):
                raise ValueError("initialization budget cannot cover the requested population")
            records = budget.records
            digest = hashlib.sha256()
            for route, value in records[:len(self.routes)]:
                digest.update(route.towers.tobytes())
            host.diagnostics.update(implementation="pilot_tensor_frozen_bank", initial_population_size=config.popsize,
                initial_unique_population=len({route.towers.tobytes() for route,value in records}),
                initial_feasible_population=sum(value.is_feasible for route,value in records),
                initial_common_sha256=digest.hexdigest(), initial_random_count=len(extra),
                planning_mode="cached_initial_coordinates", new_rrt_calls=0, new_astar_calls=0,
                research_phase_limits=dict(self.phase_limits))
            population = [Individual(route.towers,value.objectives,value.violation) for route,value in records]
            return PilotInitialPopulation(population, TowerRange(self.lower,self.upper,self.upper),
                host.diagnostics, list(records), host)
        finally:
            geometry.close()

    def global_random(self, state, bounds, window, target, fallback):
        count = min(target, window.remaining)
        routes = self.draw(count, state.geometry, self.global_generator)
        result = state.score(routes, window, origin="frozen_global_random")
        state.count("frozen_global_random_evaluations", count)
        if count < target:
            indices = torch.arange(target-count, device=state.device)%len(fallback)
            result = TensorPopulation.concatenate([result, fallback.take(indices)])
            state.count("frozen_global_reused_slots", target-count)
        return result

    def components(self):
        return SearchComponents(self.initialize, partial(evolve, fresh_builder=self.global_random))
