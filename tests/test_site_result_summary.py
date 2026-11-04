import json

from plugins.site_plugin import site_result_summary


def test_site_result_summary_copies_existing_counts(tmp_path) -> None:
    (tmp_path / "run_summary.json").write_text(json.dumps({
        "n_solutions": 12,
        "n_feasible": 0,
        "n_pareto": 0,
        "no_feasible_solution": True,
        "algorithm": "guided_search",
    }), encoding="utf-8")

    assert site_result_summary(tmp_path) == {
        "n_solutions": 12,
        "n_feasible": 0,
        "n_pareto": 0,
        "no_feasible_solution": True,
    }


def test_site_result_summary_omits_missing_or_inconsistent_files(tmp_path) -> None:
    assert site_result_summary(tmp_path) is None
    (tmp_path / "run_summary.json").write_text(json.dumps({
        "n_solutions": 4,
        "n_feasible": 2,
        "n_pareto": 1,
        "no_feasible_solution": True,
    }), encoding="utf-8")
    assert site_result_summary(tmp_path) is None
