"""Manifest-driven exact routing benchmarks, independent from published software runs."""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

import numpy as np
import torch

from algorithms.common.four_objective_front import four_objective_front
from algorithms.routing.search import routing_search
from config.project_config import RoutingConfig
from experiments.launch_routing_run import problem_from_snapshot, snapshot_routing_scene
from experiments.routing_metrics import compare_front, reference_front
from experiments.routing_output import write_routing_json
from plugins.routing_plugin import RoutingRunConfig


def _synchronize(devices):
    for name in devices:
        if name.startswith("cuda:"):
            torch.cuda.synchronize(name)


def _save_candidates(path, result):
    counts = np.array([len(route.towers) for route in result.routes], dtype=np.int64)
    np.savez_compressed(path, xy=np.concatenate([r.towers for r in result.routes], axis=0), counts=counts,
        objectives=np.array([e.objectives for e in result.evaluations]), feasible=np.array([e.is_feasible for e in result.evaluations]),
        pareto=np.array(result.pareto_indices, dtype=np.int64), evaluation_indices=result.evaluation_indices,
        evaluation_times_s=result.evaluation_times_s)


def _front_at(saved, seconds):
    valid = saved["feasible"] & (saved["evaluation_times_s"] <= seconds)
    values = saved["objectives"][valid]
    return values[four_objective_front(values)] if len(values) else values


def benchmark(manifest, output_root):
    output_root.mkdir(parents=True, exist_ok=False)
    write_routing_json(output_root / "manifest.json", manifest)
    revision = os.getenv("SOURCE_REVISION")
    if revision is None:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    rows = []
    for task_path in manifest["tasks"]:
        task = RoutingRunConfig.model_validate(json.loads(Path(task_path).read_text()))
        scene_root = output_root / task.scene_name
        scene_root.mkdir()
        started = time.perf_counter()
        metadata = snapshot_routing_scene(task.scene_name, scene_root / "snapshot")
        snapshot_s = time.perf_counter() - started
        scene_rows = []
        for case in manifest["cases"]:
            if not case["name"] or Path(case["name"]).name != case["name"] or case["name"] in {".", ".."}:
                raise ValueError("case name must be one directory component")
            for seed in manifest["seeds"]:
                cfg = replace(RoutingConfig(**task.algorithm.model_dump()), **{**case["routing"], "seed": seed})
                active_task = task.model_copy(update={"algorithm": task.algorithm.model_validate(asdict(cfg))})
                info = {};started = time.perf_counter()
                problem = problem_from_snapshot(scene_root / "snapshot", active_task, metadata, cache_report=info)
                context_s = time.perf_counter() - started
                for _ in range(manifest["warmups"]):
                    routing_search(problem, cfg)
                replay_hash = None
                for repeat in range(manifest["repeats"]):
                    for device in cfg.devices:
                        if device.startswith("cuda:"):
                            with torch.cuda.device(device):
                                torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats(device)
                    _synchronize(cfg.devices)
                    started = time.perf_counter()
                    result = routing_search(problem, cfg)
                    _synchronize(cfg.devices)
                    elapsed = time.perf_counter() - started
                    run_name = f'{case["name"]}-seed{seed}-repeat{repeat}'
                    saved_path = scene_root / f"{run_name}.npz"
                    _save_candidates(saved_path, result)
                    digest = hashlib.sha256()
                    for route, value in zip(result.routes, result.evaluations):
                        digest.update(route.towers.tobytes());digest.update(value.objectives.tobytes())
                    repeated = None if replay_hash is None else replay_hash == digest.hexdigest()
                    if repeated is False:
                        raise AssertionError("fixed backend and seed failed reproduction")
                    replay_hash = digest.hexdigest()
                    valid = [i for i, e in enumerate(result.evaluations) if e.is_feasible]
                    first = min((int(result.evaluation_indices[i]) for i in valid), default=None)
                    row = {"scene": task.scene_name, "case": case["name"], "seed": seed, "repeat": repeat,
                        "config": asdict(cfg), "elapsed_s": elapsed, "snapshot_s": snapshot_s, "context_s": context_s,
                        "context_cache": info, "n_candidates": len(result.routes), "n_feasible": len(valid),
                        "n_pareto": len(result.pareto_indices), "first_feasible_evaluation": first,
                        "evaluation_count": result.evaluation_count, "result_hash": replay_hash, "reproduced": repeated,
                        "generation_count": result.generation_count, "initialization_evaluations": result.initialization_evaluations,
                        "tower_count_lower": result.lower, "initial_tower_upper": result.initial_upper,
                        "final_tower_upper": result.final_upper, "expansions": result.expansions,
                        "pareto_tower_counts": sorted({len(result.routes[i].towers) for i in result.pareto_indices}),
                        "duplicate_evaluations": result.evaluation_count - len(result.routes), "stop_reason": result.stop_reason,
                        "execution": result.execution, "candidate_file": str(saved_path.resolve()),
                        "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                        "git_commit": revision, "input_hashes": metadata["input_hashes"]}
                    if case.get("publish", False):
                        from experiments.launch_routing_run import launch_routing_run
                        published_task = active_task.model_copy(update={"experiment_name": run_name, "overwrite_existing": False})
                        publication_started = time.perf_counter()
                        published = launch_routing_run(published_task, lambda *_: None, output_root=scene_root / "published")
                        publication_s = time.perf_counter() - publication_started
                        summary = json.loads((published / "run_summary.json").read_text())
                        assert summary["evaluation_count"] == result.evaluation_count
                        assert summary["n_solutions"] == len(result.routes)
                        row["publication"] = {"elapsed_s": publication_s, "directory": str(published.resolve()), "summary": summary}
                    write_routing_json(scene_root / f"{run_name}.json", row)
                    rows.append(row);scene_rows.append(row)
                    print(json.dumps({k: row[k] for k in ("scene", "case", "seed", "repeat", "elapsed_s", "n_feasible", "n_pareto")}), flush=True)
        fronts = []
        for row in scene_rows:
            with np.load(row["candidate_file"]) as saved:
                fronts.append(saved["objectives"][saved["pareto"]])
        reference = reference_front(fronts)
        np.save(scene_root / "reference_front.npy", reference)
        if len(reference):
            minimum = reference.min(0)
            scale = np.where(reference.max(0) > minimum, reference.max(0) - minimum, 1.)
            write_routing_json(scene_root / "normalization.json", {"minimum": minimum, "scale": scale,
                "reference_sha256": hashlib.sha256(reference.tobytes()).hexdigest(), "kind": "best_known_union"})
            for row in scene_rows:
                with np.load(row["candidate_file"]) as saved:
                    row["quality"] = compare_front(saved["objectives"][saved["pareto"]], reference, minimum, scale)
                    row["quality_at_search_seconds"] = {str(t): compare_front(_front_at(saved, t), reference, minimum, scale)
                        for t in manifest["time_checkpoints_s"]}
        # Source preservation is checked after every scene's complete matrix.
        from experiments.scene_store import scene_directory, scenes_root
        source = scene_directory(scenes_root(), task.scene_name)
        for name, expected in metadata["input_hashes"].items():
            with (source / name).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise AssertionError(f"source changed: {name}")
            assert (source / name).stat().st_ino != (scene_root / "snapshot" / name).stat().st_ino
    report = {"schema_version": 1, "rows": rows, "git_commit": revision,
        "source_hashes_unchanged": True, "independent_snapshots": True,
        "quality_reference": "frozen union of completed fronts; not a proof of global optimality",
        "timing_scope": "elapsed includes initialization/search/archive/CPU validation; optional publication is a separate full task replay including snapshot/context/report/output"}
    write_routing_json(output_root / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    benchmark(json.loads(args.manifest.read_text()), args.output_root)


if __name__ == "__main__":
    main()
