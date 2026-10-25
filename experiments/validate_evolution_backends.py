"""Headless prepared-scene acceptance for explicit backends and CPU fallback."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter

import numpy as np
import torch

from algorithms.guided_search.search import GuidedSearch, pose_records
from config.project_config import load_project_config, resolve_guided_search_device
from experiments.launch_site_run import constrained_problem
from experiments.output_writer import write_csv
from modeling.haul_field import build_haul_field
from plugins.site_plugin import GuidedSiteConfig


def _json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def validate(args):
    base = load_project_config(args.config_path)
    requested_device = "cpu" if args.cpu else base.modeling.device
    device = resolve_guided_search_device(requested_device)
    model = replace(base.modeling, device=requested_device)
    form = GuidedSiteConfig(experiment_name="evolution-backend-validation", scene_name=args.scene_name,
        rect_w_m=model.rect_w_m, rect_h_m=model.rect_h_m, device=requested_device).model_dump()
    problem, metadata = constrained_problem(form, device)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    scene = Path(metadata["scene_dir"])
    sources = ("algorithms/guided_search/evolution.py", "algorithms/guided_search/numpy_nsga2.py",
        "algorithms/guided_search/tensor_nsga2.py", "algorithms/guided_search/search.py",
        "algorithms/guided_search/guide.py", "modeling/numpy_evaluator.py", "modeling/tensor_evaluator.py",
        "modeling/pose.py", "modeling/masks.py", "modeling/dem_model.py", "modeling/obstacle_model.py",
        "modeling/road_model.py", "modeling/demand_model.py", "config/project_config.py")
    manifest = {"arguments": vars(args), "base_config": asdict(base), "scene": metadata,
        "requested_device": requested_device, "actual_device": str(device),
        "cuda_available": torch.cuda.is_available(), "cpu_threads": torch.get_num_threads(),
        "torch": torch.__version__, "source_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in sources},
        "input_sha256": {name: hashlib.sha256((scene / name).read_bytes()).hexdigest() for name in
            ("dem_1m.npy", "landuse_1m.npy", "road_segments_local.npy", "road_voronoi_1m.npy", "demand_points.npy")}}
    started = perf_counter()
    field = build_haul_field(problem.dem, problem.obstacle_mask == 0, problem.road_segments, segment_kinds=problem.road_segment_kinds,
        diagonal=base.guided_search.diagonal_access, access_elevation_weight=base.guided_search.access_elevation_weight)
    manifest["field_seconds"] = perf_counter() - started
    _json(output / "manifest.json", manifest)
    runs = []
    for requested in ("tensor", "numpy"):
        config = replace(base.guided_search, evolution_backend=requested, seed=args.seed,
            popsize=args.popsize, generations=args.generations)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        started = perf_counter()
        result = GuidedSearch(config).search(problem, model, field=field)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        seconds = perf_counter() - started
        directory = output / requested
        directory.mkdir()
        _json(directory / "search_config.json", asdict(config))
        write_csv(directory / "solutions.csv", result.solutions, list(result.solutions[0]))
        poses = np.array([[row[key] for key in ("x", "y", "theta")] for row in result.solutions])
        rescored = pose_records(problem, model, None, poses, field=field)
        errors = {name: max(abs(a[name] - b[name]) for a, b in zip(result.solutions, rescored)) for name in result.objective_names}
        assert all(error == 0 for error in errors.values())
        assert all(a["is_feasible"] == b["is_feasible"] for a, b in zip(result.solutions, rescored))
        reference_equal = None
        if args.reference_dir:
            arm = "torch-100" if requested == "tensor" else "legacy-100"
            reference = args.reference_dir / f"{arm}-seed{args.seed}" / "solutions.csv"
            reference_equal = reference.read_bytes() == (directory / "solutions.csv").read_bytes()
            assert reference_equal, f"changed original {requested} output: {reference}"
        run = {**result.normalization, "seconds": seconds, "count": len(result.solutions),
            "feasible_count": sum(row["is_feasible"] for row in result.solutions),
            "rescore_max_absolute_error": errors, "reference_csv_identical": reference_equal}
        _json(directory / "summary.json", run)
        runs.append(run)
        print(json.dumps(run), flush=True)
    identical = (output / "tensor/solutions.csv").read_bytes() == (output / "numpy/solutions.csv").read_bytes()
    if device.type == "cpu":
        assert identical, "CPU fallback and explicit NumPy must use identical searches"
        assert all(run["evolution_backend"] == "numpy" for run in runs)
    for name, expected in manifest["source_sha256"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
    summary = {"actual_device": str(device), "cuda_available": manifest["cuda_available"],
        "both_requests_identical": identical, "runs": runs, "source_hashes_unchanged": True}
    _json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config-path", type=Path, default=Path("config/default_config.json"))
    parser.add_argument("--scene-name", default="cangnan")
    parser.add_argument("--popsize", type=int, default=100)
    parser.add_argument("--generations", type=int, default=90)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--reference-dir", type=Path)
    validate(parser.parse_args())


if __name__ == "__main__":
    main()
