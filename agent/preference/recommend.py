"""Rank the schemes on the map by the user's default weights and past choices.

Objectives are the ones this search compared (agent.analysis.compared_keys), all minimized.
Past choices are used only if every candidate in them has all of these objectives.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from agent.analysis import EDGE_SHARE, RANKED_OBJECTIVES, compared_keys, ranking_candidates
from agent.preference.slfn import SlfnConfig, SlfnUtility
from agent.preference.store import PreferenceChoice, PreferenceDefaults
from agent.workspace import WorkspaceSnapshot


@dataclass(frozen=True)
class PreferenceConfig:
    top_k: int = 5
    min_distance: float = 0.08  # Euclidean, in the normalized objective space; skips near-duplicates first
    slfn: SlfnConfig = field(default_factory=SlfnConfig)


def recommend_poses(
    snapshot: WorkspaceSnapshot,
    choices: list[PreferenceChoice],
    defaults: PreferenceDefaults | None,
    config: PreferenceConfig,
    top_k: int | None = None,
) -> dict[str, object]:
    poses = ranking_candidates(snapshot)
    keys = [key for key in compared_keys(snapshot) if all(key in pose.objectives for _, pose in poses)]
    if len(poses) < 2 or not keys:
        raise ValueError("地图上至少要有两个可行且带目标值的方案")
    prior = np.array([defaults.weights.get(key, 1.0) if defaults else 1.0 for key in keys])
    if prior.sum() <= 0:
        raise ValueError("本次比较的目标在「偏好」页里重要程度全是 0，请至少给一个目标大于 0")
    used = [choice for choice in choices if all(set(keys) <= c.objectives.keys() for c in choice.candidates)]

    current = np.array([[pose.objectives[key] for key in keys] for _, pose in poses])
    menus = [np.array([[c.objectives[key] for key in keys] for c in choice.candidates]) for choice in used]
    # One shared [0, 1] scale for history and current schemes, so training and scoring see the same space.
    every = np.vstack([current, *menus])
    low, span = every.min(axis=0), np.maximum(np.ptp(every, axis=0), 1e-9)

    def scale(rows: np.ndarray) -> np.ndarray:
        return (rows - low) / span

    model = SlfnUtility(prior, config.slfn)
    if used:
        chosen = [[c.id for c in choice.candidates].index(choice.chosen_id) for choice in used]
        model.fit([scale(menu) for menu in menus], chosen)
    normalized = scale(current)
    scores = model.score(normalized)
    weights = model.importance(normalized)

    picked = _diverse_top(normalized, scores, top_k or config.top_k, config.min_distance)
    return {
        "basis": "past_choices" if used else ("defaults" if defaults else "equal_weights"),
        "choices_used": len(used),
        "choices_skipped": len(choices) - len(used),
        "weights": [
            {"key": key, "label": RANKED_OBJECTIVES[key], "prior": round(float(p), 3), "weight": round(float(w), 3)}
            for key, p, w in zip(keys, prior / prior.sum(), weights)
        ],
        "recommendations": [
            {
                "rank": rank,
                "pose_id": poses[row][1].id,
                "index": poses[row][0] + 1,
                "score": round(float(scores[row]), 4),
                # Keyed by the card label, so the answer uses the words on the map.
                "objectives": {RANKED_OBJECTIVES[key]: poses[row][1].objectives[key] for key in keys},
                "strengths": _strengths(current, row, keys, weights),
                **_versus_first(current, row, picked[0], keys),
            }
            for rank, row in enumerate(picked, start=1)
        ],
    }


def _versus_first(current: np.ndarray, row: int, first: int, keys: list[str]) -> dict[str, dict[str, float]]:
    """Positive amounts by card label; all objectives are minimized, so smaller than rank 1 is better."""
    diff = current[row] - current[first]
    return {
        "better_than_first": {RANKED_OBJECTIVES[key]: round(float(-d), 3) for key, d in zip(keys, diff) if round(float(d), 3) < 0},
        "worse_than_first": {RANKED_OBJECTIVES[key]: round(float(d), 3) for key, d in zip(keys, diff) if round(float(d), 3) > 0},
    }


def _strengths(current: np.ndarray, row: int, keys: list[str], weights: np.ndarray) -> list[str]:
    """Labels of objectives where this scheme is in the best EDGE_SHARE of the map, heaviest weight first."""
    edge = max(1, round(EDGE_SHARE * len(current)))
    ranks = 1 + (current < current[row]).sum(axis=0)
    order = np.argsort(-weights, kind="stable")
    return [RANKED_OBJECTIVES[keys[i]] for i in order if ranks[i] <= edge]


def _diverse_top(normalized: np.ndarray, scores: np.ndarray, k: int, min_distance: float) -> list[int]:
    order = [int(i) for i in np.argsort(scores, kind="stable")]
    picked: list[int] = []
    for row in order:
        if len(picked) < k and all(np.linalg.norm(normalized[row] - normalized[p]) >= min_distance for p in picked):
            picked.append(row)
    picked += [row for row in order if row not in picked][: k - len(picked)]
    return picked
