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
    ALGORITHM_VERSION,
    SCHEMA_VERSION,
    build_three_mode,
    legacy_portfolio_message,
    preview_enabled,
)
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
    write_routing_json(directory / ALL_PARETO_NAME, {**header, "routes": geometries, "pareto_complete": True})
    write_routing_json(directory / GROUPS_NAME, {
        "schema_version": SCHEMA_VERSION,
        "engineering_equivalence": False,
        "groups": portfolio["groups"],
    })
    write_routing_json(directory / RECOMMENDATIONS_NAME, {
        "schema_version": SCHEMA_VERSION,
        "method": "R3",
        "recommended_route_ids": [item["route_id"] for item in portfolio["recommendations"]],
        "recommendations": portfolio["recommendations"],
    })
    counts = portfolio["counts"]
    write_routing_json(directory / MANIFEST_NAME, {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "scene_id": header.get("scene_name"),
        "experiment_id": directory.name,
        "data_version": header.get("data_version"),
        "algorithm_version": ALGORITHM_VERSION,
        "source_revision": provenance.get("source_revision"),
        "all_pareto_count": counts["all_pareto"],
        "a5_group_count": counts["a5_groups"],
        "recommended_count": counts["recommended"],
        "files": {
            "all_pareto": {"name": ALL_PARETO_NAME, "source": "result.pareto_indices"},
            "groups": {"name": GROUPS_NAME, "source": "frozen A5 on this front"},
            "recommendations": {"name": RECOMMENDATIONS_NAME, "source": "frozen R3 on A5 representatives"},
            "published": {"name": "routes.json", "source": "result.published_indices"},
        },
        "subset": "RECOMMENDED ⊆ A5_REPRESENTATIVES ⊆ ALL_PARETO",
        "corridor_status": portfolio.get("corridor_status"),
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


def write_three_mode_outputs(directory: Path, problem: RoutingProblem, result: RoutingResult,
                             form: dict, metadata: dict, reporter=None) -> dict | None:
    """Write the full front after routes.json. A failure here does not remove that file."""
    if not preview_enabled():
        return None
    started = time.perf_counter()
    header = {
        "schema_version": 1, "problem_type": "routing", "scene_name": form["scene_name"],
        "frame": header_frame(problem), "data_version": metadata["data_version"],
    }
    repository = Path(__file__).resolve().parents[1]
    try:
        geometries, portfolio = build_from_result(problem, result, form, reporter)
        write_three_mode_documents(directory, header, geometries, portfolio, {
            "source_revision": _revision(repository),
            "retention": (
                "自动选线结果仍只保留每个场景最近 2 次已完成任务。"
                "本次三层文件随该任务目录保存，不表示更早的自动任务会被永久留下。"
            ),
        })
    except Exception as exc:
        logger.exception("three-mode preview failed after routes.json was written")
        write_routing_json(directory / MANIFEST_NAME, {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "scene_id": form["scene_name"],
            "experiment_id": directory.name,
            "message": f"三层结果没有生成：{exc}",
            "published_file": "routes.json",
        })
        return {"status": "failed", "seconds": time.perf_counter() - started}
    seconds = time.perf_counter() - started
    summary_path = directory / "run_summary.json"
    if summary_path.is_file():
        import json
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["three_mode_preview"] = True
        summary["three_mode_seconds"] = seconds
        summary["three_mode_counts"] = portfolio["counts"]
        write_routing_json(summary_path, summary)
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
    portfolio = build_three_mode([item["id"] for item in geometries], objectives, lines)
    return geometries, portfolio
