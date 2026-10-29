from dataclasses import replace
from types import SimpleNamespace
import math
import numpy as np
import pytest
from algorithms.common.nsga2 import Individual, nondominated_sort
from algorithms.routing.pilot_reference.local_search import elite_indices, local_due, refine_population
from algorithms.routing.pilot_reference.population import individual
from modeling.routing.types import Route
from test_pilot_components import state_for
from pilot_reference import original_functions


def population_for_test():
    return [Individual(np.array([[i+3.,8.]]),np.array([i,10-i,i,10-i],dtype=float),0.) for i in range(8)]


def test_elite_order_matches_frozen_population_state():
    population=population_for_test();core=state_for().core
    def fronts(values,**kwargs):
        return [np.array(f) for f in nondominated_sort([Individual(np.empty((0,2)),v,0.) for v in values])]
    def crowd(values):
        rows=[Individual(np.empty((0,2)),v,0.) for v in values];nondominated_sort(rows)
        return np.array([x.crowding for x in rows])
    source=original_functions('population.py',['_compute_population_state'],{
        'PreferenceGuidance':object,'_constraint_violation':lambda g:np.maximum(g,0).sum(axis=1),
        '_is_pinsga2_official_profile':lambda *a:False,'_is_search_guidance_disabled_profile':lambda *a:True,
        '_is_utility_scalarized_profile':lambda *a:False,'_profile_fronts':fronts,'_crowding_distance_like':crowd})['_compute_population_state']
    original=source([p.objectives for p in population],np.zeros((8,1)))
    boundary=original['boundary_idx'].tolist();sparse=original['sparse_idx'].tolist()
    expected=(boundary+sparse)[:max(4,math.ceil(.2*len(population)))]
    indices,exhaustive=elite_indices(population,core,len(population))
    assert indices==expected and exhaustive==set(boundary+sparse)
    assert [g for g in range(1,11) if local_due(g,core)]==[1,4,7,10]
    for p in population:p.violation=1.
    assert elite_indices(population,core,len(population))==([],set())


def test_local_phase_divides_allowance_and_rechecks_encoded_candidate(monkeypatch):
    import algorithms.routing.pilot_reference.local_search as module
    from algorithms.routing.ranges import TowerRange
    state=state_for(limit=64)
    state.config=replace(state.config,popsize=4,pilot=replace(state.config.pilot,local_budget_factor=2))
    candidates=[state.score(Route(np.array([[i+4.,8.]])),state.budget.window('initialization',1)) for i in range(4)]
    population=[individual(c) for c in candidates];quotas=[];selected=[]
    monkeypatch.setattr(module,'elite_indices',lambda *a:([0,1,2,3],{0,1,2,3}))
    def vns(current,s,window,**kwargs):
        quotas.append(window.limit)
        while window.remaining:s.score(current.route,window)
        return current
    monkeypatch.setattr(module,'vns',vns)
    assert refine_population(population,TowerRange(0,4,4),state) is population
    assert len(quotas)==4 and max(quotas)-min(quotas)<=1
    assert state.diagnostics['local_refined_elites']==4
    assert state.diagnostics['local_evaluations']<=8
    # A raw improvement is insufficient when encoding loses the improvement.
    state.better=lambda a,b: b is not a
    monkeypatch.setattr(module,'vns',lambda current,s,w,**k:SimpleNamespace(route=current.route))
    monkeypatch.setattr(module,'encode_candidate',lambda *a:Route(np.array([[20.,20.]])))
    state.better=lambda a,b:isinstance(b,SimpleNamespace)
    refine_population(population,TowerRange(0,4,4),state)
    assert state.diagnostics['local_raw_accepts']==4
    assert state.diagnostics.get('local_encoded_accepts',0)==0


def test_periodic_local_search_is_integrated_and_total_budget_is_exact():
    from algorithms.routing.search import routing_search
    from test_routing_context import make_problem
    state=state_for();cfg=replace(state.config,popsize=4,max_generations=3, max_evaluations=160,reference_count=2,
        pilot=replace(state.config.pilot,enabled_mechanisms=['elite_local_search']))
    problem=make_problem();problem=replace(problem,constraints=replace(problem.constraints,max_span_m=12.))
    result=routing_search(problem,cfg)
    stats=result.execution['pilot_initialization']
    assert result.generation_count==cfg.max_generations
    assert stats['local_calls']>0 and stats['vns_draws']>0
    assert stats['local_evaluations']>0
    assert all((g-1)%cfg.pilot.core.local_search_interval==0 for g in stats['local_generations'])


def test_elite_limit_uses_configured_population_size_for_partial_initial_pool():
    population=[Individual(np.array([[i+3.,8.]]),np.array([i,21-i,i,21-i],dtype=float),0.) for i in range(21)]
    core=state_for().core
    assert len(elite_indices(population,core,64)[0])==8
    assert len(elite_indices(population,core,21)[0])==5
