"""Frozen A5 groups and P8-R3 recommendations for one strict Pareto front.

The grouping and recommendation functions are the validated diagnostic
implementations. This module only loads them and checks the subset invariant.
Bend is degrees, matching the A5 tolerances. It does not rerun a search.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
ALGORITHM_VERSION = "A5-hausdorff20-tower0-length30-bend3-crossing10+R3-extremes-stable-macro-crossing-tradeoff+tie-front-index"
REVIEW_STATUS = "NOT_REVIEWED"
TOWER_OFFSET_REVIEW_M = 10.0
HIGH_TOWER_OFFSET_M = 50.0
FLAG = "ENABLE_ROUTING_THREE_MODE_PREVIEW"


def preview_enabled() -> bool:
    return os.getenv(FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


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


def legacy_portfolio_message(published_count: int, recorded_pareto_count: int | None) -> str:
    recorded = "未记录" if recorded_pareto_count is None else str(recorded_pareto_count)
    return (
        f"该历史结果仅保存旧发布线路 {published_count} 条"
        f"（摘要记录的精确前沿数为 {recorded}）。"
        "完整非支配前沿的几何没有保存，不能恢复，也不会重新优化来冒充当时的前沿。"
    )
