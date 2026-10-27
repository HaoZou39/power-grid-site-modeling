from copy import deepcopy

import pytest

from experiments.validate_routing_refactor import compare_snapshots


def snapshot():
    return {"kind": "routing_refactor_synthetic", "schema": {"version": 1}, "cases": {
        "cpu": {"evaluations": [{"xy": "coordinates", "source": "initialization"}],
                "selection": ["parent"], "random_states": ["stream"], "bounds": [0, 1, 2]}}}


def test_refactor_comparison_checks_complete_candidate_and_execution_contract():
    before = snapshot()
    assert compare_snapshots(before, deepcopy(before)) == {"matched": True, "cases": 1, "complete_evaluations": 1}
    for field in ["evaluations", "selection", "random_states", "bounds"]:
        after = deepcopy(before);after["cases"]["cpu"][field] = []
        with pytest.raises(AssertionError, match=field):
            compare_snapshots(before, after)
    after = deepcopy(before);after["schema"] = {}
    with pytest.raises(AssertionError, match="schema"):
        compare_snapshots(before, after)


def test_phase_windows_share_one_limit_and_offer_readonly_history():
    from algorithms.routing.evaluation_budget import EvaluationBudget

    class Evaluator:
        def evaluate_many(self, routes, *, details):
            return [item * 2 for item in routes]

    ledger = EvaluationBudget(Evaluator(), 3, 0., clock=lambda: 1.)
    seeds, evolution = ledger.window("initialization", 2), ledger.window("offspring", 3)
    assert seeds.evaluate_many([1, 2, 3]) == [2, 4]
    assert seeds.remaining == 0
    assert evolution.remaining == 1
    history = seeds.history
    assert isinstance(history, tuple)
    assert evolution.evaluate(4) == 8
    assert evolution.evaluate(5) is None
    assert history == ((1, 2), (2, 4))
    assert ledger.history == ((1, 2), (2, 4), (4, 8))
    assert ledger.counts == {"initialization": 2, "offspring": 1}
