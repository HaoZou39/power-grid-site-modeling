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
