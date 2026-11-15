"""Three-mode preview: frozen A5 groups, frozen R3, and additive files."""

import json
from pathlib import Path

import numpy as np

from algorithms.routing.three_mode import LEGACY_PORTFOLIO_MESSAGE, build_three_mode, legacy_portfolio_message
from experiments.routing_three_mode_output import write_legacy_manifest, write_three_mode_documents

ROOT = Path(__file__).resolve().parents[1]


def _front():
    ids = ["route-000001", "route-000002", "route-000003", "route-000004", "route-000005"]
    objectives = np.array([
        [5, 1000, 10, 50],
        [6, 900, 20, 80],
        [7, 1100, 5, 70],
        [9, 1200, 30, 20],
        [5, 1005, 10.2, 52],
    ], dtype=float)
    lines = [np.array([[0.0, 0.0], [10.0, float(index)], [20.0, 0.0]]) for index in range(5)]
    distance = np.full((5, 5), 100.0)
    np.fill_diagonal(distance, 0.0)
    distance[0, 4] = distance[4, 0] = 1.0
    return ids, objectives, lines, distance


def test_three_mode_write_does_not_read_a_preview_flag():
    import algorithms.routing.three_mode as three_mode
    assert not hasattr(three_mode, "preview_enabled")
    assert legacy_portfolio_message(12, 400) == LEGACY_PORTFOLIO_MESSAGE
    assert "12" not in LEGACY_PORTFOLIO_MESSAGE
    assert "400" not in LEGACY_PORTFOLIO_MESSAGE


def test_a5_partition_and_r3_subset():
    ids, objectives, lines, distance = _front()
    portfolio = build_three_mode(ids, objectives, lines, distance=distance, shape={"stable": False, "macro": np.zeros(5), "macro_m": 0})
    members = [route for group in portfolio["groups"] for route in group["member_route_ids"]]
    assert sorted(members) == sorted(ids)
    assert all(group["representative_route_id"] in group["member_route_ids"] for group in portfolio["groups"])
    assert all(group["engineering_review_status"] == "NOT_REVIEWED" for group in portfolio["groups"])
    assert all("CROSSING_OBJECTS_DATA_MISSING" in group["group_risk_flags"] for group in portfolio["groups"])
    assert portfolio["counts"] == {"all_pareto": 5, "a5_groups": 4, "recommended": 4}
    recommended = {item["route_id"] for item in portfolio["recommendations"]}
    representatives = {group["representative_route_id"] for group in portfolio["groups"]}
    assert recommended <= representatives <= set(ids)
    assert "route-000005" not in recommended
    assert any(group["member_route_ids"] == ["route-000001", "route-000005"] or set(group["member_route_ids"]) == {"route-000001", "route-000005"} for group in portfolio["groups"])


def test_documents_do_not_replace_published_routes(tmp_path):
    published = tmp_path / "routes.json"
    published.write_text('{"routes":[{"id":"route-000001"}]}', encoding="utf-8")
    before = published.read_bytes()
    ids, objectives, lines, distance = _front()
    portfolio = build_three_mode(ids, objectives, lines, distance=distance, shape={"stable": False, "macro": np.zeros(5), "macro_m": 0})
    geometries = [{"id": route_id, "objectives": {"tower_count": 1, "length_3d_m": 2, "bend_sum_rad": 3, "crossing_3d_m": 4}} for route_id in ids]
    write_three_mode_documents(tmp_path, {"schema_version": 1, "scene_name": "scene"}, geometries, portfolio, {"source_revision": "abc", "retention": "keep newest 2"})
    assert published.read_bytes() == before
    manifest = json.loads((tmp_path / "routing_portfolio_manifest.json").read_text())
    assert manifest["all_pareto_count"] == 5
    assert manifest["a5_group_count"] == 4
    assert manifest["recommended_count"] == 4
    assert manifest["files"]["published"]["name"] == "routes.json"
    saved_ids = [item["id"] for item in json.loads((tmp_path / "routes_all_pareto.json").read_text())["routes"]]
    assert saved_ids == ids


def test_legacy_manifest_does_not_invent_a_front(tmp_path):
    write_legacy_manifest(tmp_path, "scene", 12, 400)
    manifest = json.loads((tmp_path / "routing_portfolio_manifest.json").read_text())
    assert manifest["status"] == "legacy_published_only"
    assert manifest["all_pareto_count"] is None
    assert manifest["message"] == LEGACY_PORTFOLIO_MESSAGE
    assert not (tmp_path / "routes_all_pareto.json").exists()
    assert "12" not in manifest["message"]


def _historical_case(name, ids, objectives, lines, distance):
    from algorithms.routing.three_mode import _column_winners, _verified, corridor_shape
    rules, _p4, _p8, _grouping, _towers = _verified()
    shape = corridor_shape(lines)
    portfolio = build_three_mode(ids, objectives, lines, distance=distance, shape=shape)
    winners = _column_winners(objectives, rules.normalized_sum)
    kept, _assignment = rules.a5_keep(distance, objectives, list(dict.fromkeys(winners)))
    kept_portfolio = build_three_mode(
        ids, objectives, lines, distance=distance, shape=shape, representative_order=list(kept),
    )
    reversed_portfolio = build_three_mode(
        ids, objectives, lines, distance=distance, shape=shape, representative_order=list(reversed(kept)),
    )
    return name, portfolio, kept_portfolio, reversed_portfolio


def test_historical_fronts_are_independent_of_representative_order():
    # Exact ties use the original front index. The published P8 Yongjia files
    # used a5_keep insertion order instead, so those two counts stay different.
    expected = {
        "cangnan-E1": {"all_pareto": 449, "a5_groups": 46, "recommended": 5},
        "cangnan-E4": {"all_pareto": 428, "a5_groups": 47, "recommended": 5},
        "yongjia-123": {"all_pareto": 701, "a5_groups": 242, "recommended": 10},
        "yongjia-124": {"all_pareto": 976, "a5_groups": 288, "recommended": 7},
        "yongjia-125": {"all_pareto": 671, "a5_groups": 161, "recommended": 6},
    }
    front_index_ids = {
        "yongjia-123": [
            "s123-300039", "s123-272605", "s123-307427", "s123-91152", "s123-306276",
            "s123-251850", "s123-297384", "s123-144616", "s123-303635", "s123-288710",
        ],
        "yongjia-124": [
            "s124-107708", "s124-295121", "s124-211164", "s124-88977", "s124-285060",
            "s124-167969", "s124-75011",
        ],
    }
    published_p8_ids = {
        "yongjia-123": [
            "s123-300039", "s123-272605", "s123-307427", "s123-91152", "s123-306276",
            "s123-252790", "s123-297384", "s123-144616", "s123-288710",
        ],
        "yongjia-124": [
            "s124-107708", "s124-295121", "s124-211164", "s124-88977", "s124-285060", "s124-167969",
        ],
    }
    for name, portfolio, kept_portfolio, reversed_portfolio in _historical_portfolios():
        assert portfolio["counts"] == expected[name]
        recommended = [item["route_id"] for item in portfolio["recommendations"]]
        assert [item["route_id"] for item in kept_portfolio["recommendations"]] == recommended
        assert [item["route_id"] for item in reversed_portfolio["recommendations"]] == recommended
        if name in front_index_ids:
            assert recommended == front_index_ids[name]
            assert recommended != published_p8_ids[name]


def _historical_portfolios():
    cangnan_fronts = ROOT / "diagnostics/CANGNAN_EPSILON_S1_S2_COMPARISON/s2_runs"
    cangnan_distance = ROOT / "diagnostics/CANGNAN_ENGINEERING_PREFERENCE_PORTFOLIO"
    for level in ("E1", "E4"):
        archive = np.load(cangnan_fronts / level / "exact_pareto.npz")
        objectives = archive["objectives"].astype(float)
        objectives[:, 2] = np.degrees(objectives[:, 2])
        offsets = archive["offsets"]
        lines = [archive["xy"][int(start):int(stop)].copy() for start, stop in zip(offsets[:-1], offsets[1:])]
        ids = [f"{level}-{int(index)}" for index in archive["route_index"]]
        distance = np.load(cangnan_distance / f"hausdorff_{level}.npy")
        yield _historical_case(f"cangnan-{level}", ids, objectives, lines, distance)
    yongjia = ROOT / "diagnostics/ROUTING_THREE_OBJECTIVE_REOPTIMIZATION/runs"
    hausdorff = ROOT / "diagnostics/YONGJIA_P5_FROZEN_TRANSFER"
    for seed, count_name in ((123, "yongjia-123"), (124, "yongjia-124"), (125, "yongjia-125")):
        archive = np.load(yongjia / f"E0_seed{seed}" / "exact_pareto.npz")
        objectives = archive["objectives"].astype(float)
        objectives[:, 2] = np.degrees(objectives[:, 2])
        offsets = archive["offsets"]
        lines = [archive["xy"][int(start):int(stop)].copy() for start, stop in zip(offsets[:-1], offsets[1:])]
        ids = [f"s{seed}-{int(index)}" for index in archive["route_index"]]
        distance = np.load(hausdorff / f"hausdorff_s{seed}.npy")
        yield _historical_case(count_name, ids, objectives, lines, distance)
