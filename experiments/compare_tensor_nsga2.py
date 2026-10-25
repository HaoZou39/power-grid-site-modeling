"""Headless full-search timing and quality comparison against a Git baseline."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter

import numpy as np
import torch

from algorithms.common.pareto import extract_feasible_pareto_front
from algorithms.guided_search.search import GuidedSearch, _hypervolume
from config.project_config import load_project_config, validate_cuda_device
from experiments.launch_site_run import constrained_problem
from experiments.output_writer import write_csv
from modeling.haul_field import build_haul_field
from plugins.site_plugin import GuidedSiteConfig


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _legacy_search(ref, output):
    source = subprocess.check_output(["rtk", "proxy", "git", "show", f"{ref}:algorithms/guided_search/search.py"])
    path = output / "legacy_search.py"
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location("tensor_benchmark_legacy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.GuidedSearch


def summarize(output, runs):
    names = runs[0]["objective_names"]
    fronts, records = [], []
    for run in runs:
        points = np.load(Path(run["directory"]) / "front.npy")
        fronts.append(points)
        records.extend({**dict(zip(names, point)), "is_feasible": True} for point in points)
    reference_rows = extract_feasible_pareto_front(records, names)
    reference = np.unique(np.array([[row[name] for name in names] for row in reference_rows]), axis=0)
    ideal, nadir = reference.min(0), reference.max(0)
    scale = np.maximum(nadir - ideal, 1e-12)
    normalized_reference = (reference - ideal) / scale
    box = np.full(len(names), 1.1)
    for run, points in zip(runs, fronts):
        normalized = (points - ideal) / scale
        run["hv"] = _hypervolume(list(normalized), box) if len(points) else 0
        if len(points):
            distances = [np.linalg.norm(np.maximum(normalized[None, :, :] - chunk[:, None, :], 0), axis=2).min(1) for chunk in np.array_split(normalized_reference, max(1, len(reference) // 256))]
            run["igd_plus"] = float(np.concatenate(distances).mean())
        else:
            run["igd_plus"] = None
        _json(Path(run["directory"]) / "summary.json", run)
    arms = {}
    for arm in sorted({run["arm"] for run in runs}):
        selected = [run for run in runs if run["arm"] == arm]
        arms[arm] = {key: {"mean": float(np.mean(values)), "min": float(min(values)), "max": float(max(values)),
                          "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0}
                    for key in ("seconds", "hv", "igd_plus", "feasible_ratio", "peak_cuda_mb")
                    if all((run[key] is not None) for run in selected)
                    for values in [[run[key] for run in selected]]}
    write_csv(output / "reference_front.csv", reference_rows, [*names, "is_feasible"])
    write_csv(output / "runs.csv", [{key: value for key, value in run.items() if key not in ("directory", "objective_names")} for run in runs], [key for key in runs[0] if key not in ("directory", "objective_names")])
    result = {"arms": arms, "ideal": ideal.tolist(), "nadir": nadir.tolist(), "reference_count": len(reference),
              "reference_point": box.tolist(), "objective_names": names, "runs": runs}
    _json(output / "summary.json", result)
    return result


def compare(args):
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists():
        raise FileExistsError(f"comparison already started in {output}")
    base = load_project_config(args.config_path)
    device = validate_cuda_device(base.modeling.device)
    legacy = _legacy_search(args.baseline_ref, output)
    form = GuidedSiteConfig(experiment_name="tensor-nsga2-comparison", scene_name=args.scene_name,
        rect_w_m=base.modeling.rect_w_m, rect_h_m=base.modeling.rect_h_m,
        diagonal_access=base.guided_search.diagonal_access,
        include_demand=base.guided_search.include_demand).model_dump()
    problem, metadata = constrained_problem(form, device, base.modeling)
    scene = Path(metadata["scene_dir"])
    source_paths = ("algorithms/guided_search/search.py", "algorithms/guided_search/tensor_nsga2.py",
                    "modeling/tensor_evaluator.py", "modeling/masks.py", "modeling/site_model.py", "modeling/obstacle_model.py",
                    "algorithms/guided_search/guide.py", "experiments/compare_tensor_nsga2.py")
    manifest = {"arguments": vars(args), "config": asdict(base), "site_form": form,
                "scene_metadata": metadata, "shape": list(problem.dem.shape),
                "input_sha256": {name: hashlib.sha256((scene / name).read_bytes()).hexdigest() for name in
                    ("dem_1m.npy", "landuse_1m.npy", "road_segments_local.npy", "road_voronoi_1m.npy", "demand_points.npy")},
                "source_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in source_paths},
                "legacy_sha256": hashlib.sha256((output / "legacy_search.py").read_bytes()).hexdigest(),
                "torch": torch.__version__, "gpu": torch.cuda.get_device_name(device)}
    started = perf_counter()
    field = build_haul_field(problem.dem, problem.obstacle_mask == 0, problem.road_segments, segment_kinds=problem.road_segment_kinds,
        diagonal=base.guided_search.diagonal_access, access_elevation_weight=base.guided_search.access_elevation_weight)
    manifest["field_seconds"] = perf_counter() - started
    arms = [("legacy", args.baseline_popsize), *[("torch", size) for size in args.populations]]
    # Report first full calls separately; paired timings follow these warm-ups.
    manifest["first_search_seconds"] = {}
    for engine, size in arms:
        config = replace(base.guided_search, popsize=size, generations=args.generations,
            seed=args.seeds[0], evaluation_batch_size=args.batch_size)
        search = legacy if engine == "legacy" else GuidedSearch
        torch.cuda.synchronize(device)
        started = perf_counter()
        search(config).search(problem, base.modeling, field=field)
        torch.cuda.synchronize(device)
        manifest["first_search_seconds"][f"{engine}-{size}"] = perf_counter() - started
    _json(output / "manifest.json", manifest)
    if args.profile_legacy:
        profile = cProfile.Profile()
        profile.enable()
        legacy(replace(base.guided_search, popsize=args.baseline_popsize, generations=args.generations)).search(problem, base.modeling, field=field)
        profile.disable()
        profile.dump_stats(output / "legacy_profile.pstats")
    runs = []
    for index, seed in enumerate(args.seeds):
        offset = index % len(arms)
        for engine, size in arms[offset:] + arms[:offset]:
            config = replace(base.guided_search, popsize=size, generations=args.generations, seed=seed,
                             evaluation_batch_size=args.batch_size)
            search = legacy if engine == "legacy" else GuidedSearch
            torch.cuda.synchronize(device)
            torch.cuda.reset_peak_memory_stats(device)
            started = perf_counter()
            result = search(config).search(problem, base.modeling, field=field)
            torch.cuda.synchronize(device)
            seconds = perf_counter() - started
            peak = torch.cuda.max_memory_allocated(device) / 2**20
            directory = output / f"{engine}-{size}-seed{seed}"
            directory.mkdir()
            front = extract_feasible_pareto_front(result.solutions, result.objective_names)
            np.save(directory / "front.npy", np.array([[row[name] for name in result.objective_names] for row in front]).reshape(-1, len(result.objective_names)))
            write_csv(directory / "solutions.csv", result.solutions, list(result.solutions[0]))
            _json(directory / "search_config.json", asdict(config))
            run = {"arm": f"{engine}-{size}", "popsize": size, "seed": seed, "seconds": seconds,
                   "peak_cuda_mb": peak, "feasible_ratio": sum(row["is_feasible"] for row in result.solutions) / size,
                   "front_count": len(front), "evaluations": size * (config.generations + 1),
                   "objective_names": list(result.objective_names), "directory": str(directory)}
            runs.append(run)
            _json(directory / "summary.json", run)
            with (output / "progress.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(run) + "\n")
            print(json.dumps(run), flush=True)
    summary = summarize(output, runs)
    print(json.dumps(summary["arms"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--config-path", type=Path, default=Path("config/default_config.json"))
    parser.add_argument("--scene-name", default="cangnan")
    parser.add_argument("--seeds", nargs="+", type=int, default=[123, 456, 789, 1011, 1213])
    parser.add_argument("--populations", nargs="+", type=int, default=[100, 400, 1000])
    parser.add_argument("--baseline-popsize", type=int, default=100)
    parser.add_argument("--generations", type=int, default=90)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--profile-legacy", action="store_true")
    args = parser.parse_args()
    if not args.seeds or len(set(args.seeds)) != len(args.seeds) or len(set(args.populations)) != len(args.populations):
        parser.error("provide distinct seeds and population sizes")
    compare(args)


if __name__ == "__main__":
    main()
