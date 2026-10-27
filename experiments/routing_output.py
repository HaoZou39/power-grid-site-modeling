"""Versioned routing records, without site-only fields or invented normalization."""

from dataclasses import asdict
import json
import hashlib
import math
import os
from pathlib import Path
import platform
import subprocess
import time

import numpy as np
import torch

from algorithms.routing.search import RoutingResult
from experiments.output_writer import write_csv
from modeling.routing.context import RoutingProblem
from modeling.routing.evaluator import RouteEvaluator, tower_cache_budget
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
                          form: dict, metadata: dict, elapsed_s: float, *, timings: dict | None = None, reporter=None) -> None:
    write_started = time.perf_counter()
    front = set(result.pareto_indices)

    def solution_record(index, evaluation):
        route_id = f"route-{index + 1:06d}"
        return json_safe({"route_id": route_id, **dict(zip(OBJECTIVE_NAMES, evaluation.objectives)),
            "is_feasible": evaluation.is_feasible, "is_pareto": index in front, **evaluation.violations})

    records = lambda: (solution_record(i, value) for i, value in enumerate(result.evaluations))
    fields = list(solution_record(0, result.evaluations[0])) if result.evaluations else ["route_id", *OBJECTIVE_NAMES, "is_feasible", "is_pareto"]
    write_csv(directory / "solutions.csv", records(), fields)
    write_csv(directory / "pareto_solutions.csv", (record for record in records() if record["is_pareto"]), fields)
    header = {"schema_version": 1, "problem_type": "routing", "scene_name": form["scene_name"],
              "frame": asdict(problem.frame), "data_version": metadata["data_version"]}
    evaluator = RouteEvaluator(problem).cache_geometry_checks(tower_cache_budget(problem, form["algorithm"]["context_cache_mib"]))
    with (directory / "routes.json").open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(json_safe(header), ensure_ascii=False, allow_nan=False)[:-1] + ', "routes": [\n')
        for index, (route, saved) in enumerate(zip(result.routes, result.evaluations)):
            if reporter is not None and index % form["algorithm"]["evaluation_batch_size"] == 0:
                reporter(.9 + .08 * index / len(result.routes), "report", f"正在逐批写出完整线路报告 {index}/{len(result.routes)}")
            evaluation = evaluator.evaluate(route, report=saved.is_feasible)
            if evaluation.is_feasible != saved.is_feasible or not np.allclose(evaluation.objectives, saved.objectives, rtol=1e-10, atol=1e-8):
                raise RuntimeError("routing output disagrees with search validation")
            points = route.points(problem.start, problem.end)
            geometry = {"id": f"route-{index + 1:06d}", "objectives": dict(zip(OBJECTIVE_NAMES, saved.objectives)),
                "is_feasible": saved.is_feasible, "is_pareto": index in front, "violations": saved.violations,
                "points": [{"x": point[0], "y": point[1], "z": z,
                    "role": "start" if i == 0 else "end" if i == len(points) - 1 else "tower"}
                    for i, (point, z) in enumerate(zip(points, evaluation.elevations))],
                "spans": evaluation.spans, "turns_deg": np.degrees(turn_angles(points)),
                "tower_slopes_deg": evaluation.tower_slopes_deg}
            if index:
                stream.write(',\n')
            json.dump(json_safe(geometry), stream, ensure_ascii=False, allow_nan=False)
        stream.write('\n]}\n')
    repository = Path(__file__).resolve().parents[1]
    commit = os.getenv("SOURCE_REVISION")
    if commit is None and (repository / ".git").exists():
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=True).stdout.strip()
    sources = [*repository.glob("algorithms/routing/*.py"), *repository.glob("modeling/routing/*.py")]
    sources.extend(repository / name for name in ("algorithms/common/nsga2.py", "algorithms/common/tensor_nsga2.py", "algorithms/common/pareto.py",
        "modeling/context.py", "config/project_config.py", "config/default_config.json",
        "experiments/launch_routing_run.py", "experiments/routing_output.py", "plugins/routing_plugin.py"))
    source_hashes = {str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(sources)}
    output_s = time.perf_counter() - write_started
    write_routing_json(directory / "run_summary.json", {"schema_version": 1, "problem_type": "routing",
        "algorithm": "routing_nsga2", "scene_name": form["scene_name"], "experiment_name": form["experiment_name"],
        "objective_names": OBJECTIVE_NAMES, "n_solutions": len(result.routes),
        "n_feasible": sum(record["is_feasible"] for record in records()), "n_pareto": len(front),
        "no_feasible_solution": not front, "tower_count_lower": result.lower,
        "initial_tower_upper": result.initial_upper, "final_tower_upper": result.final_upper,
        "expansions": result.expansions, "evaluation_count": result.evaluation_count,
        "generation_count": result.generation_count, "initialization_evaluations": result.initialization_evaluations,
        "validation_evaluations": sum(record["is_feasible"] for record in records()),
        "output_evaluations": len(result.routes),
        "stop_reason": result.stop_reason, "elapsed_s": elapsed_s + output_s, "clearance_status": "净空未校核",
        "execution": "CPU" if result.execution.get("devices", ["cpu"]) == ["cpu"] else "CUDA + CPU exact checks",
        "execution_details": result.execution, "git_commit": commit, "python_version": platform.python_version(),
        "numpy_version": np.__version__, "torch_version": torch.__version__, "source_hashes": source_hashes,
        "timings": {**(timings or {}), "output_s": output_s}})
