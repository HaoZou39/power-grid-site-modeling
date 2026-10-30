"""Correctness-only real-scene migration probes, with explicit stage configuration."""

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import time

from config.project_config import load_default_config
from config.routing_task import RoutingRunConfig
from experiments.benchmark_routing import benchmark


def stage_manifest(task_paths, mechanisms, mode, seed, evaluations):
    base = load_default_config().routing
    pilot = replace(base.pilot, enabled_mechanisms=mechanisms, initialization_mode=mode)
    cfg = replace(base, search_strategy="pilot_reference", evolution_backend="numpy", devices=["cpu"],
                  evaluation_backend="compiled_cpu", popsize=4, max_generations=2,
                  max_evaluations=evaluations, pilot=pilot)
    return {"tasks": [{"id": Path(p).stem, "config": p} for p in task_paths], "cases": [{"name": "migrated", "routing": asdict(cfg)}],
            "seeds": [seed], "warmups": 0, "repeats": 1, "time_checkpoints_s": [], "report_quality": False}


def validate_job(task_path, manifest, output):
    output.mkdir(exist_ok=True)
    if (output / "job-validation.json").exists():
        raise FileExistsError(output / "job-validation.json")
    from unittest.mock import patch
    with patch.dict(os.environ, {
        "FAVORITES_DB_PATH": str((output / "favorites.sqlite3").resolve()),
        "EXPERIMENT_OUTPUT_ROOT": str(output.resolve()),
    }):
        from fastapi.testclient import TestClient
        from backend.app.main import create_app
        task = RoutingRunConfig.model_validate(json.loads(Path(task_path).read_text()))
        cfg = manifest["cases"][0]["routing"]
        task = task.model_copy(update={"experiment_name": "cpu-components-job", "algorithm": task.algorithm.model_validate(cfg)})
        with TestClient(create_app(database_url="sqlite://:memory:", redis_url="", experiment_root=str(output),
                                   favorite_db_path=output / "favorites.sqlite3")) as client:
            response = client.post("/api/v1/jobs", json={"plugin_id": "routing.nsga2", "config": task.model_dump(mode="json")})
            response.raise_for_status();job_id = response.json()["job_id"]
            deadline = time.monotonic() + 600
            while True:
                job = client.get("/api/v1/jobs/" + job_id).json()
                if job["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                if time.monotonic() > deadline:
                    client.post("/api/v1/jobs/" + job_id + "/cancel")
                    raise TimeoutError("migration correctness job exceeded its run limit")
                time.sleep(.2)
            if job["status"] != "succeeded":
                raise AssertionError(job)
            (output / "job-validation.json").write_text(json.dumps(job, ensure_ascii=False, indent=2))
    return job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, nargs="+", required=True)
    parser.add_argument("--mechanisms", nargs="+", required=True)
    parser.add_argument("--mode", default="legacy")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--evaluations", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job", action="store_true")
    args = parser.parse_args()
    manifest = stage_manifest([str(p.resolve()) for p in args.tasks], args.mechanisms, args.mode, args.seed, args.evaluations)
    report = benchmark(manifest, args.output)
    if args.job:
        validate_job(args.tasks[0], manifest, args.output / "job")
    print(json.dumps({"completed": len(report["rows"]), "quality_computed": False}), flush=True)


if __name__ == "__main__":
    main()
