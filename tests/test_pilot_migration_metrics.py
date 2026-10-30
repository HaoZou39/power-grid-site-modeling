import copy

import numpy as np
import pytest

from experiments.pilot_migration_metrics import migration_gate, shape_diversity


def gate(before, after, **kwargs):
    return migration_gate(before, after, quality_gain=.05, special_gain=.1,
        regression=.05, required_wins=4, seed_count=5, tolerance=1e-8, **kwargs)


def paired_cases(igd=.2, epsilon=.2, diversity=.1):
    return {name: {seed: {"feasible": True, "igd_plus": igd, "epsilon": epsilon,
                         "initial_shape_diversity": diversity} for seed in range(123, 128)}
            for name in ["cangnan", "nanxi-100", "nanxi-200"]}


def test_shape_diversity_has_an_independent_parallel_path_value():
    paths = [np.array([[0., y], [10., y]]) for y in [0., 2., 4.]]
    assert shape_diversity(paths[:2], 10., 64) == pytest.approx(.2)
    assert shape_diversity(paths, 10., 64) == pytest.approx(8 / 30)
    assert shape_diversity([paths[0]] * 3, 10., 64) == 0


def test_gate_requires_stable_gain_and_rejects_no_gain():
    original = paired_cases()
    assert not gate(original, copy.deepcopy(original))["passed"]
    candidate = paired_cases(.1, .1)
    assert gate(original, candidate)["passed"]
    candidate["nanxi-100"][123]["feasible"] = False
    assert not gate(original, candidate)["passed"]


def test_special_gain_never_hides_quality_regression():
    original = paired_cases()
    candidate = paired_cases(diversity=.2)
    assert gate(original, candidate, special_metric="initial_shape_diversity")["passed"]
    candidate["cangnan"] = paired_cases(.3)["cangnan"]
    assert not gate(original, candidate, special_metric="initial_shape_diversity")["passed"]


def test_single_lucky_seed_and_missing_pairs_cannot_pass():
    original = paired_cases()
    candidate = copy.deepcopy(original)
    candidate["cangnan"][123]["igd_plus"] = 0.
    assert not gate(original, candidate)["passed"]
    del candidate["cangnan"][124]
    with pytest.raises(ValueError, match="paired seeds"):
        gate(original, candidate)


def test_report_comparison_uses_saved_geometry_and_rejects_wrong_problem(tmp_path, monkeypatch):
    import json
    from experiments.benchmark_routing import benchmark
    from experiments.compare_pilot_migration import compare_migration
    from test_routing_output import routing_task
    task, _ = routing_task(tmp_path, monkeypatch)
    task_path = tmp_path / "problem.json"; task_path.write_text(task.model_dump_json())
    root = tmp_path / "trials"
    monkeypatch.setenv("SOURCE_REVISION", "test")
    benchmark({"tasks": [str(task_path)], "cases": [{"name": "base", "routing": {}}],
        "seeds": list(range(123, 128)), "warmups": 0, "repeats": 1, "time_checkpoints_s": []}, root)
    entry = {"report": str(root / "report.json"), "case": "base"}
    spec = {"tasks": {"problem": str(task_path)}, "baseline": {"problem": entry},
            "candidate": {"problem": entry}, "shape_samples": 64,
            "gate": dict(quality_gain=.05, special_gain=.1, regression=.05, required_wins=4,
                         seed_count=5, tolerance=1e-8, special_metric="initial_shape_diversity")}
    result = compare_migration(spec)
    assert not result["gate"]["passed"] and not result["gate"]["regressions"]
    assert result["baseline"] == result["candidate"]
    altered = json.loads((root / "report.json").read_text())
    altered["rows"][0]["problem"]["max_span_m"] += 1
    (root / "altered.json").write_text(json.dumps(altered))
    spec["candidate"]["problem"] = {"report": str(root / "altered.json"), "case": "base"}
    with pytest.raises(ValueError, match="engineering inputs"):
        compare_migration(spec)
