from dataclasses import replace
from types import SimpleNamespace
import numpy as np
from algorithms.common.nsga2 import Individual
from algorithms.routing.pilot_reference.global_search import update_survival, inject_population
from algorithms.routing.pilot_reference.population import survivors, individual
from algorithms.routing.ranges import TowerRange
from modeling.routing.types import Route
from test_pilot_components import state_for
from pilot_reference import original_functions


def test_survival_counts_match_original_and_reset_disappeared_routes():
    a=Individual(np.array([[1.,2.]]),np.zeros(4),0.);b=Individual(np.array([[1.+1e-10,2.]]),np.zeros(4),0.)
    original=original_functions('population.py',['_update_stagnation_counts'],{'_row_signature':lambda row:row.tobytes()})['_update_stagnation_counts']
    rows=np.array([a.genes.ravel(),a.genes.ravel(),b.genes.ravel()]);previous={a.genes.tobytes():3}
    assert update_survival([a,a,b],previous)==original(rows,previous)
    assert update_survival([b],previous)=={b.genes.tobytes():1}
    assert update_survival([a],update_survival([b],previous))=={a.genes.tobytes():1}


def test_exact_dedup_and_source_rollback_preserve_population_size():
    state=state_for();state.config=replace(state.config,pilot=replace(state.config.pilot,enabled_mechanisms=['population_dedup']))
    a=Individual(np.array([[1.,2.]]),np.ones(4),0.)
    b=Individual(np.array([[1.+1e-10,2.]]),np.ones(4)*2,0.)
    c=Individual(np.array([[2.,2.]]),np.ones(4)*3,0.)
    assert len(survivors([a,a,b,c],3,state))==3
    assert state.diagnostics['population_duplicates_removed']==1
    assert len(survivors([a,a,b],3,state))==3
    assert state.diagnostics['population_dedup_rollbacks']==1


def test_global_injection_occurs_before_stagnation_and_protects_front(monkeypatch):
    import algorithms.routing.pilot_reference.global_search as module
    state=state_for(limit=100)
    state.config=replace(state.config,popsize=4)
    parents=[state.score(Route(np.array([[i+4.,8.]])),state.budget.window('initialization',1)) for i in range(4)]
    population=[individual(c) for c in parents]
    for i,p in enumerate(population):p.objectives=np.ones(4)*i;p.violation=0.
    state.stagnation=update_survival(population,{})
    captured=[]
    def build(s,b,w,target,**kwargs):
        captured.append(kwargs)
        return [s.score(Route(np.array([[21.,8.]])),w)]*target
    monkeypatch.setattr(module,'build_population',build)
    monkeypatch.setattr(module,'offspring',lambda a,b,bounds,s,w:s.score(Route(np.array([[22.,8.]])),w))
    merged=[]
    monkeypatch.setattr(module,'survivors',lambda rows,*args:(merged.extend(rows) or rows[:4]))
    bounds=TowerRange(0,4,4)
    inject_population(population,bounds,state)
    assert state.diagnostics['global_calls']==1
    assert state.diagnostics['global_stagnant_removed']==0
    assert captured[0]['include_astar'] is False and captured[0]['anchor_for_fill'] is True
    assert all(any(p is q for q in merged) for p in population)
    state.stagnation={p.genes.tobytes():state.core.stagnation_limit for p in population}
    merged.clear();inject_population(population,bounds,state)
    assert merged[0] is population[0]
    assert state.diagnostics['global_stagnant_removed']==2
    assert bounds.upper==4
    assert state.diagnostics['global_evaluations']<=2*state.config.pilot.global_budget_factor*4


def test_global_noop_without_dominated_or_remaining_budget(monkeypatch):
    state=state_for(limit=4)
    population=[Individual(np.array([[i,2.]]),np.array([i,4-i,0,0]),0.) for i in range(4)]
    assert inject_population(population,TowerRange(0,4,4),state) is population
    assert state.diagnostics.get('global_calls',0)==0


def test_full_loop_uses_separate_global_phase_and_keeps_initial_sources():
    from algorithms.routing.search import routing_search
    from test_routing_context import make_problem
    state=state_for();cfg=replace(state.config,popsize=4,max_evaluations=200,reference_count=2,
        pilot=replace(state.config.pilot,initialization_mode='hybrid',
            enabled_mechanisms=['astar','rrt','global_injection','population_dedup']))
    problem=make_problem();problem=replace(problem,constraints=replace(problem.constraints,max_span_m=12.))
    result=routing_search(problem,cfg)
    stats=result.execution['pilot_initialization']
    assert result.evaluation_count==200
    assert stats.get('global_calls',0)>0
    assert sum(stats['initial_sources'].values())==4
    assert sum(stats['global_sources'].values())>0
    assert result.execution['phase_evaluations']['global_search']>0


def test_duplicate_representatives_match_frozen_neutral_rules():
    from algorithms.routing.pilot_reference.population import deduplicate
    state=state_for()
    x=np.array([[1.,2.],[1.,2.],[2.,3.],[2.,3.],[4.,5.]])
    f=np.arange(20,dtype=float).reshape(5,4)
    g=np.array([[2.],[1.],[0.],[0.],[0.]])
    original=original_functions('population.py',['_prefer_population_index','_deduplicate_population_rows'],{
        'PreferenceGuidance':object,'_constraint_violation':lambda a:np.maximum(a,0).sum(1),
        '_is_pinsga2_official_profile':lambda *a:False,'_is_search_guidance_disabled_profile':lambda *a:True,
        '_row_signature':lambda row:row.tobytes()})['_deduplicate_population_rows']
    expected=original(x,f,g)
    actual=deduplicate([Individual(row.reshape(1,2),v,float(cv[0])) for row,v,cv in zip(x,f,g)],state)
    np.testing.assert_array_equal([p.genes.ravel() for p in actual],expected[0])
    np.testing.assert_array_equal([p.objectives for p in actual],expected[1])


def test_global_parent_draws_and_phase_order_match_frozen_function(monkeypatch):
    import algorithms.routing.pilot_reference.global_search as module
    state=state_for(limit=64);state.config=replace(state.config,popsize=4)
    candidates=[state.score(Route(np.array([[i+4.,8.]])),state.budget.window('initialization',1)) for i in range(4)]
    population=[individual(c) for c in candidates];source_events=[];events=[]
    rng=np.random.RandomState(state.config.seed)
    class NumpyProxy:
        random=rng
        def __getattr__(self,name):return getattr(np,name)
    def source_build(*args,**kwargs):
        source_events.append('random');assert kwargs['include_astar'] is False
        return np.array([[10.]])
    def source_offspring(a,b,*args,**kwargs):
        source_events.append(('parents',int(a[0]),int(b[0])));return np.array([20.])
    def source_select(x,f,g,**kwargs):
        source_events.append('select');return x[:4],f[:4],g[:4],None
    original=original_functions('population.py',['_apply_hybrid_global_search_population'],{
        'np':NumpyProxy(),'PreferenceGuidance':object,'_is_pinsga2_official_strict_profile':lambda *a:False,
        '_compute_population_state':lambda *a,**k:{'nd_idx':np.array([0,1]),'feasible':np.ones(4,dtype=bool)},
        'INSGA_GLOBAL_SEARCH_FRACTION':state.core.global_fraction,'INSGA_STAGNATION_LIMIT':state.core.stagnation_limit,
        '_row_signature':lambda row:row.tobytes(),'_build_astar_rrt_population':source_build,
        '_generate_insga_offspring_row':source_offspring,
        '_evaluate_population_with_decoder':lambda x,*a:(np.zeros((len(x),4)),np.zeros((len(x),1))),
        '_select_population_environment':source_select})['_apply_hybrid_global_search_population']
    original(np.arange(4.).reshape(4,1),np.zeros((4,4)),np.zeros((4,1)),(0,0),(1,1),None,4,{})
    monkeypatch.setattr(module,'feasible_front',lambda *a:[0,1])
    def build(*args,**kwargs):events.append('random');return [candidates[0]]
    def offspring(a,b,*args,**kwargs):
        events.append(('parents',int(a.route.towers[0,0]-4),int(b.route.towers[0,0]-4)));return a
    def select(rows,*args):events.append('select');return rows[:4]
    monkeypatch.setattr(module,'build_population',build);monkeypatch.setattr(module,'offspring',offspring)
    monkeypatch.setattr(module,'survivors',select)
    inject_population(population,TowerRange(0,4,4),state)
    assert events==source_events
    np.testing.assert_array_equal(rng.get_state()[1],state.adapter.numpy_rng.get_state()[1])
    assert rng.get_state()[2:]==state.adapter.numpy_rng.get_state()[2:]
