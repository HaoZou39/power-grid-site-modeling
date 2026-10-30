from dataclasses import replace
import numpy as np
import pytest
import torch
from algorithms.routing.evaluation_budget import EvaluationBudget
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.tensor_types import TensorEvaluationBatch, TowerBatch
from modeling.routing.types import Route
from test_routing_context import make_problem


def native_config(device="cpu", batch_size=3):
    return replace(load_default_config().routing, evolution_backend="tensor", evaluation_backend="tensor",
                   devices=[device], evaluation_batch_size=batch_size)


@pytest.mark.parametrize("device",["cpu","cuda:0"])
@pytest.mark.parametrize("manual",[False,True])
def test_native_evaluation_matches_reference_and_ignores_poisoned_padding(device,manual):
    if device.startswith("cuda") and not torch.cuda.is_available():pytest.skip("CUDA unavailable")
    zones=[[[12.,16.],[18.,16.],[18.,20.],[12.,20.]]] if manual else []
    landuse=np.zeros((32,32),dtype=np.int32);landuse[10:13,12:17]=5
    problem=make_problem(landuse=landuse,no_tower_zones=zones,no_cross_zones=zones)
    rng=np.random.default_rng(17)
    routes=[Route(np.empty((0,2))),Route(np.array([[14.,8.]])),Route(np.array([[.4,8.],[14,18.]]))]
    routes += [Route(rng.uniform(-1,33,(int(rng.integers(5)),2))) for _ in range(21)]
    batch=TowerBatch.from_routes(routes,device,6)
    valid=torch.arange(6,device=device)[None,:]<batch.counts[:,None]
    batch.xy[~valid]=float("nan")
    engine=TensorRouteEvaluator(problem,native_config(device))
    try:
        checked=engine.evaluate_tensors(batch)
        reference=RouteEvaluator(problem).evaluate_many(routes,details=False)
        np.testing.assert_allclose(checked.objectives.cpu(),[x.objectives for x in reference],rtol=1e-10,atol=1e-8)
        np.testing.assert_allclose(checked.violation.cpu(),[x.violation for x in reference],rtol=1e-10,atol=1e-8)
        np.testing.assert_array_equal((checked.violation==0).cpu(),[x.is_feasible for x in reference])
        for a,b in zip(checked.records(),reference):
            for key in b.violations:assert a.violations[key]==pytest.approx(b.violations[key],rel=1e-10,abs=1e-8)
        assert checked.objectives.device==torch.device(device)
    finally:engine.close()


@pytest.mark.parametrize("backend",["native","reference"])
def test_tensor_windows_truncate_before_evaluation_and_keep_all_phase_records(backend):
    problem=make_problem()
    engine=TensorRouteEvaluator(problem,native_config()) if backend=="native" else RouteEvaluator(problem)
    try:
        budget=EvaluationBudget(engine,5,0.,clock=lambda:1.)
        routes=[Route(np.array([[float(x),8.]])) for x in [8,10,12,14]]
        batch=TowerBatch.from_routes(routes,"cpu",2)
        window=budget.window("offspring",3)
        first=window.evaluate_tensors(batch)
        assert len(first)==3 and window.used==3 and len(budget.records)==3
        assert len(window.evaluate_tensors(batch))==0
        second=budget.window("local_search",4).evaluate_tensors(batch)
        assert len(second)==2 and budget.remaining==0
        assert budget.counts=={"offspring":3,"local_search":2}
        assert [r.towers.tobytes() for r,v in budget.records]==[r.towers.tobytes() for r in routes[:3]+routes[:2]]
        assert budget.times==[1.]*5
    finally:
        if hasattr(engine,"close"):engine.close()


def test_tensor_window_evaluates_duplicate_routes_once_but_records_each_request():
    class Evaluator:
        def __init__(self):
            self.calls = []

        def evaluate_tensors(self, batch):
            self.calls.append(len(batch))
            objectives = torch.arange(len(batch) * 4, dtype=torch.float64).reshape(-1, 4)
            violations = torch.zeros((len(batch), 8), dtype=torch.float64)
            return TensorEvaluationBatch(objectives, violations, torch.zeros(len(batch), dtype=torch.float64))

    first = Route(np.array([[8., 8.]]))
    second = Route(np.array([[10., 8.]]))
    batch = TowerBatch.from_routes([first, first, second], "cpu", 1)
    evaluator = Evaluator()
    budget = EvaluationBudget(evaluator, 3, 0., clock=lambda: 1.)
    values = budget.window("offspring", 3).evaluate_tensors(batch)

    assert evaluator.calls == [2]
    assert len(values) == len(budget.records) == 3
    assert torch.equal(values.objectives[0], values.objectives[1])
    assert not torch.equal(values.objectives[0], values.objectives[2])


def test_native_budget_deduplicates_before_cpu_route_conversion(monkeypatch):
    from modeling.routing.tensor_types import TowerBatch

    first = Route(np.array([[8., 8.]]))
    second = Route(np.array([[10., 8.]]))
    batch = TowerBatch.from_routes([first, first, second], "cpu", 2)
    calls = []

    original_routes = TowerBatch.routes

    def tracked_routes(self):
        calls.append(("routes", len(self)))
        return original_routes(self)

    monkeypatch.setattr(TowerBatch, "routes", tracked_routes)

    class Evaluator:
        def evaluate_tensors(self, selected):
            calls.append(("native", len(selected)))
            objectives = torch.arange(len(selected) * 4, dtype=torch.float64).reshape(-1, 4)
            violations = torch.zeros((len(selected), 8), dtype=torch.float64)
            return TensorEvaluationBatch(objectives, violations, torch.zeros(len(selected), dtype=torch.float64))

    budget = EvaluationBudget(Evaluator(), 3, 0., clock=lambda: 1.)
    values = budget.window("offspring", 3).evaluate_tensors(batch)

    assert calls == [("native", 2), ("routes", 3)]
    assert len(values) == len(budget.records) == 3


@pytest.mark.parametrize("device",["cpu","cuda:0"])
def test_native_evaluation_chunking_changes_neither_values_nor_feasibility(device):
    if device.startswith("cuda") and not torch.cuda.is_available():pytest.skip("CUDA unavailable")
    problem=make_problem();rng=np.random.default_rng(21)
    routes=[Route(rng.uniform(2,30,(int(rng.integers(4)),2))) for _ in range(13)]
    batch=TowerBatch.from_routes(routes,device,4)
    results=[]
    for size in [1,4,32]:
        engine=TensorRouteEvaluator(problem,native_config(device,batch_size=size))
        try:results.append(engine.evaluate_tensors(batch))
        finally:engine.close()
    for actual in results[1:]:
        assert torch.equal(results[0].objectives,actual.objectives)
        assert torch.equal(results[0].violations,actual.violations)
        assert torch.equal(results[0].violation,actual.violation)


def test_native_evaluation_empty_and_invalid_counts_are_explicit():
    engine=TensorRouteEvaluator(make_problem(),native_config())
    try:
        assert len(engine.evaluate_tensors(TowerBatch.from_routes([],"cpu",0)))==0
        batch=TowerBatch(torch.zeros((1,2,2),dtype=torch.float64),torch.tensor([3]))
        with pytest.raises(ValueError,match="capacity"):engine.evaluate_tensors(batch)
    finally:engine.close()
