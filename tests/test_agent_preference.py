from __future__ import annotations

import json

import numpy as np

from agent.preference.candidates import load_pareto_csv
from agent.preference.history import append_choice, load_choices
from agent.preference.learner import PreferenceLearner
from agent.preference.models import Candidate, ObjectiveSpec, PreferenceChoice
from agent.preference.objectives import ObjectiveEnvelope
from agent.preference.recommender import recommend


def _candidates() -> tuple[Candidate, ...]:
    return (
        Candidate("a", {"dem_soft": 1.0, "demand_distance": 10.0}, {"x": 1.0}),
        Candidate("b", {"dem_soft": 2.0, "demand_distance": 5.0}, {"x": 2.0}),
        Candidate("c", {"dem_soft": 3.0, "demand_distance": 1.0}, {"x": 3.0}),
    )


def test_history_round_trip(tmp_path):
    candidates = _candidates()
    choice = PreferenceChoice("scene-a", candidates, "b", reason="平衡两个目标")
    path = tmp_path / "choices.jsonl"
    append_choice(path, choice)
    loaded = load_choices(path)
    assert len(loaded) == 1
    assert loaded[0].chosen_id == "b"
    assert loaded[0].candidates[1].objectives["dem_soft"] == 2.0


def test_learner_scores_and_recommendation_are_bounded(tmp_path):
    candidates = _candidates()
    specs = (ObjectiveSpec("dem_soft"), ObjectiveSpec("demand_distance"))
    history = [PreferenceChoice("scene-a", candidates, "b")]
    learner = PreferenceLearner(ObjectiveEnvelope.from_candidates(candidates, specs), seed=7).fit(history)
    scores = learner.score_batch(candidates)
    results = recommend(candidates, learner, top_k=2)
    assert scores.shape == (3,)
    assert np.isfinite(scores).all()
    assert len(results) == 2
    assert len({item.candidate.candidate_id for item in results}) == 2
    assert json.loads(json.dumps(learner.export_state()))["fitted"] is True


def test_pareto_csv_adapter_filters_infeasible_rows(tmp_path):
    path = tmp_path / "pareto_solutions.csv"
    path.write_text(
        "id,dem_soft,demand_distance,is_feasible,x\n"
        "p1,1.0,4.0,true,10\n"
        "p2,2.0,3.0,false,20\n",
        encoding="utf-8",
    )
    candidates = load_pareto_csv(path, ["dem_soft", "demand_distance"])
    assert [candidate.candidate_id for candidate in candidates] == ["p1"]
    assert candidates[0].variables["x"] == 10.0


def test_pareto_csv_adapter_uses_run_id_when_present(tmp_path):
    path = tmp_path / "pareto_solutions.csv"
    path.write_text(
        "run_id,dem_soft,demand_distance,is_feasible\n"
        "42,1.0,4.0,true\n",
        encoding="utf-8",
    )
    candidates = load_pareto_csv(path, ["dem_soft", "demand_distance"])
    assert candidates[0].candidate_id == "42"
