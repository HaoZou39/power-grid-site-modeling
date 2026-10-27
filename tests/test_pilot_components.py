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


def test_astar_heap_and_backtracking_match_frozen_single_grid_source():
    from algorithms.routing.pilot_reference.astar import astar_grid
    original=original_functions('path_planners.py',['_astar_on_binary_grid'],{})['_astar_on_binary_grid']
    for blocked in [np.zeros((8,8),dtype=bool),np.eye(8,dtype=bool),np.ones((8,8),dtype=bool)]:
        expected=original(blocked,(0,0),(7,6))
        actual=astar_grid(blocked.shape,(0,0),(7,6),allowed=lambda p:not blocked[p[1],p[0]],
                          distance=lambda a,b:float(np.hypot(a[0]-b[0],a[1]-b[1])))
        assert actual==expected


def test_metric_astar_crosses_water_without_putting_towers_inside_it():
    from algorithms.routing.pilot_reference.astar import metric_astar
    landuse=np.zeros((32,32),dtype=np.int32);landuse[:,12:20]=5
    problem=make_problem(landuse=landuse)
    state=state_for(problem)
    path=metric_astar(state,4)
    assert path is not None
    assert np.array_equal(path[[0,-1]],[problem.start,problem.end])
    assert all(state.evaluator.tower_allowed(p) for p in path[1:-1])
    assert any(a[0]<12 and b[0]>=20 for a,b in zip(path[:-1],path[1:]))
    assert state.evaluator.evaluate(state.adapter.route(path)).is_feasible


def test_metric_astar_respects_no_cross_and_does_not_report_straight_fallback():
    from algorithms.routing.pilot_reference.astar import metric_astar
    state=state_for(make_problem(no_cross_zones=[[[14,0],[18,0],[18,32],[14,32]]]))
    assert metric_astar(state,4) is None
    assert state.diagnostics.get('astar_successes',0)==0


def test_astar_three_dimensional_cost_selects_a_shorter_spatial_detour():
    from algorithms.routing.pilot_reference.astar import astar_grid
    heights=np.zeros((3,5));heights[1,1:4]=100
    def cost(a,b):
        return float(np.sqrt((a[0]-b[0])**2+(a[1]-b[1])**2+(heights[a[1],a[0]]-heights[b[1],b[0]])**2))
    path=astar_grid(heights.shape,(0,1),(4,1),allowed=lambda _:True,distance=cost)
    assert not any(y==1 and 1<=x<=3 for x,y in path)
    assert sum(cost(a,b) for a,b in zip(path[:-1],path[1:]))<10


def test_astar_component_injects_evaluated_seed_into_actual_search():
    from algorithms.routing.search import routing_search
    base=load_default_config().routing
    cfg=replace(base,evolution_backend='numpy',devices=['cpu'],search_strategy='pilot_reference',
                popsize=4,max_evaluations=96,reference_count=2,navigation_step_m=4,
                pilot=replace(base.pilot,enabled_mechanisms=['astar']))
    result=routing_search(make_problem(),cfg)
    stats=result.execution['pilot_initialization']
    assert stats['astar_attempts']>0
    assert stats['astar_successes']>0
    assert result.evaluation_count==96
    assert all(RouteEvaluator(make_problem()).evaluate(r).is_feasible for r,e in zip(result.routes,result.evaluations) if e.is_feasible)


def test_real_jobs_probe_publishes_inside_its_explicit_output(tmp_path,monkeypatch):
    import json,os
    from experiments.validate_pilot_components import stage_manifest,validate_job
    from test_routing_output import routing_task
    task,_=routing_task(tmp_path,monkeypatch)
    path=tmp_path/'task.json';path.write_text(task.model_dump_json())
    outside=tmp_path/'outside';monkeypatch.setenv('EXPERIMENT_OUTPUT_ROOT',str(outside))
    manifest=stage_manifest([str(path)],['cpu_driver'],'legacy',123,64)
    output=tmp_path/'probe'
    job=validate_job(path,manifest,output)
    assert job['status']=='succeeded'
    assert (output/'cpu-components-job/run_summary.json').is_file()
    assert not (outside/'cpu-components-job').exists()
    assert os.environ['EXPERIMENT_OUTPUT_ROOT']==str(outside)


def test_polyline_resampling_matches_original_without_legacy_encoding():
    from algorithms.routing.pilot_reference.hybrid import resample_path
    original=original_functions('path_metrics.py',['_polyline_cumlen','_resample_polyline'],{})['_resample_polyline']
    for path in [np.array([[0.,0.],[3.,0.],[3.,4.]]),np.zeros((2,2)),np.empty((0,2))]:
        np.testing.assert_array_equal(resample_path(path,7),original(path,7))


@pytest.mark.parametrize('limit',[4,96])
def test_hybrid_initialization_records_actual_unique_slots_and_bounded_reuse(limit):
    from algorithms.routing.search import routing_search
    base=load_default_config().routing
    cfg=replace(base,evolution_backend='numpy',devices=['cpu'],search_strategy='pilot_reference',
                popsize=4,max_evaluations=limit,reference_count=2,navigation_step_m=4,
                pilot=replace(base.pilot,initialization_mode='hybrid',enabled_mechanisms=['astar','rrt']))
    first=routing_search(make_problem(),cfg);second=routing_search(make_problem(),cfg)
    stats=first.execution['pilot_initialization']
    assert stats['initial_population_size']==4
    assert 0<stats['initial_unique_population']<=4
    assert first.evaluation_count==limit
    assert [r.towers.tobytes() for r in first.routes]==[r.towers.tobytes() for r in second.routes]
    assert first.final_upper>=first.initial_upper>=first.lower
