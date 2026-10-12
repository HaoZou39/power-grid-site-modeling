"""Application service joining history, learning, and Pareto recommendation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

from agent.preference.candidates import load_pareto_csv
from agent.preference.history import append_choice, history_path, load_choices, history_summary
from agent.preference.learner import PreferenceLearner
from agent.preference.models import Candidate, ObjectiveSpec, PreferenceChoice
from agent.preference.objectives import ObjectiveEnvelope
from agent.preference.recommender import recommend

MODEL_ENV = "AGENT_PREFERENCE_MODEL_PATH"


class PreferenceService:
    def __init__(self, *, history_file: Path | None = None, model_file: Path | None = None) -> None:
        self.history_file = history_file or history_path()
        configured = os.getenv(MODEL_ENV, "").strip()
        self.model_file = model_file or (Path(configured).expanduser() if configured else Path("memory") / "PREFERENCE_MODEL.json")

    def choices(self) -> list[PreferenceChoice]:
        return load_choices(self.history_file)

    def record_choice(self, choice: PreferenceChoice) -> dict[str, Any]:
        append_choice(self.history_file, choice)
        return history_summary(self.choices())

    def build_learner(self, candidates: Sequence[Candidate], specs: Sequence[ObjectiveSpec]) -> PreferenceLearner:
        learner = PreferenceLearner(ObjectiveEnvelope.from_candidates(candidates, specs))
        history = self.choices()
        if history:
            learner.fit(history)
        return learner

    def fit_model(self, candidates: Sequence[Candidate], specs: Sequence[ObjectiveSpec]) -> dict[str, Any]:
        learner = self.build_learner(candidates, specs)
        self.model_file.parent.mkdir(parents=True, exist_ok=True)
        self.model_file.write_text(json.dumps(learner.export_state(), ensure_ascii=False, indent=2), encoding="utf-8")
        return learner.export_state()

    def recommend_from_csv(
        self,
        csv_path: str | Path,
        specs: Sequence[ObjectiveSpec],
        *,
        top_k: int = 5,
    ) -> dict[str, Any]:
        candidates = load_pareto_csv(csv_path, [spec.name for spec in specs])
        learner = self.build_learner(candidates, specs)
        items = recommend(candidates, learner, top_k=top_k)
        return {
            "recommendations": [item.to_dict() for item in items],
            "model": learner.export_state(),
            "candidate_count": len(candidates),
            "history": history_summary(self.choices()),
        }

    def model_summary(self) -> dict[str, Any]:
        if not self.model_file.is_file():
            return {"fitted": False, "history": history_summary(self.choices())}
        try:
            return json.loads(self.model_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("preference model file is invalid") from exc
