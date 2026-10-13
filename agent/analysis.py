"""Rank one pose against the others using only objectives already in the snapshot.

Objective order and direction follow markdown/GUIDED_SEARCH.md: all minimized; road_haul_m only with an origin.
"""

from __future__ import annotations

from agent.workspace import WorkspaceSnapshot

# Labels match the solution card in the frontend, so the answer and the map use the same words.
RANKED_OBJECTIVES = {
    "dem_soft": "地形平整度",
    "demand_distance": "需求点距离（m）",
    "road_haul_m": "沿路长度（m）",
    "offroad_haul_m": "进场（m）",
    "haul_rise_m": "进场高差（m）",
}
EDGE_SHARE = 0.25


def compared_keys(snapshot: WorkspaceSnapshot) -> list[str]:
    return [key for key in RANKED_OBJECTIVES if key != "road_haul_m" or snapshot.origin is not None]


def rank_pose(snapshot: WorkspaceSnapshot, pose_id: str) -> dict[str, object]:
    index = next((i for i, pose in enumerate(snapshot.poses) if pose.id == pose_id), None)
    if index is None:
        raise ValueError(f"没有这个方案：{pose_id}")
    pose = snapshot.poses[index]
    own = pose.objectives or {}
    ranks, strengths, weaknesses = [], [], []
    for key in compared_keys(snapshot):
        values = [(other.objectives[key], i) for i, other in enumerate(snapshot.poses) if other.objectives and key in other.objectives]
        if key not in own or len(values) < 2:
            continue
        rank = 1 + sum(value < own[key] for value, _ in values)
        best_value, best = min(values)
        ranks.append({
            "key": key,
            "label": RANKED_OBJECTIVES[key],
            "value": own[key],
            "rank": rank,
            "of": len(values),
            "best_value": best_value,
            "best_pose_id": snapshot.poses[best].id,
            "best_index": best + 1,
        })
        if rank <= max(1, round(EDGE_SHARE * len(values))):
            strengths.append(key)
        elif rank > len(values) - max(1, round(EDGE_SHARE * len(values))):
            weaknesses.append(key)
    return {
        "pose": {"id": pose.id, "index": index + 1, "x": pose.x, "y": pose.y, "theta": pose.theta, "objectives": own},
        "ranks": ranks,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "road_distance": own.get("road_distance"),
    }
