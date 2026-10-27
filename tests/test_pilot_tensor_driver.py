from dataclasses import replace

import numpy as np
import pytest
import torch

from algorithms.routing.search import routing_search
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from test_routing_context import make_problem
from test_pilot_tensor_variation import tensor_state


MECHANISMS = ["cpu_driver", "astar", "rrt", "nearby_crossover", "distinct_parents", "path_mutation",
              "shorten", "smooth", "elite_local_search", "global_injection", "population_dedup"]


def full_config(devices, *, budget=256, batch_size=4):
    base = load_default_config().routing
    return replace(base, search_strategy="pilot_reference", evolution_backend="tensor", evaluation_backend="tensor",
        devices=devices, popsize=4, max_evaluations=budget, reference_count=2, navigation_step_m=4,
        evaluation_batch_size=batch_size, expansion_interval=1,
        pilot=replace(base.pilot, initialization_mode="hybrid", enabled_mechanisms=MECHANISMS))


def routed_problem():
    problem = make_problem()
    return replace(problem, constraints=replace(problem.constraints, max_span_m=10.))


@pytest.mark.parametrize("devices", [["cpu"], ["cuda:0"], ["cuda:0", "cuda:1"]])
def test_full_pilot_tensor_driver_runs_all_phases_and_reproduces_across_microbatches(devices):
    if devices[0].startswith("cuda") and torch.cuda.device_count() < len(devices):
        pytest.skip("requested CUDA devices unavailable")
    problem = routed_problem()
    results = [routing_search(problem, full_config(devices, batch_size=n)) for n in [3, 16]]
    for result in results:
        assert result.evaluation_count == 256 and result.generation_count > 0
        assert sum(result.execution["phase_evaluations"].values()) == 256
        assert result.execution["pilot_initialization"]["implementation"] == "pilot_tensor"
        stats = result.execution["pilot_initialization"]
        for name in ["crossover_calls", "mutation_calls", "shorten_calls", "smooth_calls", "local_calls", "vns_draws", "global_calls"]:
            assert stats.get(name, 0) > 0, (name, stats)
        assert result.expansions
        assert result.execution["planner_device"] == "cpu"
        reference = RouteEvaluator(problem)
        for route, value in zip(result.routes, result.evaluations):
            checked = reference.evaluate(route)
            np.testing.assert_allclose(value.objectives, checked.objectives, atol=1e-8, rtol=1e-10)
            assert checked.is_feasible == value.is_feasible
        assert max(result.evaluation_indices) <= 256
    assert results[0].evaluation_count == results[1].evaluation_count
    assert results[0].pareto_indices == results[1].pareto_indices
    assert [r.towers.tobytes() for r in results[0].routes] == [r.towers.tobytes() for r in results[1].routes]


def test_full_pilot_initialization_exhaustion_and_partial_final_batch():
    for limit in [4, 37]:
        result = routing_search(routed_problem(), full_config(["cpu"], budget=limit))
        assert result.evaluation_count == limit
        assert sum(result.execution["phase_evaluations"].values()) == limit
        assert all(np.isfinite(route.towers).all() for route in result.routes)


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_full_pilot_cancellation_releases_scene_and_clearance(monkeypatch, device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    from algorithms.routing.pilot_reference.tensor_geometry import PilotTensorGeometry
    from modeling.routing.tensor_evaluator import TensorRouteEvaluator
    closed, fields = [], []
    close = PilotTensorGeometry.close
    original = TensorRouteEvaluator.close
    def release(self):
        close(self)
        closed.append(self._clearance)
    def field_release(self):
        original(self)
        fields.append((self.dem, self.blocked, self.crossing))
    monkeypatch.setattr(PilotTensorGeometry, "close", release)
    monkeypatch.setattr(TensorRouteEvaluator, "close", field_release)
    class Cancelled(Exception):
        pass
    def cancel(fraction, stage, message):
        if "张量批处理" in message:
            raise Cancelled()
    with pytest.raises(Cancelled):
        routing_search(routed_problem(), full_config([device]), cancel)
    assert closed == [None] and fields == [(None, None, None)]


def test_elite_quota_recycles_unused_budget_and_rejects_encoding_loss(tensor_state, monkeypatch):
    from algorithms.routing.pilot_reference import tensor_local_search as local
    from algorithms.routing.ranges import TowerRange
    from test_pilot_tensor_variation import scored
    state = tensor_state
    parents = scored(state, [[[10.,10.],[19.,9.]], [[11.,12.]]])
    monkeypatch.setattr(local, "elite_indices", lambda *args: (torch.tensor([0,1],device=state.device),
        torch.tensor([True,True],device=state.device)))
    limits, target = [], {}
    def refine(current, state, window, **kwargs):
        limits.append(window.limit)
        if len(limits) == 1:
            state.score(current.routes,window)
            state.score(current.routes,window)
            return current
        target["routes"] = current.routes
        moved = current.routes.clone()
        moved.xy += .1
        candidate = state.score(moved,window)
        candidate.values.objectives = current.values.objectives-1
        return candidate
    monkeypatch.setattr(local,"vns",refine)
    monkeypatch.setattr(local,"encode_candidate",lambda *args: target["routes"])
    before = len(state.budget.records)
    result = local.refine_population(parents,TowerRange(0,4,4),state,lambda _: pytest.fail("degraded encoding admitted"))
    limit = min(state.budget.total_limit-before,state.config.pilot.local_budget_factor*state.config.popsize)
    assert limits == [int(np.ceil(limit/2))-1,limit-2-1]
    assert result is parents and len(state.budget.records)-before == 4
    assert state.diagnostics["local_raw_accepts"] == 1
    assert state.diagnostics.get("local_encoded_accepts",0) == 0


def test_full_pilot_cuda_runs_through_real_jobs_and_publishes_config(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict
    from experiments.validate_pilot_components import validate_job
    from tests.test_routing_output import routing_task
    if not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    config = full_config(["cuda:0"], budget=128)
    task, _ = routing_task(tmp_path,monkeypatch,max_span_m=10,algorithm=asdict(config))
    task_path = tmp_path/"task.json"
    task_path.write_text(task.model_dump_json())
    output = tmp_path/"job"
    job = validate_job(task_path,{"cases":[{"routing":asdict(config)}]},output)
    assert job["status"] == "succeeded"
    summary = json.loads((output/"cpu-components-job/run_summary.json").read_text())
    assert summary["evaluation_count"] == 128
    assert summary["execution_details"]["pilot_initialization"]["implementation"] == "pilot_tensor"
    assert summary["execution_details"]["evolution_device"] == "cuda:0"
