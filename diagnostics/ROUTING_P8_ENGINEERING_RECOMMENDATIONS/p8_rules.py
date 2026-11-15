"""Interpretable route recommendations.

Thresholds are the frozen A5 tolerances and the P6 independence bars.
They are not adjusted to land on a count. A route that does not clear them
is recorded for review instead of being added to fill a quota.
"""

from __future__ import annotations

import numpy as np

# Copies of portfolio_rules.A5_TOLERANCE and GEO_M. The runner checks the live values.
A5_TOLERANCE = (0.0, 30.0, 3.0, 10.0)
GEO_M = 20.0
INDEPENDENT_GEOMETRY_M = 40.0
INDEPENDENT_OBJECTIVE = 0.15
SOFT_CAP = 10
EXTENDED_CAP = 15
MAJOR_CORRIDOR_CUT_M = 400.0
PRIMARY_WEIGHTS = (0.5, 0.5)
SENSITIVITY_WEIGHTS = ((0.7, 0.3), (0.3, 0.7))
LONG_DETOUR_M = 6000.0

EXTREME_TAGS = ("最少塔", "最短线路", "最小转角", "最小跨越")
LENGTH_CROSSING = "长度—跨越折中"
TOWER_CROSSING = "塔数—跨越折中"
BEND_CROSSING = "转角—跨越折中"
CORRIDOR_TAG = "主要走廊代表"
SPATIAL_TAG = "独立空间走向"
TRADEOFF_TAGS = (LENGTH_CROSSING, TOWER_CROSSING, BEND_CROSSING)


def a5_equivalent(objectives: np.ndarray, distance: np.ndarray, left: int, right: int) -> bool:
    if left == right:
        return True
    if float(distance[left, right]) > GEO_M:
        return False
    delta = objectives[left] - objectives[right]
    return all(abs(float(delta[column])) <= A5_TOLERANCE[column] for column in range(4))


def pair_score(left: int, right: int, norm: np.ndarray, distance: np.ndarray, weights: tuple[float, float], cap: float) -> float:
    objective = float(np.linalg.norm(norm[left] - norm[right]) / 2.0)
    geometric = min(float(distance[left, right]) / cap, 1.0)
    return weights[0] * objective + weights[1] * geometric


def tie_identity(identity, size: int) -> np.ndarray:
    """Original front index for each local row.

    An exact score tie uses this value, not the position in the array being
    scanned. Callers that omit it keep the old local-position behavior.
    """
    if identity is None:
        return np.arange(size)
    values = np.asarray(identity)
    if values.shape != (size,):
        raise ValueError("tie identity must be one original front index per local route")
    return values


def farthest(candidates: list[int], selected: list[int], norm, distance, weights, cap: float, identity=None) -> int | None:
    keys = tie_identity(identity, len(norm))
    best, best_key = None, None
    for index in candidates:
        if index in selected:
            continue
        # Smaller original front index wins. The key is negated so max() keeps it.
        rank = -int(keys[index])
        if not selected:
            key = (1.0, rank)
        else:
            separation = min(pair_score(index, other, norm, distance, weights, cap) for other in selected)
            key = (separation, rank)
        if best_key is None or key > best_key:
            best, best_key = index, key
    return best


def balance_index(candidates: list[int], norm: np.ndarray, columns: tuple[int, int], identity=None) -> int | None:
    """Minimize the worse of two normalized objectives. Exact ties take the smaller front index."""
    if not candidates:
        return None
    keys = tie_identity(identity, len(norm))
    return min(candidates, key=lambda index: (max(float(norm[index, columns[0]]), float(norm[index, columns[1]])), int(keys[index])))


def _phrase(baseline: str, base: np.ndarray, route: np.ndarray) -> str:
    parts = []
    names = (("塔数", 0, "座", 0), ("长度", 1, "m", 1), ("转角", 2, "°", 1), ("跨越", 3, "m", 1))
    for name, column, unit, digits in names:
        delta = float(route[column] - base[column])
        if abs(delta) < 10 ** (-digits) / 2:
            parts.append(f"{name}不变")
            continue
        direction = "增加" if delta > 0 else "减少"
        parts.append(f"{name}{direction} {abs(delta):.{digits}f} {unit}")
    return f"相对{baseline}，" + "，".join(parts) + "。"


def _nearest(index: int, selected: list[int], distance: np.ndarray, identity: np.ndarray) -> int:
    return min(selected, key=lambda other: (float(distance[index, other]), int(identity[other])))


def _equivalent_to_any(index: int, selected: list[int], objectives, distance) -> bool:
    return any(a5_equivalent(objectives, distance, index, other) for other in selected)


def build_recommendation(
    objectives: np.ndarray,
    distance: np.ndarray,
    norm: np.ndarray,
    weights: tuple[float, float],
    cap: float,
    extremes: list[int],
    extreme_roles: dict[int, tuple[int, ...]],
    tied: list[tuple[int, int]],
    labels: list[int] | None,
    include_tradeoffs: bool,
    identity=None,
) -> dict:
    """Core protection, then only tradeoffs that clear the A5 raw-unit bars.

    Diversity fills up to 10 and 15 are returned separately. They are not part
    of the default recommendation.
    """
    records: dict[int, dict] = {}
    reviews = []
    alternatives = []
    selected: list[int] = []
    keys = tie_identity(identity, len(objectives))

    def add(index: int, tags: list[str], reason: str, source: str, tier: str) -> None:
        if index in records:
            current = records[index]
            for tag in tags:
                if tag not in current["tags"]:
                    current["tags"].append(tag)
            current["reason"] = current["reason"] + reason
            if labels is not None:
                current["corridor"] = labels[index]
            return
        selected.append(index)
        records[index] = {"tags": list(tags), "reason": reason, "source": source, "tier": tier, "rank": len(selected)}
        if labels is not None:
            records[index]["corridor"] = labels[index]

    for index in extremes:
        roles = extreme_roles.get(index, ())
        tags = [EXTREME_TAGS[column] for column in roles]
        values = "、".join(f"{EXTREME_TAGS[column]} {objectives[index, column]:.1f}" for column in roles)
        add(index, tags, f"完整前沿四目标极值：{values}。", "extreme", "core")

    stable = labels is not None
    if stable:
        for label in sorted(set(labels)):
            if any(labels[index] == label for index in selected):
                continue
            tied_here = []
            for index, column in tied:
                winner = next(route for route, roles in extreme_roles.items() if column in roles)
                if labels[index] != label or labels[winner] == label:
                    continue
                if float(distance[index, winner]) <= INDEPENDENT_GEOMETRY_M:
                    continue
                tied_here.append((float(distance[index, winner]), -int(keys[index]), index, column, winner))
            if tied_here:
                _, _, choice, column, winner = max(tied_here)
                add(
                    choice,
                    [EXTREME_TAGS[column], SPATIAL_TAG],
                    f"与{EXTREME_TAGS[column]}并列，且位于尚未覆盖的稳定宏观走廊 {label}，Hausdorff {distance[choice, winner]:.1f} m。",
                    "tied-extreme",
                    "core",
                )
                records[choice]["corridor"] = label
                continue
            group = [index for index, value in enumerate(labels) if value == label]
            if any(labels[index] == label for index in selected):
                continue
            group = [index for index, value in enumerate(labels) if value == label]
            choice = farthest(group, selected, norm, distance, weights, cap, keys)
            if choice is None:
                continue
            nearest = _nearest(choice, selected, distance, keys)
            add(
                choice,
                [CORRIDOR_TAG],
                f"稳定宏观走廊 {label} 尚无代表。与最近已选线路 Hausdorff {distance[choice, nearest]:.1f} m。"
                + _phrase("该线路", objectives[nearest], objectives[choice]),
                "corridor",
                "core",
            )
            records[choice]["corridor"] = label
    corridor_status = "STABLE" if stable else "CORRIDOR_LABEL_UNSTABLE"

    def consider_tradeoff(tag: str, columns: tuple[int, int], baseline: int, baseline_name: str, gain_column: int, gain_limit: float, cost_column: int, cost_limit: float) -> None:
        blocked = [route for route in selected if a5_equivalent(objectives, distance, route, baseline) or route == baseline]
        candidates = [index for index in range(len(objectives)) if not _equivalent_to_any(index, blocked or [baseline], objectives, distance)]
        choice = balance_index(candidates, norm, columns, keys)
        if choice is None:
            reviews.append({"route": None, "tag": tag, "detail": f"没有与{baseline_name}不同的候选"})
            return
        gain = float(objectives[baseline, gain_column] - objectives[choice, gain_column])
        cost = float(objectives[choice, cost_column] - objectives[baseline, cost_column])
        detail = _phrase(baseline_name, objectives[baseline], objectives[choice])
        if gain <= gain_limit or cost <= cost_limit:
            reviews.append({"route": choice, "tag": tag, "detail": f"折中点未超过冻结容差。{detail}"})
            return
        if _equivalent_to_any(choice, selected, objectives, distance):
            host = next(route for route in selected if a5_equivalent(objectives, distance, choice, route))
            add(host, [tag], detail, "tradeoff", records[host]["tier"])
            return
        add(choice, [tag], detail, "tradeoff", "tradeoff")

    if include_tradeoffs:
        length_route = next(index for index, roles in extreme_roles.items() if 1 in roles)
        tower_route = next(index for index, roles in extreme_roles.items() if 0 in roles)
        bend_route = next(index for index, roles in extreme_roles.items() if 2 in roles)
        consider_tradeoff(LENGTH_CROSSING, (1, 3), length_route, "最短线路", 3, A5_TOLERANCE[3], 1, 0.0)
        consider_tradeoff(TOWER_CROSSING, (0, 3), tower_route, "最少塔方案", 3, A5_TOLERANCE[3], 0, A5_TOLERANCE[0])
        consider_tradeoff(BEND_CROSSING, (2, 3), bend_route, "最小转角方案", 3, A5_TOLERANCE[3], 2, A5_TOLERANCE[2])

    alternatives.extend(_prune_near_neighbors(selected, records, objectives, distance, reviews))
    # Optional lists use the same front-index tie. They are not the default recommendation.
    default = [index for index in selected if records[index]["tier"] in {"core", "tradeoff"}]
    capacity = "DEFAULT_CAPACITY_INSUFFICIENT" if len(default) > SOFT_CAP else "OK"

    optional = _fill(default, records, objectives, distance, norm, weights, cap, SOFT_CAP, INDEPENDENT_GEOMETRY_M, "optional", keys)
    extended = _fill(optional, records, objectives, distance, norm, weights, cap, EXTENDED_CAP, None, "extended", keys)
    return {
        "core": [index for index in default if records[index]["tier"] == "core"],
        "default": default,
        "optional": optional,
        "extended": extended,
        "records": records,
        "reviews": reviews,
        "alternatives": alternatives,
        "capacity": capacity,
        "corridor_status": corridor_status,
    }


def _fill(seed: list[int], records: dict, objectives, distance, norm, weights, cap: float, limit: int, geometry_floor: float | None, tier: str, identity: np.ndarray) -> list[int]:
    chosen = list(seed)
    while len(chosen) < limit:
        candidates = [index for index in range(len(objectives)) if index not in chosen and not _equivalent_to_any(index, chosen, objectives, distance)]
        choice = farthest(candidates, chosen, norm, distance, weights, cap, identity)
        if choice is None:
            break
        nearest = _nearest(choice, chosen, distance, identity)
        gap = float(distance[choice, nearest])
        if geometry_floor is not None and gap <= geometry_floor:
            break
        objective = float(np.linalg.norm(norm[choice] - norm[nearest]) / 2.0)
        records[choice] = {
            "tags": [SPATIAL_TAG],
            "reason": f"诊断扩展，不是默认推荐。与最近已选线路 Hausdorff {gap:.1f} m，目标距离 {objective:.3f}。"
            + _phrase("最近已选线路", objectives[nearest], objectives[choice]),
            "source": tier,
            "tier": tier,
            "rank": len(chosen) + 1,
        }
        chosen.append(choice)
    return chosen


def _duty(record: dict) -> tuple:
    tags = tuple(tag for tag in record["tags"] if tag in EXTREME_TAGS or tag in TRADEOFF_TAGS or tag == CORRIDOR_TAG)
    return tags, record.get("corridor")


def _prune_near_neighbors(selected: list[int], records: dict, objectives, distance, reviews: list) -> list[dict]:
    """Drop a later neighbor inside 20 m when both carry the same duties.

    Different extremes or different corridor labels both stay, and the pair is
    recorded so a small crossing gap between different tower counts remains visible.
    """
    alternatives = []
    removed = set()
    for left_pos, left in enumerate(selected):
        if left in removed:
            continue
        for right in selected[left_pos + 1:]:
            if right in removed:
                continue
            gap = float(distance[left, right])
            if gap > GEO_M:
                continue
            crossing_delta = abs(float(objectives[left, 3] - objectives[right, 3]))
            tower_delta = abs(float(objectives[left, 0] - objectives[right, 0]))
            detail = f"Hausdorff {gap:.1f} m，塔数差 {tower_delta:.0f}，跨越差 {crossing_delta:.1f} m。"
            left_extreme = set(records[left]["tags"]) & set(EXTREME_TAGS)
            right_extreme = set(records[right]["tags"]) & set(EXTREME_TAGS)
            different_extreme = bool(left_extreme and right_extreme and left_extreme != right_extreme)
            left_corridor = records[left].get("corridor")
            right_corridor = records[right].get("corridor")
            different_corridor = left_corridor is not None and right_corridor is not None and left_corridor != right_corridor
            if different_extreme or different_corridor or crossing_delta > A5_TOLERANCE[3]:
                reviews.append({"route": right, "tag": "近邻保留", "detail": "两条线路的极值、走廊或跨越差超过冻结容差。" + detail})
                continue
            drop = right if records[right]["rank"] >= records[left]["rank"] else left
            kept = left if drop == right else right
            removed.add(drop)
            records[drop]["tier"] = "alternative"
            alternatives.append({
                "dropped": drop,
                "kept": kept,
                "detail": "同类型近邻，默认只保留先入选的一条。" + detail,
                "review": tower_delta > 0 and crossing_delta <= A5_TOLERANCE[3],
            })
            reviews.append({"route": drop, "tag": "可替换近邻", "detail": alternatives[-1]["detail"]})
    return alternatives


def sets_equivalent(left: list[int], right: list[int], objectives, distance) -> bool:
    if len(left) != len(right):
        return False
    return all(any(a5_equivalent(objectives, distance, item, other) for other in right) for item in left) and all(
        any(a5_equivalent(objectives, distance, item, other) for other in left) for item in right
    )


def choose_method(rows: list[dict]) -> str:
    """Keep R3 only when its tradeoff is absent from the historical prefix on at least three pools.

    If the sets are A5-equivalent on four or more pools, the extra rules did not
    change the engineering choice and the historical prefix remains the method.
    A missed stable corridor disqualifies R3.
    """
    if any(row["misses_stable_corridor"] for row in rows):
        return "NONE"
    equivalent = sum(bool(row["equivalent_to_r0"]) for row in rows)
    distinct = sum(bool(row["tradeoff_absent_from_r0"]) for row in rows)
    if equivalent >= 4:
        return "R0"
    if distinct >= 3:
        return "R3"
    return "NONE"
