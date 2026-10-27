from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from algorithms.routing.evaluation_budget import EvaluationBudget
from algorithms.routing.pilot_reference.adapter import PilotAdapter
from algorithms.routing.pilot_reference.runtime import Candidate, RunState, candidate_is_better
from config.project_config import load_default_config
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import Route
from pilot_reference import original_functions
from test_routing_context import make_problem


def state_for(problem=None, config=None, limit=256):
    problem = make_problem() if problem is None else problem
    config = load_default_config().routing if config is None else config
    evaluator = RouteEvaluator(problem)
    ledger = EvaluationBudget(evaluator, limit, 0.)
    return RunState(PilotAdapter(evaluator, config.seed), config, ledger, lambda *args: None)


def value(f, cv):
    return Candidate(Route(np.empty((0, 2))), SimpleNamespace(
        objectives=np.array(f, dtype=float), violation=cv, is_feasible=cv == 0), 0)


@pytest.mark.parametrize('a,b,ca,cb,target,margin', [
    ([3,10,2,5],[2,9,1,4],0,0,None,0),
    ([3,10,2,5],[2,11,1,4],0,0,None,0),
    ([3]*4,[100]*4,2,1,None,0),
    ([3]*4,[1]*4,0,1,None,0),
    ([3]*4,[100]*4,1,0,None,0),
    ([3,10,2,5],[3,8,2+1e-7,5],0,0,1,1.),
    ([3,10,2,5],[3,8,3,5],0,0,1,1.),
])
def test_candidate_acceptance_matches_original_neutral_branch(a,b,ca,cb,target,margin):
    original = original_functions('preference.py', ['_candidate_is_better'], {
        'PreferenceGuidance': object, '_utility_model_scores': lambda *a, **kw: None})['_candidate_is_better']
    expected = original(a,[ca],b,[cb],target_idx=target,target_margin=margin)
    actual = candidate_is_better(value(a,ca),value(b,cb),load_default_config().routing.pilot.core,
                                 target=target,margin=margin)
    assert actual == expected


def test_current_feasibility_is_not_relaxed_by_original_cv_tolerance():
    cfg = load_default_config().routing.pilot.core
    assert not candidate_is_better(value([3]*4,0),value([1]*4,1e-9),cfg)


def test_radius_scales_both_constants_and_distance_input():
    original = original_functions('path_operators.py', ['_adaptive_neighborhood_radius'], {
        '_path_internal_point_clearances':lambda _:np.array([0.,5.,100.])})['_adaptive_neighborhood_radius']
    state = state_for()
    for scale in [.5,1.,5.]:
        state.adapter.problem = replace(state.problem, constraints=replace(state.problem.constraints,
            max_span_m=scale*state.core.reference_max_step))
        state.clearance = lambda p: float(p[0])*scale
        for index in [1,2,3]:
            path=np.array([[0,0],[0,0],[5,0],[100,0],[0,0]],dtype=float)
            assert state.neighborhood_radius(path,index) == pytest.approx(scale*original(path,index))


def test_evaluated_identity_reuse_and_private_streams_are_per_run():
    a,b=state_for(),state_for()
    route=Route(np.empty((0,2)))
    checked=a.score(route,a.budget.window('trial',2))
    assert a.lookup(route) is checked
    assert len(a.budget.records)==1 and checked.evaluation_index==0
    a.adapter.python_rng.random()
    assert a.adapter.python_rng.getstate()!=b.adapter.python_rng.getstate()
    assert b.diagnostics=={} and b.candidates=={}


def test_cpu_entry_delegates_original_search_before_components_are_enabled():
    from algorithms.routing.search import routing_search
    cfg=replace(load_default_config().routing,evolution_backend='numpy',devices=['cpu'],
                search_strategy='pilot_reference',popsize=4,max_evaluations=32,reference_count=2)
    baseline=routing_search(make_problem(),cfg)
    migrated=routing_search(make_problem(),replace(cfg,pilot=replace(cfg.pilot,enabled_mechanisms=['cpu_driver'])))
    assert baseline.evaluation_count==migrated.evaluation_count
    assert baseline.pareto_indices==migrated.pareto_indices
    assert [r.towers.tobytes() for r in baseline.routes]==[r.towers.tobytes() for r in migrated.routes]


def test_correctness_manifest_never_computes_quality_metrics():
    from experiments.validate_pilot_components import stage_manifest
    result=stage_manifest(['one.json'],['cpu_driver'],'legacy',123,256)
    assert result['report_quality'] is False
    assert result['tasks'][0]['id']=='one'
