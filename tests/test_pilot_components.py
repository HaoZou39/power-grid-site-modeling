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
    config = replace(load_default_config().routing, search_strategy="pilot_reference", evolution_backend="numpy",
                     evaluation_backend="compiled_cpu", devices=["cpu"]) if config is None else config
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
    base = load_default_config().routing
    cfg=replace(base,evolution_backend='numpy',evaluation_backend='compiled_cpu',devices=['cpu'],
                search_strategy='pilot_reference',popsize=4,max_generations=2, max_evaluations=32,reference_count=2,
                pilot=replace(base.pilot, initialization_mode='legacy', enabled_mechanisms=[]))
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
    cfg=replace(base,evolution_backend='numpy',evaluation_backend='compiled_cpu',devices=['cpu'],search_strategy='pilot_reference',
                popsize=4,max_generations=2, max_evaluations=96,reference_count=2,navigation_step_m=4,
                pilot=replace(base.pilot,enabled_mechanisms=['astar']))
    result=routing_search(make_problem(),cfg)
    stats=result.execution['pilot_initialization']
    assert stats['astar_attempts']>0
    assert stats['astar_successes']>0
    assert result.generation_count==cfg.max_generations
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
    cfg=replace(base,evolution_backend='numpy',evaluation_backend='compiled_cpu',devices=['cpu'],search_strategy='pilot_reference',
                popsize=4,max_generations=2, max_evaluations=limit,reference_count=2,navigation_step_m=4,
                pilot=replace(base.pilot,initialization_mode='hybrid',enabled_mechanisms=['astar','rrt']))
    first=routing_search(make_problem(),cfg);second=routing_search(make_problem(),cfg)
    stats=first.execution['pilot_initialization']
    assert stats['initial_population_size']==4
    assert 0<stats['initial_unique_population']<=4
    assert first.generation_count==cfg.max_generations
    assert [r.towers.tobytes() for r in first.routes]==[r.towers.tobytes() for r in second.routes]
    assert first.final_upper>=first.initial_upper>=first.lower


@pytest.mark.parametrize('improve',[False,True])
def test_spatial_crossover_matches_original_candidate_order_and_early_exit(improve):
    from algorithms.routing.pilot_reference.variation import crossover
    a=np.array([[2.,8.],[10.,8.],[18.,8.],[28.,8.]])
    b=np.array([[2.,8.],[10.,9.],[18.,9.],[28.,8.]])
    source_trace=[]
    def metrics(path,grid):
        source_trace.append(np.asarray(path).tolist())
        return ([0.]*4 if improve and len(source_trace)==3 else [1.]*4),[0.]
    bindings=original_functions('preference.py',['_candidate_is_better'],{
        'PreferenceGuidance':object,'_utility_model_scores':lambda *a,**k:None})
    bindings.update(PreferenceGuidance=object,PATH_CROSSOVER_MAX_PAIRS=4,compute_path_metrics=metrics,
        _neutral_prefer_safety=lambda:0.,_edge_is_collision_free=lambda *a:True,
        _path_is_collision_free=lambda *a:True,_sanitize_path_candidate=lambda p,*a,**k:p)
    original=original_functions('path_operators.py',['_select_better_path_bundle','_path_crossover_operator'],bindings)
    expected=original['_path_crossover_operator'](a,b,None)
    state=state_for();state.evaluator.span_allowed=lambda *args:True
    state.sanitize=lambda p:p;state.valid_path=lambda p:True
    traces=[]
    def score(route,window):
        traces.append(state.adapter.path(route).tolist())
        f=[0.]*4 if improve and len(traces)==1 else [1.]*4
        return Candidate(route,SimpleNamespace(objectives=np.array(f),is_feasible=True,violation=0.),len(traces))
    state.score=score
    f=SimpleNamespace(objectives=np.ones(4),is_feasible=True,violation=0.)
    actual=crossover(Candidate(state.adapter.route(a),f,0),Candidate(state.adapter.route(b),f,1),
                     state,SimpleNamespace(remaining=100))
    assert traces==source_trace[2:]
    np.testing.assert_array_equal(state.adapter.path(actual.route),expected[0])
    np.testing.assert_array_equal(a,[[2.,8.],[10.,8.],[18.,8.],[28.,8.]])


def test_neutral_tournament_matches_original_private_rng_draws():
    import random
    from algorithms.common.nsga2 import Individual
    from algorithms.routing.pilot_reference.population import tournament_index
    state=state_for();population=[Individual(np.empty((0,2)),np.ones(4),cv,rank,crowd)
        for cv,rank,crowd in [(0,0,float('inf')),(0,0,1.),(1.,2,0.),(1.,2,0.)]]
    rng=random.Random(state.config.seed)
    bindings={'random':rng,'_is_pinsga2_official_profile':lambda *a:False,
              '_is_search_guidance_disabled_profile':lambda *a:False}
    original=original_functions('population.py',['_tournament_better_index','_binary_tournament_select'],bindings)
    context={'F':np.ones((4,4)),'feasible':np.array([p.violation<=0 for p in population]),
             'cv':np.array([p.violation for p in population]),'rank':np.array([p.rank for p in population]),
             'crowding':np.array([p.crowding for p in population]),'pref_scores':np.zeros(4),'has_guidance':False}
    assert [tournament_index(population,state) for _ in range(30)]==[original['_binary_tournament_select'](context) for _ in range(30)]
    assert rng.getstate()==state.adapter.python_rng.getstate()


def test_parent_index_reselection_is_bounded_even_with_identical_inputs(monkeypatch):
    import algorithms.routing.pilot_reference.population as module
    state=state_for();state.config=replace(state.config,pilot=replace(state.config.pilot,enabled_mechanisms=['distinct_parents']))
    calls=[]
    monkeypatch.setattr(module,'tournament_index',lambda *args:(calls.append(0) or 0))
    assert module.parent_pair([object(),object()],state)==(0,0)
    assert len(calls)==2+state.core.parent_retries


@pytest.mark.parametrize('probability',[0.,1.])
def test_independent_cpu_crossover_loop_spends_budget_when_returning_parents(probability):
    from algorithms.routing.search import routing_search
    base=load_default_config().routing
    cfg=replace(base,evolution_backend='numpy',evaluation_backend='compiled_cpu',devices=['cpu'],search_strategy='pilot_reference',
                popsize=4,max_generations=2, max_evaluations=57,reference_count=2,
                pilot=replace(base.pilot,enabled_mechanisms=['nearby_crossover','distinct_parents'],
                              core=replace(base.pilot.core,crossover_probability=probability)))
    result=routing_search(make_problem(),cfg)
    stats=result.execution['pilot_initialization']
    assert result.generation_count==cfg.max_generations and result.stop_reason=="generation_limit"
    assert stats['offspring_submitted']>0 and stats['parent_pairs']>0
    if probability==0:assert stats.get('crossover_calls',0)==0


def test_offspring_reuses_a_parent_rechecked_inside_the_same_operator_call(monkeypatch):
    import algorithms.routing.pilot_reference.variation as module
    from algorithms.routing.ranges import TowerRange
    state=state_for()
    state.config=replace(state.config,pilot=replace(state.config.pilot,enabled_mechanisms=['nearby_crossover'],
        core=replace(state.core,crossover_probability=1.)))
    window=state.budget.window('offspring',100)
    first=state.score(Route(np.empty((0,2))),window)
    second=state.score(Route(np.empty((0,2))),window)
    def crossed(a,b,s,w):
        s.score(a.route,w)
        return a
    monkeypatch.setattr(module,'crossover',crossed)
    monkeypatch.setattr(module,'encode_candidate',lambda *args:first.route)
    before=len(state.budget.records)
    result=module.offspring(first,second,TowerRange(0,1,1),state,window)
    assert len(state.budget.records)==before+1
    assert result.evaluation_index==before


def test_reference_rrt_and_migrated_operators_share_one_run_stream(monkeypatch):
    import algorithms.routing.pilot_reference.rrt as module
    from algorithms.routing.pilot_reference.driver import initialize
    captured=[]
    def append(initial,adapter,*args,**kwargs):
        captured.append(adapter)
        adapter.python_rng.random()
        return {'rrt_attempts':1}
    monkeypatch.setattr(module,'append_rrt_seeds',append)
    state=state_for()
    cfg=replace(state.config,popsize=4,max_generations=2, max_evaluations=64,reference_count=2,
        pilot=replace(state.config.pilot,initialization_mode='legacy',enabled_mechanisms=['rrt','nearby_crossover']))
    initial=initialize(state.evaluator,cfg,np.random.default_rng(cfg.seed),state.budget,lambda *args:None)
    assert captured==[initial.run_state.adapter]


@pytest.mark.parametrize('improve',[False,True])
def test_multitrial_mutation_matches_original_proposals_and_rng_states(improve):
    import random
    from algorithms.routing.pilot_reference.mutation import mutate
    path=np.array([[2.,8.],[10.,8.],[18.,8.],[28.,8.]])
    source_trace=[];source_py=random.Random(123);source_np=np.random.RandomState(123)
    class NumpyProxy:
        random=source_np
        def __getattr__(self,name):return getattr(np,name)
    def metrics(points,grid):
        source_trace.append(np.asarray(points).copy())
        return ([0.]*4 if improve and len(source_trace)==2 else [1.]*4),[0.]
    bindings=original_functions('preference.py',['_candidate_is_better'],{
        'PreferenceGuidance':object,'_utility_model_scores':lambda *a,**k:None})
    bindings.update(np=NumpyProxy(),random=source_py,PATH_MUTATION_TRIES=12,PreferenceGuidance=object,
        compute_path_metrics=metrics,_adaptive_neighborhood_radius=lambda *args:6.,
        _project_to_valid_cell=lambda p,*args,**kwargs:p,_edge_is_collision_free=lambda *args:True,
        _path_is_collision_free=lambda *args:True,_dedup_consecutive_points=lambda p:p)
    original=original_functions('path_operators.py',['_path_mutation_operator'],bindings)['_path_mutation_operator']
    expected=original(path,None)
    problem=make_problem();problem=replace(problem,constraints=replace(problem.constraints,max_span_m=40.))
    state=state_for(problem)
    state.neighborhood_radius=lambda *a:6.;state.project=lambda p,*a,**k:p
    state.evaluator.span_allowed=lambda *a:True;state.valid_path=lambda p:True
    traces=[]
    def score(route,window):
        traces.append(state.adapter.path(route).copy())
        return Candidate(route,SimpleNamespace(objectives=np.array([0.]*4 if improve and len(traces)==1 else [1.]*4),
                                              is_feasible=True,violation=0.),len(traces))
    state.score=score
    first=Candidate(state.adapter.route(path),SimpleNamespace(objectives=np.ones(4),is_feasible=True,violation=0.),0)
    actual=mutate(first,state,SimpleNamespace(remaining=100))
    assert len(traces)==state.core.mutation_tries
    for a,b in zip(traces,source_trace[1:]):np.testing.assert_array_equal(a,b)
    np.testing.assert_array_equal(state.adapter.path(actual.route),expected[0])
    assert source_py.getstate()==state.adapter.python_rng.getstate()
    np.testing.assert_array_equal(source_np.get_state()[1],state.adapter.numpy_rng.get_state()[1])
    assert source_np.get_state()[2:]==state.adapter.numpy_rng.get_state()[2:]


def test_crossover_and_mutation_are_independent_in_the_same_offspring(monkeypatch):
    import algorithms.routing.pilot_reference.variation as module
    import algorithms.routing.pilot_reference.mutation as mutations
    from algorithms.routing.ranges import TowerRange
    state=state_for();state.config=replace(state.config,pilot=replace(state.config.pilot,
        enabled_mechanisms=['nearby_crossover','path_mutation'],core=replace(state.core,
        crossover_probability=1.,mutation_probability=1.)))
    window=state.budget.window('offspring',100)
    first=state.score(Route(np.empty((0,2))),window);events=[]
    monkeypatch.setattr(module,'crossover',lambda a,b,*args:(events.append('cross') or a))
    monkeypatch.setattr(mutations,'mutate',lambda a,*args:(events.append('mutate') or a))
    monkeypatch.setattr(module,'encode_candidate',lambda *args:first.route)
    module.offspring(first,first,TowerRange(0,1,1),state,window)
    assert events==['cross','mutate']


def test_mutation_respects_a_one_trial_window_without_touching_parent():
    from algorithms.routing.pilot_reference.mutation import mutate
    state=state_for();path=np.array([[2.,8.],[14.,12.],[28.,8.]])
    parent=state.score(state.adapter.route(path),state.budget.window('initialization',1))
    state.project=lambda p,*a,**k:p;state.valid_path=lambda p:True;state.evaluator.span_allowed=lambda *a:True
    window=state.budget.window('offspring',1)
    result=mutate(parent,state,window)
    assert window.used==1
    np.testing.assert_array_equal(state.adapter.path(parent.route),path)
    assert result.evaluation_index<len(state.budget.records)


def test_projection_bias_is_a_bounded_geometry_parameter():
    cfg=load_default_config().routing.pilot.core
    assert replace(cfg,mutation_clearance_bias=0.).mutation_clearance_bias==0.
    with pytest.raises(ValueError):replace(cfg,mutation_clearance_bias=2.)


@pytest.mark.parametrize('name,original_name,exhaustive',[
    ('shorten','_shorten_path_operator',None),('smooth','_smoothness_path_operator',None),
    ('vns','_adaptive_vns_local_search_operator',False),('vns','_adaptive_vns_local_search_operator',True)])
def test_refinement_control_and_rng_match_original(name,original_name,exhaustive):
    import random
    import algorithms.routing.pilot_reference.refinement as module
    problem=make_problem();problem=replace(problem,constraints=replace(problem.constraints,max_span_m=40.))
    state=state_for(problem);path=np.array([[2.,8.],[8.,12.],[18.,11.],[28.,8.]])
    source_trace=[];source_py=random.Random(123);source_np=np.random.RandomState(123)
    evaluator=RouteEvaluator(problem)
    def evaluate(points):return evaluator.evaluate(state.adapter.route(np.asarray(points,dtype=float)))
    def metrics(points,grid):
        source_trace.append(np.asarray(points).copy());checked=evaluate(points)
        return checked.objectives,[checked.violation]
    neutral=original_functions('preference.py',['_candidate_is_better'],{
        'PreferenceGuidance':object,'_utility_model_scores':lambda *a,**k:None})['_candidate_is_better']
    def compare(*args,**kwargs):
        if kwargs.get('target_idx')==3:kwargs['target_idx']=2
        return neutral(*args,**kwargs)
    class NumpyProxy:
        random=source_np
        def __getattr__(self,name):return getattr(np,name)
    bindings=dict(np=NumpyProxy(),random=source_py,PreferenceGuidance=object,compute_path_metrics=metrics,
        _candidate_is_better=compare,_adaptive_neighborhood_radius=lambda *a:6.,
        _project_to_valid_cell=lambda p,*a,**k:p,_edge_is_collision_free=lambda *a:True,
        _path_is_collision_free=lambda *a:True,_dedup_consecutive_points=lambda p:p)
    original=original_functions('path_operators.py',[original_name],bindings)[original_name]
    kwargs={} if exhaustive is None else {'exhaustive':exhaustive}
    expected=original(path,None,**kwargs)
    state.project=lambda p,*a,**k:p;state.valid_path=lambda p:True
    state.evaluator.span_allowed=lambda *a:True;state.neighborhood_radius=lambda *a:6.
    traces=[]
    def score(route,window):
        points=state.adapter.path(route);traces.append(points.copy())
        return Candidate(route,evaluate(points),len(traces))
    state.score=score
    first=Candidate(state.adapter.route(path),evaluate(path),0)
    actual=getattr(module,name)(first,state,SimpleNamespace(remaining=100),**kwargs)
    assert len(traces)==len(source_trace)-1
    for a,b in zip(traces,source_trace[1:]):np.testing.assert_array_equal(a,b)
    np.testing.assert_array_equal(state.adapter.path(actual.route),expected[0])
    assert source_py.getstate()==state.adapter.python_rng.getstate()
    np.testing.assert_array_equal(source_np.get_state()[1],state.adapter.numpy_rng.get_state()[1])
    assert source_np.get_state()[2:]==state.adapter.numpy_rng.get_state()[2:]


@pytest.mark.parametrize('count',[0,1])
def test_refinement_handles_short_paths_and_exhausted_windows(count):
    from algorithms.routing.pilot_reference.refinement import shorten,smooth,vns
    state=state_for();path=np.vstack([state.problem.start,*([np.array([14.,8.])] if count else []),state.problem.end])
    parent=state.score(state.adapter.route(path),state.budget.window('initialization',1))
    empty=state.budget.window('local_search',0)
    for operation in [shorten,smooth,vns]:assert operation(parent,state,empty) is parent


def test_vns_effort_uses_reference_units_not_meter_radius(monkeypatch):
    from algorithms.routing.pilot_reference.refinement import vns
    state=state_for();state.adapter.problem=replace(state.problem,constraints=replace(state.problem.constraints,
        max_span_m=5*state.core.reference_max_step))
    path=np.array([[2.,8.],[14.,12.],[28.,8.]])
    parent=state.score(state.adapter.route(path),state.budget.window('initialization',1))
    state.neighborhood_radius=lambda *a:5*6.;state.project=lambda p,*a,**k:p
    state.evaluator.span_allowed=lambda *a:False
    vns(parent,state,state.budget.window('local_search',100),exhaustive=True)
    assert state.diagnostics['vns_draws']==6


@pytest.mark.parametrize('blocked',[False,True])
def test_same_cell_astar_records_result_and_cache_without_aliasing(blocked):
    from algorithms.routing.pilot_reference.astar import metric_astar
    state=state_for(make_problem(no_cross_zones=[[[14,0],[18,0],[18,32],[14,32]]] if blocked else []))
    first=metric_astar(state,64)
    second=metric_astar(state,64)
    assert state.diagnostics['astar_attempts']==1 and state.diagnostics['astar_cache_hits']==1
    assert state.diagnostics['astar_failures' if blocked else 'astar_successes']==1
    if blocked:assert first is second is None
    else:
        np.testing.assert_array_equal(first,second)
        first[0]=0
        assert not np.array_equal(first,second)
