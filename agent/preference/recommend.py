"""Rank the schemes on the map by what the user picked before.

Objectives are the ones this search compared (agent.analysis.compared_keys), all minimized.
Past choices are used only if every candidate in them has all of these objectives.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from agent.analysis import RANKED_OBJECTIVES, compared_keys
from agent.preference.history import PreferenceChoice
from agent.preference.slfn import SlfnConfig, SlfnUtility
from agent.workspace import WorkspaceSnapshot


@dataclass(frozen=True)
class PreferenceConfig:
    top_k: int = 5
    min_distance: float = 0.08  # Euclidean, in the normalized objective space; skips near-duplicates first
    slfn: SlfnConfig = field(default_factory=SlfnConfig)


def recommend_poses(
    snapshot: WorkspaceSnapshot,
    choices: list[PreferenceChoice],
    config: PreferenceConfig,
    top_k: int | None = None,
) -> dict[str, object]:
    poses = [(index, pose) for index, pose in enumerate(snapshot.poses) if pose.objectives]
    keys = [key for key in compared_keys(snapshot) if all(key in pose.objectives for _, pose in poses)]
    if len(poses) < 2 or not keys:
        raise ValueError("地图上至少要有两个带目标值的方案")
    used = [choice for choice in choices if all(set(keys) <= c.objectives.keys() for c in choice.candidates)]

    current = np.array([[pose.objectives[key] for key in keys] for _, pose in poses])
    menus = [np.array([[c.objectives[key] for key in keys] for c in choice.candidates]) for choice in used]
    # One shared [0, 1] scale for history and current schemes, so training and scoring see the same space.
    every = np.vstack([current, *menus])
    low, span = every.min(axis=0), np.maximum(np.ptp(every, axis=0), 1e-9)

    def scale(rows: np.ndarray) -> np.ndarray:
        return (rows - low) / span

    model = SlfnUtility(len(keys), config.slfn)
    if used:
        chosen = [[c.id for c in choice.candidates].index(choice.chosen_id) for choice in used]
        model.fit([scale(menu) for menu in menus], chosen)
    normalized = scale(current)
    scores = model.score(normalized)

    picked = _diverse_top(normalized, scores, top_k or config.top_k, config.min_distance)
    return {
        "basis": "past_choices" if used else "equal_weights",
        "choices_used": len(used),
        "choices_skipped": len(choices) - len(used),
        "weights": [
            {"key": key, "label": RANKED_OBJECTIVES[key], "weight": round(float(w), 3)}
            for key, w in zip(keys, model.linear_weights())
        ],
        "recommendations": [
            {
                "rank": rank,
                "pose_id": poses[row][1].id,
                "index": poses[row][0] + 1,
                "score": round(float(scores[row]), 4),
                "objectives": {key: poses[row][1].objectives[key] for key in keys},
            }
            for rank, row in enumerate(picked, start=1)
        ],
    }


def _diverse_top(normalized: np.ndarray, scores: np.ndarray, k: int, min_distance: float) -> list[int]:
    order = [int(i) for i in np.argsort(scores, kind="stable")]
    picked: list[int] = []
    for row in order:
        if len(picked) < k and all(np.linalg.norm(normalized[row] - normalized[p]) >= min_distance for p in picked):
            picked.append(row)
    picked += [row for row in order if row not in picked][: k - len(picked)]
    return picked
