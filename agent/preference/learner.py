"""Numerical preference learner with an SLFN-compatible backend."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

import numpy as np

from agent.preference.models import Candidate, PreferenceChoice
from agent.preference.objectives import ObjectiveEnvelope


class PreferenceLearner:
    """Learn a lower-is-better utility from discrete choices.

    The SLFN implementation is vendored under ``agent.preference.slfn`` and
    receives raw objective vectors plus the fixed envelope.
    """

    def __init__(self, envelope: ObjectiveEnvelope, *, seed: int = 42, backend: Any | None = None) -> None:
        self.envelope = envelope
        self.seed = int(seed)
        if backend is None:
            from agent.preference.slfn import FCPEUtilityLearner

            backend = FCPEUtilityLearner(
                n_obj=len(envelope.specs),
                n_hidden=16,
                rng_seed=seed,
                interaction_loss="pairwise_expand",
            )
        self.backend = backend
        self._history: list[PreferenceChoice] = []
        self._weights = np.ones(len(envelope.specs), dtype=float) / len(envelope.specs)
        self._fitted = False

    @property
    def history_count(self) -> int:
        return len(self._history)

    @property
    def confidence(self) -> str:
        if self.history_count >= 5 and self._fitted:
            return "medium"
        return "low"

    def fit(self, history: Sequence[PreferenceChoice]) -> "PreferenceLearner":
        self._history = list(history)
        self._fit_linear_weights()
        if self.backend is not None and self._history:
            self._fit_backend()
        self._fitted = bool(self._history)
        return self

    def update(self, choice: PreferenceChoice) -> "PreferenceLearner":
        return self.fit([*self._history, choice])

    def score_batch(self, candidates: Sequence[Candidate]) -> np.ndarray:
        normalized = self.envelope.normalize(candidates)
        if normalized.size == 0:
            return np.empty(0, dtype=float)
        if self.backend is not None and self._fitted:
            score_batch = getattr(self.backend, "score_batch", None)
            if callable(score_batch):
                return np.asarray(score_batch(normalized), dtype=float).reshape(-1)
        return normalized @ self._weights

    def score(self, candidate: Candidate) -> float:
        return float(self.score_batch([candidate])[0])

    def export_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "envelope": self.envelope.to_dict(),
            "weights": self._weights.tolist(),
            "history_count": self.history_count,
            "confidence": self.confidence,
            "fitted": self._fitted,
        }

    def load_state(self, state: Mapping[str, Any]) -> "PreferenceLearner":
        weights = np.asarray(state.get("weights", []), dtype=float)
        if weights.shape != (len(self.envelope.specs),) or not np.isfinite(weights).all():
            raise ValueError("preference model weights do not match objective dimension")
        if float(weights.sum()) <= 0:
            raise ValueError("preference model weights must have positive sum")
        self._weights = weights / weights.sum()
        self._fitted = bool(state.get("fitted", False))
        return self

    def _fit_linear_weights(self) -> None:
        totals = np.zeros(len(self.envelope.specs), dtype=float)
        observations = 0
        for choice in self._history:
            chosen = next(candidate for candidate in choice.candidates if candidate.candidate_id == choice.chosen_id)
            chosen_vector = self.envelope.normalize([chosen])[0]
            rejected = [candidate for candidate in choice.candidates if candidate.candidate_id != choice.chosen_id]
            if not rejected:
                continue
            rejected_vector = self.envelope.normalize(rejected).mean(axis=0)
            totals += np.maximum(rejected_vector - chosen_vector, 0.0)
            observations += 1
        if observations and totals.sum() > 1e-12:
            self._weights = totals / totals.sum()

    def _fit_backend(self) -> None:
        # The SLFN receives normalized all-minimization features. Objective
        # directions and fixed bounds are applied by ObjectiveEnvelope.
        rounds = []
        choices = []
        for choice in self._history:
            rounds.append(
                np.asarray(
                    [candidate.vector(self.envelope.specs) for candidate in choice.candidates],
                    dtype=float,
                )
            )
            choices.append(next(index for index, candidate in enumerate(choice.candidates) if candidate.candidate_id == choice.chosen_id))
        update = getattr(self.backend, "update", None)
        if callable(update):
            update(rounds, choices, round_idx=max(0, len(rounds) - 1))
