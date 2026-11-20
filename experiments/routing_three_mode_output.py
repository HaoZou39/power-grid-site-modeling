"""Additive three-mode files. routes.json stays the published front."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import time
from pathlib import Path

import numpy as np

from algorithms.routing.three_mode import (
    SCHEMA_VERSION,
    build_filtered_portfolio,
    legacy_portfolio_message,
)
from config.project_config import load_default_config
from algorithms.routing.types import RoutingResult
from experiments.routing_output import json_safe, write_routing_json
from modeling.routing.context import RoutingProblem
from modeling.routing.evaluator import RouteEvaluator, tower_cache_budget
from modeling.routing.geometry import turn_angles
from modeling.routing.types import OBJECTIVE_NAMES

logger = logging.getLogger("site-modeling.routing-three-mode")
ALL_PARETO_NAME = "routes_all_pareto.json"
GROUPS_NAME = "routing_a5_groups.json"
RECOMMENDATIONS_NAME = "routing_recommendations.json"
MANIFEST_NAME = "routing_portfolio_manifest.json"


def _revision(repository: Path) -> str | None:
    commit = os.getenv("SOURCE_REVISION")
    if commit is None and (repository / ".git").exists():
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=True,
        ).stdout.strip()
    return commit


def route_geometry(problem: RoutingProblem, route, evaluation, route_id: str, reported) -> dict:
    points = route.points(problem.start, problem.end)
    return json_safe({
        "id": route_id,
        "objectives": dict(zip(OBJECTIVE_NAMES, evaluation.objectives)),
        "is_feasible": evaluation.is_feasible,
        "is_pareto": True,
        "violations": evaluation.violations,
        "points": [
            {"x": float(point[0]), "y": float(point[1]), "z": None if z is None else float(z),
             "role": "start" if index == 0 else "end" if index == len(points) - 1 else "tower"}
            for index, (point, z) in enumerate(zip(points, reported.elevations))
        ],
        "spans": reported.spans,
        "turns_deg": np.degrees(turn_angles(points)),
        "tower_slopes_deg": reported.tower_slopes_deg,
    })


def write_three_mode_documents(directory: Path, header: dict, geometries: list[dict], portfolio: dict, provenance: dict) -> None:
    identities = [item["id"] for item in geometries]
    if len(identities) != len(set(identities)):
        raise RuntimeError("full Pareto route ids are not unique")
    by_id = {item["id"]: item for item in geometries}
    for group in portfolio["groups"]:
        for route_id in group["member_route_ids"]:
            if route_id not in by_id:
                raise RuntimeError(f"group member {route_id} has no saved geometry")
    for item in portfolio["recommendations"]:
        if item["route_id"] not in by_id:
            raise RuntimeError(f"recommendation {item['route_id']} has no saved geometry")
    filtered = list(portfolio["filtered_route_ids"])
    representatives = {group["representative_route_id"] for group in portfolio["groups"]}
    if set(filtered) != representatives or any(route_id not in by_id for route_id in filtered):
        raise RuntimeError("filtered routes are not saved A5 representatives")
    for geometry, value in zip(geometries, portfolio["tortuosity_k"], strict=True):
        geometry["tortuosity_k"] = value
        geometry["tortuosity_status"] = "invalid" if value is None else "ok"
    write_routing_json(directory / ALL_PARETO_NAME, {**header, "routes": geometries, "pareto_complete": True})
    write_routing_json(directory / GROUPS_NAME, {
        "schema_version": SCHEMA_VERSION,
        "engineering_equivalence": False,
        "groups": portfolio["groups"],
    })
    write_routing_json(directory / RECOMMENDATIONS_NAME, {
        "schema_version": SCHEMA_VERSION,
        "method": "unused",
        "recommended_route_ids": [],
        "recommendations": [],
        "note": "展示不再使用推荐算法。文件保留，避免旧目录缺这个名字。",
    })
    counts = portfolio["counts"]
    limit = portfolio["max_tortuosity"]
    write_routing_json(directory / MANIFEST_NAME, {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "scene_id": header.get("scene_name"),
        "experiment_id": directory.name,
        "data_version": header.get("data_version"),
        "algorithm_version": f"A5-hausdorff20-tower0-length30-bend3-crossing10+tortuosity<={limit:g}-before-a5",
        "source_revision": provenance.get("source_revision"),
        "all_pareto_count": counts["all_pareto"],
        "filtered_count": counts["filtered"],
        "filtered_route_ids": filtered,
        "max_tortuosity": limit,
        "tortuosity_eligible_count": counts["tortuosity_eligible"],
        "tortuosity_rejected_count": counts["tortuosity_rejected"],
        "tortuosity_invalid_count": counts["tortuosity_invalid"],
        "a5_group_count": counts["a5_groups"],
        "recommended_count": None,
        "files": {
            "all_pareto": {"name": ALL_PARETO_NAME, "source": "result.pareto_indices"},
            "groups": {"name": GROUPS_NAME, "source": "A5 after the tortuosity limit, trace only"},
            "recommendations": {"name": RECOMMENDATIONS_NAME, "source": "unused by the two-mode display"},
            "published": {"name": "routes.json", "source": "result.published_indices"},
        },
        "subset": "FILTERED ⊆ TORTUOSITY_ELIGIBLE ⊆ ALL_PARETO",
        "retention": provenance.get("retention"),
        "python_version": platform.python_version(),
    })


def write_legacy_manifest(directory: Path, scene_name: str, published_count: int, recorded_pareto_count: int | None) -> None:
    write_routing_json(directory / MANIFEST_NAME, {
        "schema_version": SCHEMA_VERSION,
        "status": "legacy_published_only",
        "scene_id": scene_name,
        "experiment_id": directory.name,
        "all_pareto_count": None,
        "a5_group_count": None,
        "recommended_count": None,
        "published_count": published_count,
        "recorded_pareto_count": recorded_pareto_count,
        "message": legacy_portfolio_message(published_count, recorded_pareto_count),
        "files": {"published": {"name": "routes.json", "source": "historical published routes"}},
    })


def display_completion_message(outcome: dict | None) -> str:
    if outcome and outcome.get("status") == "failed":
        detail = outcome.get("message") or "筛选方案没有生成。"
        return f"优化已完成，已发布线路已保存。{detail}"
    return "优化已完成。已发布线路、完整帕累托前沿和筛选方案已保存。"


def _record_display_stages(directory: Path, *, all_pareto_saved: bool, filtered_saved: bool,
                           seconds: float, message: str | None = None, counts: dict | None = None) -> None:
    summary_path = directory / "run_summary.json"
    if not summary_path.is_file():
        return
    import json
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["optimization_completed"] = True
    summary["published_routes_saved"] = (directory / "routes.json").is_file()
    summary["all_pareto_saved"] = all_pareto_saved
    summary["filtered_saved"] = filtered_saved
    summary["three_mode"] = all_pareto_saved and filtered_saved
    summary["three_mode_status"] = "complete" if summary["three_mode"] else "failed"
    summary["three_mode_seconds"] = seconds
    if counts is not None:
        summary["three_mode_counts"] = counts
    if message:
        summary["three_mode_message"] = message
    write_routing_json(summary_path, summary)


def write_three_mode_outputs(directory: Path, problem: RoutingProblem, result: RoutingResult,
                             form: dict, metadata: dict, reporter=None) -> dict:
    """Write the full front after routes.json. A failure here does not remove that file."""
    started = time.perf_counter()
    repository = Path(__file__).resolve().parents[1]
    try:
        geometries, portfolio = build_from_result(problem, result, form, reporter)
        header = {
            "schema_version": 1, "problem_type": "routing", "scene_name": form["scene_name"],
            "frame": header_frame(problem), "data_version": metadata["data_version"],
        }
        write_three_mode_documents(directory, header, geometries, portfolio, {
            "source_revision": _revision(repository),
            "retention": (
                "自动选线结果仍只保留每个场景最近 2 次已完成任务。"
                "完整帕累托前沿和筛选方案随该任务目录保存，不表示更早的自动任务会被永久留下。"
            ),
        })
    except Exception as exc:
        logger.exception("filtered portfolio output failed after routes.json was written")
        seconds = time.perf_counter() - started
        message = f"筛选方案没有生成：{exc}"
        write_routing_json(directory / MANIFEST_NAME, {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "scene_id": form["scene_name"],
            "experiment_id": directory.name,
            "message": message,
            "optimization_completed": True,
            "published_routes_saved": (directory / "routes.json").is_file(),
            "all_pareto_saved": False,
            "filtered_saved": False,
            "published_file": "routes.json",
        })
        _record_display_stages(directory, all_pareto_saved=False, filtered_saved=False, seconds=seconds, message=message)
        return {"status": "failed", "seconds": seconds, "message": message}
    seconds = time.perf_counter() - started
    _record_display_stages(
        directory, all_pareto_saved=True, filtered_saved=True, seconds=seconds, counts=portfolio["counts"],
    )
    return {"status": "complete", "seconds": seconds, "counts": portfolio["counts"]}


def header_frame(problem: RoutingProblem) -> dict:
    from dataclasses import asdict
    return asdict(problem.frame)


def build_from_result(problem: RoutingProblem, result: RoutingResult, form: dict, reporter=None):
    pareto = list(result.pareto_indices)
    evaluator = RouteEvaluator(problem).cache_geometry_checks(
        tower_cache_budget(problem, form["algorithm"]["context_cache_mib"]),
    )
    geometries = []
    lines = []
    objectives = np.empty((len(pareto), len(OBJECTIVE_NAMES)), dtype=float)
    batch = max(int(form["algorithm"]["evaluation_batch_size"]), 1)
    for position, index in enumerate(pareto):
        if reporter is not None and position % batch == 0:
            reporter(0.98, "report", f"正在写出完整帕累托线路 {position}/{len(pareto)}")
        route = result.routes[index]
        saved = result.evaluations[index]
        reported = evaluator.evaluate(route, report=saved.is_feasible)
        if reported.is_feasible != saved.is_feasible or not np.allclose(
            reported.objectives, saved.objectives, rtol=1e-10, atol=1e-8,
        ):
            raise RuntimeError("full Pareto report disagrees with search validation")
        route_id = f"route-{index + 1:06d}"
        geometries.append(route_geometry(problem, route, saved, route_id, reported))
        lines.append(np.asarray(route.points(problem.start, problem.end)[:, :2], dtype=float))
        objectives[position] = saved.objectives
    if len(objectives):
        objectives[:, 2] = np.degrees(objectives[:, 2])
    limit = load_default_config().routing_result.max_tortuosity
    portfolio = build_filtered_portfolio([item["id"] for item in geometries], objectives, lines, max_tortuosity=limit)
    return geometries, portfolio
