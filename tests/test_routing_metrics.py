import itertools

import numpy as np
import pytest

from algorithms.common.four_objective_front import four_objective_front
from experiments.routing_metrics import compare_front, reference_front
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import Route
from test_routing_context import make_problem


def test_front_metrics_have_independent_hand_calculated_values():
    reference = np.array([[0., 1.], [1., 0.]])
    actual = compare_front(np.array([[.5, .5]]), reference, np.zeros(2), np.ones(2))
    assert actual["igd_plus"] == .5 and actual["epsilon"] == .5 and actual["coverage"] == 0
    exact = compare_front(reference, reference, np.zeros(2), np.ones(2))
    assert exact["igd_plus"] == exact["epsilon"] == 0 and exact["coverage"] == 1
    assert compare_front(np.empty((0, 2)), reference, np.zeros(2), np.ones(2))["status"] == "no_feasible_solution"


def test_small_discrete_routing_problem_matches_enumerated_front():
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[7:10, 14:17] = 2
    problem = make_problem(landuse=landuse)
    evaluator = RouteEvaluator(problem)
    candidates = [Route(np.empty((0, 2)))]
    lattice = [(8., 5.), (16., 5.), (24., 5.), (8., 12.), (16., 12.), (24., 12.)]
    for count in (1, 2):
        candidates.extend(Route(np.array(points)) for points in itertools.permutations(lattice, count))
    values = np.array([r.objectives for c in candidates if (r := evaluator.evaluate(c)).is_feasible])
    expected = np.array([not any(np.all(other <= row) and np.any(other < row) for other in values) for row in values])
    assert expected.sum() >= 2
    assert 0 in values[expected, 0] and np.any(values[expected, 0] > 0)
    np.testing.assert_array_equal(four_objective_front(values), expected)
    np.testing.assert_array_equal(reference_front([values]), np.unique(values[expected], axis=0))


def test_manifest_benchmark_freezes_reference_and_reproduces(tmp_path, monkeypatch):
    import json
    from experiments.benchmark_routing import benchmark
    from test_routing_output import routing_task
    task, _ = routing_task(tmp_path, monkeypatch)
    task_path = tmp_path / "task.json";task_path.write_text(task.model_dump_json())
    monkeypatch.setenv("SOURCE_REVISION", "unit-test")
    manifest = {"tasks": [str(task_path)], "seeds": [123], "warmups": 0, "repeats": 2,
        "time_checkpoints_s": [0, 60], "cases": [{"name": "reference", "routing": {}, "publish": True},
        {"name": "tensor", "routing": {"evolution_backend": "tensor", "evaluation_backend": "compiled_cpu"}}]}
    report = benchmark(manifest, tmp_path / "benchmark")
    assert len(report["rows"]) == 4
    assert all(r["reproduced"] is None for r in report["rows"] if r["repeat"] == 0)
    assert all(r["reproduced"] is True for r in report["rows"] if r["repeat"] > 0)
    assert report["source_hashes_unchanged"] and report["independent_snapshots"]
    assert all("publication" in row for row in report["rows"] if row["case"] == "reference")
    assert all(r["quality_at_search_seconds"]["0"]["status"] == "no_feasible_solution" for r in report["rows"])


def test_manifest_can_compare_two_problems_in_the_same_scene(tmp_path, monkeypatch):
    import json
    from experiments.benchmark_routing import benchmark
    from test_routing_output import routing_task
    task, _ = routing_task(tmp_path, monkeypatch)
    paths = []
    for index, span in enumerate([30., 13.]):
        path = tmp_path / f"problem-{index}.json"
        path.write_text(task.model_copy(update={"max_span_m": span}).model_dump_json())
        paths.append({"id": f"span-{index}", "config": str(path)})
    monkeypatch.setenv("SOURCE_REVISION", "test")
    report = benchmark({"tasks": paths, "cases": [{"name": "base", "routing": {}}],
        "seeds": [123], "warmups": 0, "repeats": 1, "time_checkpoints_s": []}, tmp_path / "matrix")
    assert {row["task_id"] for row in report["rows"]} == {"span-0", "span-1"}
    assert len({row["candidate_file"] for row in report["rows"]}) == 2
