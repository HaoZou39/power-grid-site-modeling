"""Explicit real-scene acceptance; never chooses connection points or changes scene data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource

import numpy as np

from experiments.launch_routing_run import launch_routing_run, problem_from_snapshot
from experiments.routing_output import write_routing_json
from experiments.scene_store import scene_directory, scenes_root
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import OBJECTIVE_NAMES, Route
from config.routing_task import RoutingRunConfig


def validate_routing(task: RoutingRunConfig, output_root: Path, *, repeat: bool) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    report = lambda progress, stage, message: print(f"{progress:.0%} {stage}: {message}", flush=True)
    directory = launch_routing_run(task, report, output_root=output_root / "runs")
    metadata = json.loads((directory / "data_metadata.json").read_text())
    saved = json.loads((directory / "routes.json").read_text())
    summary = json.loads((directory / "run_summary.json").read_text())
    problem = problem_from_snapshot(directory / "scene_snapshot", task, metadata)
    evaluator = RouteEvaluator(problem)
    checked = 0
    for record in saved["routes"]:
        if not record["is_feasible"]:
            continue
        towers = np.array([[point["x"], point["y"]] for point in record["points"] if point["role"] == "tower"]).reshape(-1, 2)
        result = evaluator.evaluate(Route(towers))
        if not result.is_feasible:
            raise AssertionError(f"published route fails hard checks: {record['id']}")
        np.testing.assert_allclose(result.objectives, [record["objectives"][name] for name in OBJECTIVE_NAMES], rtol=0, atol=1e-9)
        checked += 1
    source = scene_directory(scenes_root(), task.scene_name)
    for name, expected in metadata["input_hashes"].items():
        with (source / name).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise AssertionError(f"source scene changed: {name}")
        original, snapshot = (source / name).stat(), (directory / "scene_snapshot" / name).stat()
        if (original.st_dev, original.st_ino) == (snapshot.st_dev, snapshot.st_ino):
            raise AssertionError(f"mutable scene hardlink: {name}")
    reproduced = None
    if repeat:
        replay = launch_routing_run(task.model_copy(update={"experiment_name": task.experiment_name + "-repeat"}), report,
                                    output_root=output_root / "runs")
        reproduced = (replay / "routes.json").read_bytes() == (directory / "routes.json").read_bytes()
        if not reproduced:
            raise AssertionError("same-seed routing artifacts did not reproduce")
    result = {"passed": checked > 0, "scene_name": task.scene_name, "output_dir": str(directory), "shape": problem.dem.shape,
        "checked_feasible": checked, "hard_violation_count": 0, "source_hashes_unchanged": True,
        "independent_snapshot": True, "same_seed_reproduced": reproduced,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, "summary": summary}
    write_routing_json(output_root / "verified.json", result)
    if not checked:
        raise AssertionError("no feasible route found in this acceptance task; diagnostics retained")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repeat", action="store_true")
    args = parser.parse_args()
    task = RoutingRunConfig.model_validate(json.loads(args.config.read_text()))
    result = validate_routing(task, args.output_root, repeat=args.repeat)
    print(json.dumps({name: result[name] for name in ("scene_name", "checked_feasible", "peak_rss_mib", "same_seed_reproduced")}))


if __name__ == "__main__":
    main()
