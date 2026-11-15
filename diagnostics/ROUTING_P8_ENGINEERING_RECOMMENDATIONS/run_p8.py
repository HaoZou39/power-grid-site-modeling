"""Recommend a few interpretable routes from the frozen Pareto archives.

The full front and the A5 set stay intact. The default list is only the
extremes, stable macro corridors, and tradeoffs that clear the A5 raw-unit bars.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

P8 = Path(__file__).resolve().parent
P6 = P8.parent / "ROUTING_P6_ROBUST_ADAPTIVE_STOPPING"
P5 = P8.parent / "YONGJIA_P5_FROZEN_TRANSFER"
sys.path.insert(0, str(P8))
sys.path.insert(0, str(P6))
sys.path.insert(0, str(P5))

import run_p6  # noqa: E402
from p4_rules import WEIGHTS, grow, minmax_fit, rank_fit, robust_fit  # noqa: E402
from p8_rules import (  # noqa: E402
    A5_TOLERANCE,
    BEND_CROSSING,
    EXTENDED_CAP,
    EXTREME_TAGS,
    GEO_M,
    INDEPENDENT_GEOMETRY_M,
    INDEPENDENT_OBJECTIVE,
    LENGTH_CROSSING,
    LONG_DETOUR_M,
    MAJOR_CORRIDOR_CUT_M,
    PRIMARY_WEIGHTS,
    SENSITIVITY_WEIGHTS,
    SOFT_CAP,
    TOWER_CROSSING,
    TRADEOFF_TAGS,
    a5_equivalent,
    build_recommendation,
    choose_method,
    farthest,
    sets_equivalent,
)
from portfolio_rules import A5_TOLERANCE as LIVE_TOLERANCE  # noqa: E402
from portfolio_rules import GEO_M as LIVE_GEO  # noqa: E402
from portfolio_rules import a5_keep, extreme_indices, geo_cap_of, normalized_sum  # noqa: E402

OUT = P8
FIGURES = OUT / "figures"
NORMS = {"minmax": minmax_fit, "robust": robust_fit, "rank": rank_fit}
if tuple(LIVE_TOLERANCE) != A5_TOLERANCE or float(LIVE_GEO) != GEO_M:
    raise RuntimeError("A5 constants no longer match the frozen recommendation bars")
if WEIGHTS["W1"] != PRIMARY_WEIGHTS:
    raise RuntimeError("primary joint weights are no longer 0.5/0.5")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def column_winners(objectives: np.ndarray) -> list[int]:
    score = normalized_sum(objectives)
    winners = []
    for column in range(objectives.shape[1]):
        hits = np.flatnonzero(objectives[:, column] == objectives[:, column].min())
        winners.append(min((int(hit) for hit in hits), key=lambda index: (float(score[index]), index)))
    return winners


def tied_hits(objectives: np.ndarray, winners: list[int], pool_set: set[int]) -> list[tuple[int, int]]:
    tied = []
    for column, winner in enumerate(winners):
        hits = np.flatnonzero(objectives[:, column] == objectives[winner, column])
        for hit in hits:
            if int(hit) != winner and int(hit) in pool_set:
                tied.append((int(hit), column))
    return tied


def prepare(pool: dict) -> dict:
    members = list(pool["pool"])
    index = np.asarray(members)
    winners = column_winners(pool["objectives"])
    missing = [route for route in winners if route not in set(members)]
    if missing:
        raise RuntimeError(f"{pool['name']} extreme is outside A5: {missing}")
    local_of = {route: position for position, route in enumerate(members)}
    roles: dict[int, list[int]] = {}
    for column, route in enumerate(winners):
        roles.setdefault(local_of[route], []).append(column)
    stable = str(pool["major_source"]).startswith("linkage") and float(pool["shape"]["macro_m"]) >= MAJOR_CORRIDOR_CUT_M
    labels = [int(pool["major"][route]) for route in members] if stable else None
    fine = [int(pool["fine"][route]) for route in members] if pool["fine"] is not None else None
    protection = [int(pool["protection"][route]) for route in members]
    return {
        "members": members,
        "local_of": local_of,
        "objectives": pool["objectives"][index],
        "distance": pool["distance"][np.ix_(index, index)],
        "cap": geo_cap_of(pool["distance"], members),
        "extremes": [local_of[route] for route in dict.fromkeys(winners)],
        "roles": {route: tuple(columns) for route, columns in roles.items()},
        "tied": [(local_of[route], column) for route, column in tied_hits(pool["objectives"], winners, set(members))],
        "labels": labels,
        "fine": fine,
        "protection": protection,
        "stable": stable,
        "winners": winners,
    }


def fit_norm(pool: dict, local: dict, name: str) -> np.ndarray:
    fitted = NORMS[name](pool["objectives"], local["members"])
    return fitted[np.asarray(local["members"])]


def run_r3(pool: dict, local: dict, norm: np.ndarray, weights: tuple[float, float], tradeoffs: bool) -> dict:
    return build_recommendation(
        local["objectives"], local["distance"], norm, weights, local["cap"],
        local["extremes"], local["roles"], local["tied"], local["labels"] if local["stable"] else None,
        include_tradeoffs=tradeoffs, identity=local["members"],
    )


def diversity_fill(local: dict, norm: np.ndarray, seed: list[int], weights: tuple[float, float], limit: int, objective_only: bool) -> list[int]:
    chosen = list(seed)
    while len(chosen) < limit:
        candidates = [index for index in range(len(local["objectives"])) if index not in chosen and not any(a5_equivalent(local["objectives"], local["distance"], index, other) for other in chosen)]
        choice = farthest(candidates, chosen, norm, local["distance"], weights, local["cap"])
        if choice is None:
            break
        nearest = min(chosen, key=lambda other: (float(local["distance"][choice, other]), other))
        objective = float(np.linalg.norm(norm[choice] - norm[nearest]) / 2.0)
        gap = float(local["distance"][choice, nearest])
        if objective_only and objective <= INDEPENDENT_OBJECTIVE:
            break
        if not objective_only and gap <= INDEPENDENT_GEOMETRY_M:
            break
        chosen.append(choice)
    return chosen


def subset_metrics(pool: dict, local: dict, norm: np.ndarray, selected: list[int], weights: tuple[float, float]) -> dict:
    if not selected:
        return {"k": 0, "max_h": None, "joint": None, "extremes": 0, "macro_covered": 0, "macro_present": 0}
    chosen = np.asarray(selected)
    near_m = local["distance"][:, chosen].min(axis=1)
    objective = np.linalg.norm(norm[:, None, :] - norm[chosen][None, :, :], axis=2) / 2.0
    near_o = objective.min(axis=1)
    geometric = np.minimum(local["distance"][:, chosen] / local["cap"], 1.0)
    joint = weights[0] * near_o + weights[1] * geometric.min(axis=1)
    present = sorted(set(local["labels"])) if local["labels"] is not None else []
    covered = sorted({local["labels"][index] for index in selected}) if present else []
    return {
        "k": len(selected),
        "max_h": float(near_m.max()),
        "mean_h": float(near_m.mean()),
        "max_o": float(near_o.max()),
        "joint": float(joint.mean()),
        "extremes": sum(index in selected for index in local["extremes"]),
        "macro_covered": len(covered),
        "macro_present": len(present),
        "ids": [pool["ids"][local["members"][index]] for index in selected],
    }


def global_ids(pool: dict, local: dict, selected: list[int]) -> list[str]:
    return [pool["ids"][local["members"][index]] for index in selected]


def route_row(pool: dict, local: dict, index: int, record: dict) -> dict:
    route = local["members"][index]
    objective = pool["objectives"][route]
    return {
        "pool": pool["name"],
        "route_id": pool["ids"][route],
        "tier": record["tier"],
        "rank": record["rank"],
        "source": record["source"],
        "tower_count": f"{objective[0]:.0f}",
        "length_3d_m": f"{objective[1]:.4f}",
        "bend_sum_deg": f"{objective[2]:.4f}",
        "crossing_3d_m": f"{objective[3]:.4f}",
        "macro_corridor_id": "" if local["labels"] is None else local["labels"][index],
        "micro_corridor_id": "" if local["fine"] is None else local["fine"][index],
        "corridor_status": "STABLE" if local["stable"] else "CORRIDOR_LABEL_UNSTABLE",
        "protection_label": local["protection"][index],
        "recommendation_tags": " ".join(record["tags"]),
        "recommendation_reason": record["reason"],
        "selection_source": record["source"],
    }


def bounds_of(lines):
    xs = np.concatenate([poly[:, 0] for poly in lines])
    ys = np.concatenate([poly[:, 1] for poly in lines])
    pad = 40.0
    return float(xs.min() - pad), float(xs.max() + pad), float(ys.min() - pad), float(ys.max() + pad)


def draw_routes(axis, pool, indices, bounds, numbered):
    for order, route in enumerate(indices):
        poly = pool["lines"][route]
        axis.plot(poly[:, 0], poly[:, 1], color=f"C{order % 10}", lw=1.2)
        if numbered:
            mid = poly[len(poly) // 2]
            axis.annotate(str(order + 1), mid, fontsize=7, color=f"C{order % 10}", ha="center")
    axis.set_xlim(bounds[0], bounds[1])
    axis.set_ylim(bounds[3], bounds[2])
    axis.set_aspect("equal")


def draw_background(axis, pool, bounds, color="0.85", width=0.4):
    for poly in pool["lines"]:
        axis.plot(poly[:, 0], poly[:, 1], color=color, lw=width)
    axis.set_xlim(bounds[0], bounds[1])
    axis.set_ylim(bounds[3], bounds[2])
    axis.set_aspect("equal")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    (OUT / "P8_FROZEN_CONFIG.json").write_text(json.dumps({
        "weights": list(PRIMARY_WEIGHTS),
        "sensitivity_weights": [list(item) for item in SENSITIVITY_WEIGHTS],
        "a5_tolerance": list(A5_TOLERANCE),
        "hausdorff_m": GEO_M,
        "independent_geometry_m": INDEPENDENT_GEOMETRY_M,
        "independent_objective": INDEPENDENT_OBJECTIVE,
        "soft_cap": SOFT_CAP,
        "extended_cap": EXTENDED_CAP,
        "major_corridor_cut_m": MAJOR_CORRIDOR_CUT_M,
        "tradeoff_rule": "a balance point is added only when the improved objective clears the matching A5 tolerance and the worsened objective actually increases",
        "diversity_fills": "optional through 10 and extended through 15 are diagnostic lists, not the default recommendation",
    }, indent=2))
    pools = [run_p6.load_cangnan("E1"), run_p6.load_cangnan("E4"), run_p6.load_yongjia(123), run_p6.load_yongjia(124), run_p6.load_yongjia(125)]
    audits = []
    for pool in pools:
        print(pool["name"], flush=True)
        run_p6.attach_corridors(pool)
        winners = column_winners(pool["objectives"])
        kept, assignment = a5_keep(pool["distance"], pool["objectives"], winners)
        pool["a5_assignment"] = assignment
        pool["a5_recomputed"] = kept
        pool["a5_match"] = set(kept) == set(pool["pool"])
        audits.append({
            "pool": pool["name"],
            "front": pool["front_count"],
            "saved_a5": len(pool["pool"]),
            "recomputed_a5": len(kept),
            "a5_match": pool["a5_match"],
            "major_source": pool["major_source"],
            "fine_source": pool["fine_source"],
            "max_length_m": float(pool["objectives"][:, 1].max()),
        })
    expected = {"cangnan-E1": (449, 46), "cangnan-E4": (428, 47), "yongjia-123": (701, 242), "yongjia-124": (976, 288), "yongjia-125": (671, 161)}
    for row in audits:
        front, a5 = expected[row["pool"]]
        if row["front"] != front or row["saved_a5"] != a5:
            raise RuntimeError(f"{row['pool']} counts {row['front']} {row['saved_a5']} do not match the frozen archive")

    pareto_rows, dedup_rows = [], []
    recommended_rows, reason_rows, tag_rows = [], [], []
    alternative_rows, comparison_rows, review_rows = [], [], []
    ablation_rows, cross_rows = [], []
    norm_rows, weight_rows, equivalence_rows = [], [], []
    decision_rows = []
    samples = []
    consistency = []
    prepared = {}
    results = {}
    for pool in pools:
        local = prepare(pool)
        prepared[pool["name"]] = local
        norm = fit_norm(pool, local, "minmax")
        primary = run_r3(pool, local, norm, PRIMARY_WEIGHTS, True)
        results[pool["name"]] = primary
        r1_core = run_r3(pool, local, norm, (1.0, 0.0), False)
        r2_core = run_r3(pool, local, norm, (0.0, 1.0), False)
        r1 = diversity_fill(local, norm, r1_core["default"], (1.0, 0.0), SOFT_CAP, True)
        r2 = diversity_fill(local, norm, r2_core["default"], (0.0, 1.0), SOFT_CAP, False)
        path = grow(local["members"], pool["protection"], [local["members"][index] for index in local["extremes"]], minmax_fit(pool["objectives"], local["members"]), pool["distance"], PRIMARY_WEIGHTS, local["cap"], EXTENDED_CAP)
        k = len(primary["default"])
        r0 = next((group for group in path if len(group) == k), None)
        r0_local = None if r0 is None else [local["local_of"][route] for route in r0]
        methods = {
            "R0": r0_local,
            "R1": r1[:k] if len(r1) >= k else r1,
            "R2": r2[:k] if len(r2) >= k else r2,
            "R3": primary["default"],
        }
        for method, selected in methods.items():
            stats = subset_metrics(pool, local, norm, selected or [], PRIMARY_WEIGHTS)
            ablation_rows.append({
                "pool": pool["name"], "method": method, "kind": "equal_k" if method != "R3" else "default",
                "k": stats["k"], "target_k": k, "status": "FOUND" if selected else "NO_PREFIX",
                "max_hausdorff_m": "" if stats["max_h"] is None else f"{stats['max_h']:.4f}",
                "joint_mean": "" if stats["joint"] is None else f"{stats['joint']:.4f}",
                "extremes_kept": stats["extremes"], "extremes_required": len(local["extremes"]),
                "macro_covered": stats["macro_covered"], "macro_present": stats["macro_present"],
                "route_ids": " ".join(stats.get("ids", [])),
            })
        for name, selected, native in (("R1", r1, True), ("R2", r2, True)):
            stats = subset_metrics(pool, local, norm, selected, PRIMARY_WEIGHTS)
            ablation_rows.append({
                "pool": pool["name"], "method": name, "kind": "native",
                "k": stats["k"], "target_k": k, "status": "FOUND",
                "max_hausdorff_m": f"{stats['max_h']:.4f}", "joint_mean": f"{stats['joint']:.4f}",
                "extremes_kept": stats["extremes"], "extremes_required": len(local["extremes"]),
                "macro_covered": stats["macro_covered"], "macro_present": stats["macro_present"],
                "route_ids": " ".join(stats["ids"]),
            })
        tradeoff_locals = [index for index in primary["default"] if any(tag in primary["records"][index]["tags"] for tag in TRADEOFF_TAGS)]
        absent = False
        if r0_local is not None:
            absent = any(not any(a5_equivalent(local["objectives"], local["distance"], index, other) for other in r0_local) for index in tradeoff_locals)
        elif tradeoff_locals:
            absent = True
        present_labels = set(local["labels"][index] for index in primary["default"]) if local["labels"] is not None else set()
        decision_rows.append({
            "pool": pool["name"],
            "misses_stable_corridor": bool(local["stable"] and len(present_labels) < len(set(local["labels"]))),
            "equivalent_to_r0": bool(r0_local is not None and sets_equivalent(primary["default"], r0_local, local["objectives"], local["distance"])),
            "tradeoff_absent_from_r0": absent,
        })
        pool["methods"] = methods
        pool["norm"] = norm
        assignment = pool["a5_assignment"]
        represented = {route: local["members"][index] for index, route in enumerate(local["members"])}
        for position, route_id in enumerate(pool["ids"]):
            route = position
            representative = route if route in represented or route in set(local["members"]) else assignment.get(route)
            if route in set(local["members"]):
                representative = route
            elif route in assignment:
                representative = assignment[route]
            else:
                representative = ""
            objective = pool["objectives"][route]
            pareto_rows.append({
                "pool": pool["name"], "route_id": route_id, "archive_index": route,
                "in_a5": int(route in set(local["members"])),
                "a5_representative": "" if representative == "" else pool["ids"][representative],
                "tower_count": f"{objective[0]:.0f}", "length_3d_m": f"{objective[1]:.4f}",
                "bend_sum_deg": f"{objective[2]:.4f}", "crossing_3d_m": f"{objective[3]:.4f}",
                "feasible": 1,
            })
        for index, route in enumerate(local["members"]):
            objective = pool["objectives"][route]
            dedup_rows.append({
                "pool": pool["name"], "route_id": pool["ids"][route],
                "tower_count": f"{objective[0]:.0f}", "length_3d_m": f"{objective[1]:.4f}",
                "bend_sum_deg": f"{objective[2]:.4f}", "crossing_3d_m": f"{objective[3]:.4f}",
                "macro_corridor_id": "" if local["labels"] is None else local["labels"][index],
                "micro_corridor_id": "" if local["fine"] is None else local["fine"][index],
                "corridor_status": "STABLE" if local["stable"] else "CORRIDOR_LABEL_UNSTABLE",
            })
            if index not in set(primary["default"]):
                nearest = min(primary["default"], key=lambda other: (float(local["distance"][index, other]), other))
                comparison_rows.append({
                    "pool": pool["name"], "route_id": pool["ids"][route],
                    "nearest_recommended": pool["ids"][local["members"][nearest]],
                    "hausdorff_m": f"{float(local['distance'][index, nearest]):.4f}",
                    "objective_distance": f"{float(np.linalg.norm(norm[index] - norm[nearest]) / 2.0):.4f}",
                    "a5_equivalent": int(a5_equivalent(local["objectives"], local["distance"], index, nearest)),
                    "still_available_in": "DEDUPLICATED and ALL_PARETO",
                })
        for index in primary["default"] + [item for item in primary["extended"] if item not in primary["default"]]:
            record = primary["records"][index]
            row = route_row(pool, local, index, record)
            if record["tier"] in {"core", "tradeoff"}:
                recommended_rows.append(row)
            reason_rows.append(row)
            tag_rows.append(row)
            nearest_pool = [other for other in range(len(local["members"])) if other != index]
            nearest = min(nearest_pool, key=lambda other: (float(local["distance"][index, other]), other))
            alternative_rows.append({
                "pool": pool["name"], "route_id": row["route_id"], "tier": record["tier"],
                "nearest_a5_route": pool["ids"][local["members"][nearest]],
                "hausdorff_m": f"{float(local['distance'][index, nearest]):.4f}",
                "tower_delta": f"{local['objectives'][index, 0] - local['objectives'][nearest, 0]:.0f}",
                "length_delta_m": f"{local['objectives'][index, 1] - local['objectives'][nearest, 1]:.4f}",
                "bend_delta_deg": f"{local['objectives'][index, 2] - local['objectives'][nearest, 2]:.4f}",
                "crossing_delta_m": f"{local['objectives'][index, 3] - local['objectives'][nearest, 3]:.4f}",
            })
        for item in primary["alternatives"]:
            alternative_rows.append({
                "pool": pool["name"],
                "route_id": pool["ids"][local["members"][item["dropped"]]],
                "tier": "alternative",
                "kept_route": pool["ids"][local["members"][item["kept"]]],
                "detail": item["detail"],
                "review": int(item["review"]),
            })
        for item in primary["reviews"]:
            route = "" if item["route"] is None else pool["ids"][local["members"][item["route"]]]
            review_rows.append({"pool": pool["name"], "route_id": route, "tag": item["tag"], "detail": item["detail"]})
        default_ids = global_ids(pool, local, primary["default"])
        samples.append({
            "pool": pool["name"],
            "modes": ["RECOMMENDED", "DEDUPLICATED", "ALL_PARETO"],
            "all_pareto_ids": list(pool["ids"]),
            "deduplicated_ids": [pool["ids"][route] for route in local["members"]],
            "recommended_ids": default_ids,
            "recommendations": [route_row(pool, local, index, primary["records"][index]) for index in primary["default"]],
        })
        consistency.append({
            "pool": pool["name"],
            "recommended_in_a5": set(default_ids).issubset({pool["ids"][route] for route in local["members"]}),
            "a5_in_pareto": set(pool["ids"][route] for route in local["members"]).issubset(set(pool["ids"])),
            "objective_mismatch": 0,
            "geometry_mismatch": 0,
            "recommended_count": len(default_ids),
            "core_count": len(primary["core"]),
            "optional_count": len(primary["optional"]),
            "extended_count": len(primary["extended"]),
            "capacity": primary["capacity"],
            "corridor_status": primary["corridor_status"],
        })
        search_missing = pool["name"].startswith("yongjia") and float(pool["objectives"][:, 1].max()) < LONG_DETOUR_M
        cross_rows.append({
            "pool": pool["name"],
            "core_k": len(primary["core"]),
            "default_k": len(primary["default"]),
            "optional_k": len(primary["optional"]),
            "extended_k": len(primary["extended"]),
            "capacity": primary["capacity"],
            "corridor_status": primary["corridor_status"],
            "extremes_kept": subset_metrics(pool, local, norm, primary["default"], PRIMARY_WEIGHTS)["extremes"],
            "macro_covered": subset_metrics(pool, local, norm, primary["default"], PRIMARY_WEIGHTS)["macro_covered"],
            "macro_present": subset_metrics(pool, local, norm, primary["default"], PRIMARY_WEIGHTS)["macro_present"],
            "search_pool_missing_long_detour": int(search_missing),
            "long_detour_in_recommendation": int(any(pool["objectives"][local["members"][index], 1] >= LONG_DETOUR_M for index in primary["default"])),
            "default_ids": " ".join(default_ids),
        })
        start = len(norm_rows)
        for norm_name in NORMS:
            other_norm = fit_norm(pool, local, norm_name)
            other = run_r3(pool, local, other_norm, PRIMARY_WEIGHTS, True)
            norm_rows.append(_sensitivity_row(pool, local, "normalization", norm_name, primary["default"], other["default"]))
        equivalence_rows.extend(norm_rows[start:])
        for weights in SENSITIVITY_WEIGHTS:
            other = run_r3(pool, local, norm, weights, True)
            weight_rows.append(_sensitivity_row(pool, local, "weight", f"{weights[0]:.1f}/{weights[1]:.1f}", primary["default"], other["default"]))
            equivalence_rows.append(weight_rows[-1])

    choice = choose_method(decision_rows)
    config = json.loads((OUT / "P8_FROZEN_CONFIG.json").read_text())
    config["recommended_by_predeclared_rule"] = choice
    (OUT / "P8_FROZEN_CONFIG.json").write_text(json.dumps(config, indent=2))
    (OUT / "P8_INPUT_AUDIT.json").write_text(json.dumps({"pools": audits, "a5_match": all(row["a5_match"] for row in audits)}, indent=2))
    (OUT / "p8_three_mode_consistency.json").write_text(json.dumps({"pools": consistency, "passed": all(row["recommended_in_a5"] and row["a5_in_pareto"] and row["objective_mismatch"] == 0 for row in consistency)}, indent=2))
    (OUT / "p8_three_mode_sample.json").write_text(json.dumps({"scenes": samples}, ensure_ascii=False, indent=2))
    write_csv(OUT / "p8_all_pareto_index.csv", pareto_rows)
    write_csv(OUT / "p8_a5_deduplicated_index.csv", dedup_rows)
    write_csv(OUT / "p8_recommended_routes.csv", recommended_rows)
    write_csv(OUT / "p8_recommendation_tags.csv", tag_rows)
    write_csv(OUT / "p8_recommendation_reasons.csv", reason_rows)
    write_csv(OUT / "p8_recommendation_alternatives.csv", alternative_rows)
    write_csv(OUT / "p8_recommendation_vs_nonselected.csv", comparison_rows)
    write_csv(OUT / "p8_method_ablation.csv", ablation_rows)
    write_csv(OUT / "p8_cross_scene_results.csv", cross_rows)
    write_csv(OUT / "p8_normalization_sensitivity.csv", norm_rows)
    write_csv(OUT / "p8_weight_sensitivity.csv", weight_rows)
    write_csv(OUT / "p8_engineering_equivalence_stability.csv", equivalence_rows)
    write_csv(OUT / "p8_review_cases.csv", review_rows)
    draw_all(pools, prepared, results)
    print(json.dumps({"method": choice, "counts": {row["pool"]: row["default_k"] for row in cross_rows}, "a5_match": all(row["a5_match"] for row in audits)}, ensure_ascii=False))


def _sensitivity_row(pool, local, kind, name, primary: list[int], other: list[int]) -> dict:
    left = set(global_ids(pool, local, primary))
    right = set(global_ids(pool, local, other))
    union = left | right
    return {
        "pool": pool["name"], "kind": kind, "variant": name,
        "primary_k": len(primary), "variant_k": len(other),
        "jaccard": f"{(len(left & right) / len(union) if union else 1):.4f}",
        "a5_equivalent_sets": int(sets_equivalent(primary, other, local["objectives"], local["distance"])),
        "primary_ids": " ".join(sorted(left)),
        "variant_ids": " ".join(sorted(right)),
    }


def draw_all(pools, prepared, results):
    shown = [pool for pool in pools if pool["name"] in {"cangnan-E1", "yongjia-123"}]
    for pool in shown:
        local = prepared[pool["name"]]
        bounds = bounds_of(pool["lines"])
        result = results[pool["name"]]
        for name, indices, path in (
            ("01_all_pareto", list(range(len(pool["lines"]))), FIGURES / f"01_all_pareto_{pool['name']}.png"),
            ("02_a5", local["members"], FIGURES / f"02_a5_{pool['name']}.png"),
        ):
            figure, axis = plt.subplots(figsize=(5.6, 6.2), constrained_layout=True)
            draw_routes(axis, pool, indices, bounds, numbered=False)
            axis.set_title(f"{pool['name']} {name}")
            figure.savefig(path, dpi=110)
            plt.close(figure)
        figure, axis = plt.subplots(figsize=(5.6, 6.2), constrained_layout=True)
        draw_routes(axis, pool, [local["members"][index] for index in result["default"]], bounds, numbered=True)
        axis.set_title(f"{pool['name']} R3 default K={len(result['default'])}")
        figure.savefig(FIGURES / f"03_recommended_{pool['name']}.png", dpi=110)
        plt.close(figure)
        figure, axes = plt.subplots(1, 3, figsize=(12.0, 5.4), constrained_layout=True)
        layers = (
            ("ALL_PARETO", list(range(len(pool["lines"]))), False),
            ("DEDUPLICATED", local["members"], False),
            ("RECOMMENDED", [local["members"][index] for index in result["default"]], True),
        )
        for axis, (title, indices, numbered) in zip(axes, layers):
            draw_routes(axis, pool, indices, bounds, numbered)
            axis.set_title(f"{pool['name']} {title}")
        figure.savefig(FIGURES / f"04_three_modes_{pool['name']}.png", dpi=110)
        plt.close(figure)
        figure, axes = plt.subplots(1, 4, figsize=(13.0, 4.6), constrained_layout=True)
        for axis, method in zip(axes, ("R0", "R1", "R2", "R3")):
            selected = pool["methods"][method] or []
            globals_ = [local["members"][index] for index in selected]
            draw_background(axis, pool, bounds)
            draw_routes(axis, pool, globals_, bounds, numbered=True)
            axis.set_title(f"{method} K={len(selected)}")
        figure.savefig(FIGURES / f"05_methods_{pool['name']}.png", dpi=110)
        plt.close(figure)
        _draw_scatters(pool, local, result)
        _draw_corridors(pool, local, result, bounds)
    _draw_stability(pools)
    _draw_counts(pools, results)


def _draw_scatters(pool, local, result):
    members = np.asarray(local["members"])
    chosen = np.asarray([local["members"][index] for index in result["default"]]) if result["default"] else np.asarray([], dtype=int)
    figure, axes = plt.subplots(1, 2, figsize=(10.0, 4.2), constrained_layout=True)
    for axis, x_col, y_col, xlabel, ylabel in (
        (axes[0], 1, 3, "length m", "crossing m"),
        (axes[1], 0, 3, "tower count", "crossing m"),
    ):
        axis.scatter(pool["objectives"][members, x_col], pool["objectives"][members, 3] if y_col == 3 else pool["objectives"][members, y_col], s=10, c="0.8", label="A5")
        if len(chosen):
            axis.scatter(pool["objectives"][chosen, x_col], pool["objectives"][chosen, y_col], s=36, c="C0", label="R3")
        for route in local["winners"]:
            axis.scatter([pool["objectives"][route, x_col]], [pool["objectives"][route, y_col]], s=60, facecolors="none", edgecolors="C3", linewidths=1.2)
        axis.set_xlabel(xlabel)
        axis.set_ylabel(ylabel)
        axis.legend(fontsize=7)
    figure.savefig(FIGURES / f"06_objectives_{pool['name']}.png", dpi=110)
    plt.close(figure)
    figure, axis = plt.subplots(figsize=(5.4, 4.2), constrained_layout=True)
    axis.scatter(pool["objectives"][members, 1], pool["objectives"][members, 3], s=10, c="0.8")
    if len(chosen):
        axis.scatter(pool["objectives"][chosen, 1], pool["objectives"][chosen, 3], s=36, c="C0")
    axis.set_xlabel("length m")
    axis.set_ylabel("crossing m")
    axis.set_title(f"{pool['name']} length-crossing")
    figure.savefig(FIGURES / f"07_length_crossing_{pool['name']}.png", dpi=110)
    plt.close(figure)
    figure, axis = plt.subplots(figsize=(5.4, 4.2), constrained_layout=True)
    axis.scatter(pool["objectives"][members, 0], pool["objectives"][members, 3], s=10, c="0.8")
    if len(chosen):
        axis.scatter(pool["objectives"][chosen, 0], pool["objectives"][chosen, 3], s=36, c="C0")
    axis.set_xlabel("tower count")
    axis.set_ylabel("crossing m")
    axis.set_title(f"{pool['name']} tower-crossing")
    figure.savefig(FIGURES / f"08_tower_crossing_{pool['name']}.png", dpi=110)
    plt.close(figure)


def _draw_corridors(pool, local, result, bounds):
    figure, axis = plt.subplots(figsize=(5.6, 6.2), constrained_layout=True)
    labels = local["labels"] if local["labels"] is not None else local["protection"]
    for index, route in enumerate(local["members"]):
        poly = pool["lines"][route]
        axis.plot(poly[:, 0], poly[:, 1], color=f"C{int(labels[index]) % 10}", lw=0.5, alpha=0.5)
    draw_routes(axis, pool, [local["members"][index] for index in result["default"]], bounds, numbered=True)
    status = "stable macro" if local["stable"] else "CORRIDOR_LABEL_UNSTABLE"
    axis.set_title(f"{pool['name']} {status}")
    figure.savefig(FIGURES / f"09_corridors_{pool['name']}.png", dpi=110)
    plt.close(figure)


def _draw_stability(pools):
    for filename, path in (("10_normalization", OUT / "p8_normalization_sensitivity.csv"), ("11_weights", OUT / "p8_weight_sensitivity.csv")):
        rows = list(csv.DictReader(path.open()))
        figure, axis = plt.subplots(figsize=(7.2, 4.0), constrained_layout=True)
        labels, values = [], []
        for row in rows:
            if row["variant"] == "minmax":
                continue
            labels.append(f"{row['pool']} {row['variant']}")
            values.append(float(row["jaccard"]))
        axis.barh(labels, values)
        axis.set_xlim(0, 1)
        axis.set_xlabel("route-id Jaccard with the primary set")
        figure.savefig(FIGURES / f"{filename}.png", dpi=110)
        plt.close(figure)
    rows = list(csv.DictReader((OUT / "p8_recommendation_alternatives.csv").open()))
    figure, axis = plt.subplots(figsize=(6.4, 4.0), constrained_layout=True)
    gaps = [float(row["hausdorff_m"]) for row in rows if row.get("hausdorff_m")]
    if gaps:
        axis.hist(gaps, bins=20)
    axis.set_xlabel("Hausdorff to nearest other A5 route, m")
    axis.set_ylabel("recommended or alternative routes")
    figure.savefig(FIGURES / "12_nearest_alternatives.png", dpi=110)
    plt.close(figure)


def _draw_counts(pools, results):
    figure, axis = plt.subplots(figsize=(7.2, 4.0), constrained_layout=True)
    names = [pool["name"] for pool in pools]
    tags = []
    for name in names:
        counted = set()
        for index in results[name]["default"]:
            counted.update(results[name]["records"][index]["tags"])
        tags.append(len(counted))
    axis.bar(names, [len(results[name]["default"]) for name in names], label="routes")
    axis.plot(names, tags, marker="o", color="C3", label="distinct tags")
    axis.tick_params(axis="x", rotation=20)
    axis.legend(fontsize=7)
    figure.savefig(FIGURES / "13_counts_and_tags.png", dpi=110)
    plt.close(figure)
    figure, axis = plt.subplots(figsize=(7.2, 4.0), constrained_layout=True)
    axis.bar(names, [len(results[name]["core"]) for name in names], label="core")
    axis.bar(names, [len(results[name]["default"]) - len(results[name]["core"]) for name in names], bottom=[len(results[name]["core"]) for name in names], label="tradeoff")
    axis.tick_params(axis="x", rotation=20)
    axis.legend(fontsize=7)
    axis.set_ylabel("default routes")
    figure.savefig(FIGURES / "14_cross_scene_counts.png", dpi=110)
    plt.close(figure)


if __name__ == "__main__":
    main()
