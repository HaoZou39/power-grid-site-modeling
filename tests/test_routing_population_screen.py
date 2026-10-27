from dataclasses import replace

import numpy as np
import pytest
import torch

from algorithms.routing.evaluation_budget import EvaluationBudget
from algorithms.routing.pilot_reference.frozen_population import FrozenPopulation
from algorithms.routing.search import run_with_components
from modeling.routing.types import Route
from test_pilot_tensor_driver import full_config, routed_problem


def test_phase_caps_are_shared_by_existing_windows_and_clip_before_scoring():
    class Evaluator:
        def evaluate_many(self, rows, **kwargs):
            return rows
    budget = EvaluationBudget(Evaluator(), 10, 0., phase_limits={"local_search":3})
    first, second = budget.window("local_search",10), budget.window("local_search",10)
    assert first.evaluate_many([1,2]) == [1,2]
    assert second.remaining == first.remaining == 1
    assert second.evaluate_many([3,4,5]) == [3]
    assert first.remaining == 0 and first.evaluate(6) is None
    assert budget.window("offspring",10).evaluate_many([7,8]) == [7,8]
    assert budget.counts == {"local_search":3,"offspring":2}
    with pytest.raises(ValueError,match="phase limits"):
        EvaluationBudget(Evaluator(),10,0.,phase_limits={"local_search":-1})


@pytest.mark.parametrize("device", ["cpu","cuda:0"])
def test_frozen_nested_population_is_unique_billed_and_uses_the_replacement_builder(device,monkeypatch):
    import algorithms.routing.pilot_reference.tensor_driver as driver
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    monkeypatch.setattr(driver,"build_population",lambda *a,**k:pytest.fail("planner was not frozen"))
    routes = [Route(np.array([[10.,8.+i*.1],[19.,8.+i*.1]])) for i in range(4)]
    original = [route.towers.tobytes() for route in routes]
    digests=[]
    for size in [4,8]:
        config=replace(full_config([device],budget=128),popsize=size)
        sampler=FrozenPopulation(routes,2,3,{"local_search":12,"global_search":4},7,13)
        try:
            result=run_with_components(routed_problem(),config,sampler.components())
            stats=result.execution['pilot_initialization']
            assert result.evaluation_count==128
            assert result.initialization_evaluations==size
            assert result.execution['phase_evaluations'].get('local_search',0)<=12
            assert result.execution['phase_evaluations'].get('global_search',0)<=4
            assert stats['initial_unique_population']==size
            assert stats['initial_random_count']==size-4
            assert stats['new_rrt_calls']==stats['new_astar_calls']==0
            assert stats['frozen_global_random_evaluations']>0
            digests.append(stats['initial_common_sha256'])
        finally:
            sampler.close()
    assert digests[0]==digests[1]
    assert [route.towers.tobytes() for route in routes]==original


def test_seed_bank_uses_only_initialization_coordinates(tmp_path):
    from experiments.screen_routing_population import load_seed_bank
    path=tmp_path/"candidates.npz"
    xy=np.array([[4.,8.],[8.,8.],[10.,8.],[14.,8.],[18.,8.],[22.,8.]])
    np.savez(path,xy=xy,counts=np.array([2,2,2]),evaluation_indices=np.array([1,2,3]),
             feasible=np.array([False,True,True]))
    row={"candidate_file":str(path),"initialization_evaluations":2,"tower_count_lower":2,
         "initial_tower_upper":2,"execution":{"timings":{"initialization_s":7.}}}
    routes,metadata=load_seed_bank(row,2)
    assert metadata["source_evaluation_indices"]==[2,1]
    np.testing.assert_array_equal(routes[0].towers,xy[2:4])
    np.testing.assert_array_equal(routes[1].towers,xy[:2])
    with pytest.raises(ValueError,match="fewer unique seeds"):
        load_seed_bank(row,3)


@pytest.mark.parametrize("device", ["cpu","cuda:0"])
def test_generation_stopping_completes_the_same_number_of_generations(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    routes=[Route(np.array([[10.,8.+i*.1],[19.,8.+i*.1]])) for i in range(4)]
    for size in [4,8]:
        config=replace(full_config([device],budget=1024),popsize=size)
        sampler=FrozenPopulation(routes,2,3,{"local_search":12,"global_search":4},7,13)
        try:
            result=run_with_components(routed_problem(),config,sampler.components(max_generations=2))
            assert result.generation_count==2
            assert result.stop_reason=="generation_limit"
            assert result.evaluation_count<config.max_evaluations
            assert sum(result.execution['phase_evaluations'].values())==result.evaluation_count
        finally:
            sampler.close()
