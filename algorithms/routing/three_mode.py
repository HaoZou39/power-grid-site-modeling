"""Displayed filter and the historical three-mode builder.

The displayed filter uses algorithms.routing.similarity. It does not load
diagnostics, recommendation rules, or a second front. build_three_mode still
reads local diagnostic rules when that historical function is called.
Bend is degrees, matching the A5 tolerances. This module does not rerun a search.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np

from algorithms.routing.similarity import (
    a5_keep,
    member_accepts_representative,
    normalized_sum,
    symmetric_hausdorff,
    tower_components,
)

SCHEMA_VERSION = 1
ALGORITHM_VERSION = "A5-hausdorff20-tower0-length30-bend3-crossing10+R3-extremes-stable-macro-crossing-tradeoff+tie-front-index"
REVIEW_STATUS = "NOT_REVIEWED"
TOWER_OFFSET_REVIEW_M = 10.0
HIGH_TOWER_OFFSET_M = 50.0
LEGACY_PORTFOLIO_MESSAGE = "该历史任务未保存完整非支配解，无法使用全部结果展示功能。"


def _load(name: str, path: Path):
    module_name = f"_routing_three_mode_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _verified():
    root = Path(__file__).resolve().parents[2]
    portfolio_dir = root / "diagnostics/CANGNAN_ENGINEERING_PREFERENCE_PORTFOLIO"
    if str(portfolio_dir) not in sys.path:
        sys.path.insert(0, str(portfolio_dir))
    portfolio = _load("portfolio_rules", portfolio_dir / "portfolio_rules.py")
    p4 = _load("p4_rules", root / "diagnostics/CANGNAN_P4_ADAPTIVE_PORTFOLIO_ABLATION/p4_rules.py")
    p8 = _load("p8_rules", root / "diagnostics/ROUTING_P8_ENGINEERING_RECOMMENDATIONS/p8_rules.py")
    grouping = _load("grouping", root / "diagnostics/PARETO_CORRIDOR_REPRESENTATIVE_ABLATION/grouping.py")
    towers = _load("p10_rules", root / "diagnostics/ROUTING_P10_THREE_MODE_GROUPING/p10_rules.py")
    if portfolio.A5_TOLERANCE != p8.A5_TOLERANCE or portfolio.GEO_M != p8.GEO_M:
        raise RuntimeError("A5 tolerances diverged from the validated P8 copy")
    return portfolio, p4, p8, grouping, towers


def corridor_shape(lines: list[np.ndarray]) -> dict:
    """Same linkage shape as the Yongjia transfer. Unstable labels are not used."""
    portfolio, _p4, p8, grouping, _towers = _verified()
    fractions = grouping.arc_fractions()
    start, end = lines[0][0], lines[0][-1]
    profiles = np.vstack([grouping.lateral_profile(poly, start, end, fractions) for poly in lines])
    mean_lateral = profiles.mean(axis=1)
    midpoint_x = np.array([poly[len(poly) // 2, 0] for poly in lines])
    merges = grouping.complete_linkage_merges(grouping.profile_distance(profiles))
    sweep = grouping.sweep_complete_linkage(
        merges, len(lines), mean_lateral, portfolio.corridor_labels(mean_lateral),
    )
    choice = grouping.choose_partitions(sweep)
    macro = grouping.relabel_west_to_east(choice["macro"]["labels"], midpoint_x)
    macro_m = float(choice["macro"]["threshold_m"])
    stable = bool(choice["macro_stable"]) and macro_m >= p8.MAJOR_CORRIDOR_CUT_M
    return {"macro": macro, "macro_m": macro_m, "stable": stable}


def _column_winners(objectives: np.ndarray, normalized_sum) -> list[int]:
    score = normalized_sum(objectives)
    winners = []
    for column in range(objectives.shape[1]):
        hits = np.flatnonzero(objectives[:, column] == objectives[:, column].min())
        winners.append(min((int(hit) for hit in hits), key=lambda index: (float(score[index]), index)))
    return winners


def _tied(objectives: np.ndarray, winners: list[int], pool: set[int]) -> list[tuple[int, int]]:
    tied = []
    for column, winner in enumerate(winners):
        hits = np.flatnonzero(objectives[:, column] == objectives[winner, column])
        for hit in hits:
            if int(hit) != winner and int(hit) in pool:
                tied.append((int(hit), column))
    return tied


def build_three_mode(
    route_ids: list[str],
    objectives_deg: np.ndarray,
    lines: list[np.ndarray],
    distance: np.ndarray | None = None,
    shape: dict | None = None,
    representative_order: list[int] | None = None,
) -> dict:
    """One group per strict-Pareto route, then R3 on the A5 representatives."""
    if len(route_ids) != len(objectives_deg) or len(route_ids) != len(lines):
        raise ValueError("route ids, objectives and lines must describe the same front")
    if len(set(route_ids)) != len(route_ids):
        raise ValueError("route ids must be unique")
    portfolio, p4, p8, _grouping, towers = _verified()
    objectives = np.asarray(objectives_deg, dtype=float)
    if distance is None:
        root = Path(__file__).resolve().parents[2]
        benchmark = _load(
            "benchmark",
            root / "diagnostics/PARETO_REPRESENTATIVE_SELECTION_BENCHMARK/benchmark.py",
        )
        distance, _meta = benchmark.symmetric_hausdorff(lines)
    distance = np.asarray(distance, dtype=float)
    if distance.shape != (len(route_ids), len(route_ids)):
        raise ValueError("Hausdorff matrix does not match the front")
    if shape is None and lines:
        shape = corridor_shape(lines)
    winners = _column_winners(objectives, portfolio.normalized_sum)
    forced = list(dict.fromkeys(winners))
    kept, assignment = portfolio.a5_keep(distance, objectives, forced)
    members_of: dict[int, list[int]] = {rep: [rep] for rep in kept}
    for route, rep in assignment.items():
        members_of[int(rep)].append(int(route))
    seen = [route for members in members_of.values() for route in members]
    if sorted(seen) != list(range(len(route_ids))):
        raise RuntimeError("A5 groups do not partition the front")
    for rep, members in members_of.items():
        if rep not in members:
            raise RuntimeError("representative is not a group member")
        for member in members:
            if not towers.member_accepts_representative(member, rep, objectives, distance):
                raise RuntimeError(f"{route_ids[member]} is outside the five A5 conditions of {route_ids[rep]}")
    groups = []
    group_of = {}
    for rep in kept:
        member_ids = [route_ids[index] for index in members_of[rep]]
        offsets = []
        for index in members_of[rep]:
            parts = towers.tower_components(lines[index], lines[rep])
            offsets.append(0.0 if parts is None else float(parts["max_m"]))
        max_offset = max(offsets) if offsets else 0.0
        flags = ["CROSSING_OBJECTS_DATA_MISSING", "FARMLAND_DATA_MISSING"]
        if max_offset > TOWER_OFFSET_REVIEW_M:
            flags.append("TOWER_OFFSET")
        if max_offset > HIGH_TOWER_OFFSET_M:
            flags.append("HIGH_TOWER_OFFSET")
        group_id = f"group-{route_ids[rep]}"
        record = {
            "group_id": group_id,
            "representative_route_id": route_ids[rep],
            "member_route_ids": member_ids,
            "member_count": len(member_ids),
            "group_risk_flags": flags,
            "engineering_review_status": REVIEW_STATUS,
            "max_tower_offset_m": max_offset,
        }
        groups.append(record)
        for route_id in member_ids:
            group_of[route_id] = record
    # Group listing follows front order unless a caller supplies the same set
    # in another order. Recommendation ties use the original front index, so
    # that listing order does not change which routes are chosen.
    pool = list(representative_order) if representative_order is not None else sorted(kept)
    if set(pool) != set(kept):
        raise ValueError("representative order must be the A5 kept set")
    local_of = {route: position for position, route in enumerate(pool)}
    roles: dict[int, list[int]] = {}
    for column, route in enumerate(winners):
        roles.setdefault(local_of[route], []).append(column)
    stable = bool(shape and shape.get("stable"))
    labels = [int(shape["macro"][route]) for route in pool] if stable else None
    local_objectives = objectives[np.asarray(pool)]
    local_distance = distance[np.ix_(pool, pool)]
    norm = p4.minmax_fit(objectives, pool)[np.asarray(pool)]
    recommendation = p8.build_recommendation(
        local_objectives, local_distance, norm, p8.PRIMARY_WEIGHTS, portfolio.geo_cap_of(distance, pool),
        [local_of[route] for route in forced],
        {route: tuple(columns) for route, columns in roles.items()},
        [(local_of[route], column) for route, column in _tied(objectives, winners, set(pool))],
        labels, True, identity=pool,
    )
    recommended = []
    for rank, local_index in enumerate(recommendation["default"], start=1):
        route_id = route_ids[pool[local_index]]
        group = group_of[route_id]
        record = recommendation["records"][local_index]
        recommended.append({
            "route_id": route_id,
            "recommendation_tags": list(record["tags"]),
            "recommendation_reasons": record["reason"],
            "recommendation_rank": rank,
            "review_flags": list(group["group_risk_flags"]),
            "group_id": group["group_id"],
        })
    recommended_ids = [item["route_id"] for item in recommended]
    representatives = [item["representative_route_id"] for item in groups]
    if len(recommended_ids) != len(set(recommended_ids)):
        raise RuntimeError("recommendation ids are not unique")
    if not set(recommended_ids) <= set(representatives) <= set(route_ids):
        raise RuntimeError("recommended routes are not A5 representatives of this front")
    return {
        "groups": groups,
        "recommendations": recommended,
        "corridor_status": recommendation["corridor_status"] if not stable else "STABLE",
        "counts": {
            "all_pareto": len(route_ids),
            "a5_groups": len(groups),
            "recommended": len(recommended),
        },
    }


def legacy_portfolio_message(_published_count: int, _recorded_pareto_count: int | None) -> str:
    # Counts stay on the manifest. This sentence does not present them as the Pareto total.
    return LEGACY_PORTFOLIO_MESSAGE


def horizontal_tortuosity(line: np.ndarray) -> float | None:
    """K = horizontal path length / straight-line distance. None is not a passing value."""
    points = np.asarray(line, dtype=float)
    if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] < 2:
        return None
    xy = points[:, :2]
    if not np.isfinite(xy).all():
        return None
    length = float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum())
    straight = float(np.linalg.norm(xy[-1] - xy[0]))
    if not np.isfinite(length) or not np.isfinite(straight) or straight <= 0:
        return None
    return length / straight


def build_filtered_portfolio(
    route_ids: list[str],
    objectives_deg: np.ndarray,
    lines: list[np.ndarray],
    distance: np.ndarray | None = None,
    max_tortuosity: float = 1.5,
) -> dict:
    """Drop routes with K above the limit, then run A5 only on the routes that remain.

    This does not call the recommendation algorithm. Routes that fail K, and routes
    whose K cannot be computed, stay in the full front and out of the filtered list.
    """
    if isinstance(max_tortuosity, bool) or not isinstance(max_tortuosity, (int, float)) or not math.isfinite(max_tortuosity) or max_tortuosity <= 0:
        raise ValueError("max_tortuosity must be a finite number > 0")
    if len(route_ids) != len(objectives_deg) or len(route_ids) != len(lines):
        raise ValueError("route ids, objectives and lines must describe the same front")
    if len(set(route_ids)) != len(route_ids):
        raise ValueError("route ids must be unique")
    objectives = np.asarray(objectives_deg, dtype=float)
    tortuosity = [horizontal_tortuosity(line) for line in lines]
    eligible = [index for index, value in enumerate(tortuosity) if value is not None and value <= max_tortuosity]
    rejected = [index for index, value in enumerate(tortuosity) if value is not None and value > max_tortuosity]
    invalid = [index for index, value in enumerate(tortuosity) if value is None]
    if len(eligible) + len(rejected) + len(invalid) != len(route_ids):
        raise RuntimeError("tortuosity split does not cover the front")
    groups = _deduplicate_eligible(route_ids, objectives, lines, distance, eligible)
    filtered = [group["representative_route_id"] for group in groups]
    if len(filtered) != len(set(filtered)):
        raise RuntimeError("filtered route ids are not unique")
    eligible_ids = {route_ids[index] for index in eligible}
    grouped = {route_id for group in groups for route_id in group["member_route_ids"]}
    if grouped != eligible_ids or not set(filtered) <= eligible_ids <= set(route_ids):
        raise RuntimeError("filtered routes are not the A5 representatives of the tortuosity-eligible front")
    return {
        "groups": groups,
        "recommendations": [],
        "filtered_route_ids": filtered,
        "tortuosity_k": tortuosity,
        "max_tortuosity": float(max_tortuosity),
        "counts": {
            "all_pareto": len(route_ids),
            "a5_groups": len(groups),
            "filtered": len(filtered),
            "tortuosity_eligible": len(eligible),
            "tortuosity_rejected": len(rejected),
            "tortuosity_invalid": len(invalid),
            "recommended": 0,
        },
    }


def _deduplicate_eligible(route_ids, objectives, lines, distance, eligible: list[int]) -> list[dict]:
    if not eligible:
        return []
    index = np.asarray(eligible, dtype=int)
    sub_objectives = objectives[index]
    if distance is None:
        sub_distance, _meta = symmetric_hausdorff([lines[int(item)] for item in index])
    else:
        full = np.asarray(distance, dtype=float)
        if full.shape != (len(route_ids), len(route_ids)):
            raise ValueError("Hausdorff matrix does not match the front")
        sub_distance = full[np.ix_(index, index)]
    winners = _column_winners(sub_objectives, normalized_sum)
    kept_local, assignment = a5_keep(sub_distance, sub_objectives, list(dict.fromkeys(winners)))
    original = {local: int(index[local]) for local in range(len(index))}
    members_of: dict[int, list[int]] = {original[int(local)]: [original[int(local)]] for local in kept_local}
    for local_member, local_rep in assignment.items():
        members_of[original[int(local_rep)]].append(original[int(local_member)])
    seen = [route for members in members_of.values() for route in members]
    if sorted(seen) != sorted(int(item) for item in index):
        raise RuntimeError("A5 groups do not partition the tortuosity-eligible routes")
    local_of = {original[local]: local for local in original}
    for rep, members in members_of.items():
        for member in members:
            if not member_accepts_representative(local_of[member], local_of[rep], sub_objectives, sub_distance):
                raise RuntimeError(f"{route_ids[member]} is outside the five A5 conditions of {route_ids[rep]}")
    groups = []
    for rep in sorted(members_of):
        member_indexes = [rep, *[item for item in sorted(members_of[rep]) if item != rep]]
        offsets = []
        for member in member_indexes:
            parts = tower_components(lines[member], lines[rep])
            offsets.append(0.0 if parts is None else float(parts["max_m"]))
        max_offset = max(offsets) if offsets else 0.0
        flags = ["CROSSING_OBJECTS_DATA_MISSING", "FARMLAND_DATA_MISSING"]
        if max_offset > TOWER_OFFSET_REVIEW_M:
            flags.append("TOWER_OFFSET")
        if max_offset > HIGH_TOWER_OFFSET_M:
            flags.append("HIGH_TOWER_OFFSET")
        groups.append({
            "group_id": f"group-{route_ids[rep]}",
            "representative_route_id": route_ids[rep],
            "member_route_ids": [route_ids[item] for item in member_indexes],
            "member_count": len(member_indexes),
            "group_risk_flags": flags,
            "engineering_review_status": REVIEW_STATUS,
            "max_tower_offset_m": max_offset,
        })
    return groups
