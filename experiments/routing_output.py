"""Versioned routing records, without site-only fields or invented normalization."""

from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import platform
import subprocess

import numpy as np
import torch

from algorithms.routing.search import RoutingResult
from experiments.output_writer import write_csv
from modeling.routing.context import RoutingProblem
from modeling.routing.geometry import turn_angles
from modeling.routing.types import OBJECTIVE_NAMES


def json_safe(value):
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def write_routing_json(path: Path, value) -> None:
    path.write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def write_routing_outputs(directory: Path, problem: RoutingProblem, result: RoutingResult,
                          form: dict, metadata: dict, elapsed_s: float) -> None:
    records, geometries = [], []
    front = set(result.pareto_indices)
    for index, (route, evaluation) in enumerate(zip(result.routes, result.evaluations)):
        route_id = f"route-{index + 1:06d}"
        record = {"route_id": route_id, **dict(zip(OBJECTIVE_NAMES, evaluation.objectives)),
            "is_feasible": evaluation.is_feasible, "is_pareto": index in front, **evaluation.violations}
        records.append(json_safe(record))
        points = route.points(problem.start, problem.end)
        geometries.append({"id": route_id, "objectives": dict(zip(OBJECTIVE_NAMES, evaluation.objectives)),
            "is_feasible": evaluation.is_feasible, "is_pareto": index in front,
            "violations": evaluation.violations,
            "points": [{"x": point[0], "y": point[1], "z": z,
                "role": "start" if i == 0 else "end" if i == len(points) - 1 else "tower"}
                for i, (point, z) in enumerate(zip(points, evaluation.elevations))],
            "spans": evaluation.spans, "turns_deg": np.degrees(turn_angles(points)),
            "tower_slopes_deg": evaluation.tower_slopes_deg})
    fields = list(records[0]) if records else ["route_id", *OBJECTIVE_NAMES, "is_feasible", "is_pareto"]
    write_csv(directory / "solutions.csv", records, fields)
    write_csv(directory / "pareto_solutions.csv", [record for record in records if record["is_pareto"]], fields)
    write_routing_json(directory / "routes.json", {"schema_version": 1, "problem_type": "routing",
        "scene_name": form["scene_name"], "frame": asdict(problem.frame), "data_version": metadata["data_version"], "routes": geometries})
    repository = Path(__file__).resolve().parents[1]
    commit = os.getenv("SOURCE_REVISION")
    if commit is None and (repository / ".git").exists():
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=True).stdout.strip()
    write_routing_json(directory / "run_summary.json", {"schema_version": 1, "problem_type": "routing",
        "algorithm": "routing_nsga2", "scene_name": form["scene_name"], "experiment_name": form["experiment_name"],
        "objective_names": OBJECTIVE_NAMES, "n_solutions": len(records),
        "n_feasible": sum(record["is_feasible"] for record in records), "n_pareto": len(front),
        "no_feasible_solution": not front, "tower_count_lower": result.lower,
        "initial_tower_upper": result.initial_upper, "final_tower_upper": result.final_upper,
        "expansions": result.expansions, "evaluation_count": result.evaluation_count,
        "validation_evaluations": sum(record["is_feasible"] for record in records),
        "stop_reason": result.stop_reason, "elapsed_s": elapsed_s, "clearance_status": "净空未校核",
        "execution": "CPU", "git_commit": commit, "python_version": platform.python_version(),
        "numpy_version": np.__version__, "torch_version": torch.__version__})
