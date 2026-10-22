"""Rank one pose against the others using only objectives already in the snapshot.

Objective order and direction follow markdown/GUIDED_SEARCH.md: all minimized; road_haul_m only with an origin.
"""

from __future__ import annotations

from agent.workspace import Pose, WorkspaceSnapshot

# Labels match the solution card in the frontend, so the answer and the map use the same words.
RANKED_OBJECTIVES = {
    "dem_soft": "地形平整度",
    "demand_distance": "需求点距离（m）",
    "road_haul_m": "沿路长度（m）",
    "offroad_haul_m": "进站长度（m）",
    "haul_rise_m": "进站累计高差（m）",
}
EDGE_SHARE = 0.25


def compared_keys(snapshot: WorkspaceSnapshot) -> list[str]:
    return [key for key in RANKED_OBJECTIVES if key != "road_haul_m" or snapshot.origin is not None]


def ranking_candidates(snapshot: WorkspaceSnapshot) -> list[tuple[int, Pose]]:
    """Poses that enter an objective comparison. The index is the 0-based place on the map.

    `feasible is False` stays out. An unreachable approach is stored as 0, and every objective is minimized,
    so that 0 would otherwise rank ahead of a real scheme. A missing flag still counts.
    """

    return [
        (index, pose)
        for index, pose in enumerate(snapshot.poses)
        if pose.objectives and pose.feasible is not False
    ]


def rank_pose(snapshot: WorkspaceSnapshot, pose_id: str) -> dict[str, object]:
    index = next((i for i, pose in enumerate(snapshot.poses) if pose.id == pose_id), None)
    if index is None:
        raise ValueError(f"没有这个方案：{pose_id}")
    pose = snapshot.poses[index]
    if pose.feasible is False:
        raise ValueError(f"方案 {index + 1} 不满足当前约束，不参与目标比较")
    candidates = ranking_candidates(snapshot)
    own = pose.objectives or {}
    ranks, strengths, weaknesses = [], [], []
    for key in compared_keys(snapshot):
        values = [(other.objectives[key], i) for i, other in candidates if other.objectives and key in other.objectives]
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
