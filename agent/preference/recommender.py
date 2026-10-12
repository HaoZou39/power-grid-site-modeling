"""Preference-aware, diverse recommendation of Pareto candidates."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from agent.preference.learner import PreferenceLearner
from agent.preference.models import Candidate, Recommendation


def recommend(
    candidates: Sequence[Candidate],
    learner: PreferenceLearner,
    *,
    top_k: int = 5,
    min_distance: float = 0.08,
) -> list[Recommendation]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if not candidates:
        return []
    scores = learner.score_batch(candidates)
    features = learner.envelope.normalize(candidates)
    ranked = sorted(range(len(candidates)), key=lambda index: (float(scores[index]), candidates[index].candidate_id))
    selected: list[int] = []
    distances: dict[int, float | None] = {}
    for index in ranked:
        if len(selected) >= min(top_k, len(candidates)):
            break
        distance = None if not selected else float(np.min(np.linalg.norm(features[index] - features[selected], axis=1)))
        if selected and distance is not None and distance < min_distance:
            continue
        selected.append(index)
        distances[index] = distance
    if len(selected) < min(top_k, len(candidates)):
        for index in ranked:
            if index not in selected:
                selected.append(index)
                distances[index] = float(np.min(np.linalg.norm(features[index] - features[selected[:-1]], axis=1))) if selected[:-1] else None
                if len(selected) >= min(top_k, len(candidates)):
                    break
    return [
        Recommendation(
            candidate=candidates[index],
            rank=rank,
            utility_score=float(scores[index]),
            diversity_distance=distances.get(index),
            reason="根据历史选择学习到的效用排序，并保留候选差异。",
        )
        for rank, index in enumerate(selected, start=1)
    ]
