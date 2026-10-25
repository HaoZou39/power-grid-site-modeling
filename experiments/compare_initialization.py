"""Compare initialization strategies on one prepared scene, without a browser."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np
import torch

from algorithms.common.pareto import extract_feasible_pareto_front
from algorithms.guided_search import guide
from algorithms.guided_search.search import GuidedSearch, _hypervolume, pose_records
from config.project_config import load_project_config, resolve_guided_search_device
from experiments.launch_site_run import constrained_problem
from experiments.output_writer import write_csv
from modeling.haul_field import build_haul_field
from modeling.pose import decode_raw_pose
from plugins.site_plugin import GuidedSiteConfig


@dataclass(frozen=True)
class InitializationComparisonConfig:
    output_dir: Path
    scene_name: str = "cangnan"
    config_path: Path = Path("config/default_config.json")
    seeds: tuple[int, ...] = (123, 456, 789, 1011, 1213, 1415, 1617, 1819, 2021, 2223)
    popsize: int = 100
    baseline_popsize: int = 40
    generations: int = 90
    grid_m: float = 100.0


def _json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _stage_summary(records: list[dict], grid_m: float) -> dict:
    feasible = [row for row in records if row["is_feasible"]]

    def occupied(rows):
        points = np.asarray([[row["x"], row["y"]] for row in rows]).reshape(-1, 2)
        return len(np.unique(np.floor(points / grid_m).astype(int), axis=0))

    return {"count": len(records), "feasible_count": len(feasible),
            "feasible_ratio": len(feasible) / len(records),
            "occupied_cells": occupied(records), "feasible_cells": occupied(feasible)}


def _run(problem, modeling, field, config, directory: Path, grid_m: float) -> dict:
    captured = {}
    sample = guide.sample_initial_population
    guided = guide.guide_initial_population

    def record_sample(*args, **kwargs):
        result = sample(*args, **kwargs)
        captured["initial"] = result.copy()
        return result

    def record_guidance(*args, **kwargs):
        result = guided(*args, **kwargs)
        captured["guided"] = result.copy()
        return result

    with patch.object(guide, "sample_initial_population", record_sample), patch.object(guide, "guide_initial_population", record_guidance):
        if problem.device.type == "cuda":
            torch.cuda.synchronize(problem.device)
        started = perf_counter()
        result = GuidedSearch(config).search(problem, modeling, field=field)
        if problem.device.type == "cuda":
            torch.cuda.synchronize(problem.device)
        elapsed = perf_counter() - started
    directory.mkdir()
    _json(directory / "search_config.json", asdict(config))
    stages = {}
    for name, raw in captured.items():
        pose = decode_raw_pose(torch.tensor(raw.astype(np.float32), device=problem.device),
                               problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m)
        rows = pose_records(problem, modeling, None, pose.cpu().numpy(), field=field, raw=raw)
        write_csv(directory / f"{name}.csv", rows, list(rows[0]))
        stages[name] = _stage_summary(rows, grid_m)
    rows = result.solutions
    front = extract_feasible_pareto_front(rows, result.objective_names)
    write_csv(directory / "solutions.csv", rows, list(rows[0]))
    write_csv(directory / "pareto_solutions.csv", front, list(rows[0]))
    stages["final"] = _stage_summary(rows, grid_m)
    stages["pareto"] = _stage_summary(front, grid_m) if front else {"count": 0, "feasible_cells": 0}
    summary = {"arm": f"{config.initialization}-{config.popsize}", "method": config.initialization,
               "popsize": config.popsize, "seed": config.seed, "algorithm_seconds": elapsed,
               "evolution_evaluations": config.popsize * (config.generations + 1),
               "objective_names": list(result.objective_names), "stages": stages,
               "objective_minima": {name: min(float(row[name]) for row in front) if front else None
                                    for name in result.objective_names},
               "directory": str(directory)}
    _json(directory / "summary.json", summary)
    return summary


def summarize(output_dir: Path, runs: list[dict]) -> dict:
    names = runs[0]["objective_names"]
    all_rows = []
    fronts = []
    for run in runs:
        with (Path(run["directory"]) / "pareto_solutions.csv").open(encoding="utf-8") as stream:
            records = list(csv.DictReader(stream))
        points = np.asarray([[float(row[name]) for name in names] for row in records]).reshape(-1, len(names))
        fronts.append(points)
        all_rows.extend({**dict(zip(names, point)), "is_feasible": True} for point in points)
    reference_records = extract_feasible_pareto_front(all_rows, names)
    if not reference_records:
        raise ValueError("no feasible front was produced by any comparison run")
    reference = np.unique(np.asarray([[row[name] for name in names] for row in reference_records]), axis=0)
    ideal, nadir = reference.min(axis=0), reference.max(axis=0)
    scale = np.maximum(nadir - ideal, 1e-12)
    normalized_reference = (reference - ideal) / scale
    box = np.full(len(names), 1.1)
    for run, points in zip(runs, fronts):
        normalized = (points - ideal) / scale
        run["hv"] = _hypervolume(list(normalized), box) if len(points) else 0.0
        run["igd_plus"] = float(np.linalg.norm(np.maximum(normalized[None, :, :] - normalized_reference[:, None, :], 0), axis=2).min(axis=1).mean()) if len(points) else None
        _json(Path(run["directory"]) / "summary.json", run)
    arms = {}
    for arm in sorted({run["arm"] for run in runs}):
        selected = [run for run in runs if run["arm"] == arm]
        metrics = {key: [run[key] for run in selected] for key in ("hv", "igd_plus", "algorithm_seconds")}
        metrics.update({"feasible_ratio": [run["stages"]["final"]["feasible_ratio"] for run in selected],
                        "pareto_cells": [run["stages"]["pareto"]["feasible_cells"] for run in selected],
                        "initial_cells": [run["stages"]["initial"]["occupied_cells"] for run in selected],
                        "guided_cells": [run["stages"]["guided"]["occupied_cells"] for run in selected]})
        arms[arm] = {key: {"mean": float(np.mean(values)), "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                          "median": float(np.median(values)), "min": float(np.min(values)), "max": float(np.max(values))}
                     for key, values in metrics.items() if all(value is not None for value in values)}
    paired = []
    for seed in sorted({run["seed"] for run in runs}):
        selected = {run["method"]: run for run in runs if run["seed"] == seed and run["method"] != "gaussian"}
        uniform, taguchi = selected["uniform"], selected["taguchi"]
        paired.append({"seed": seed, "taguchi_minus_uniform_hv": taguchi["hv"] - uniform["hv"],
                       "taguchi_minus_uniform_igd_plus": taguchi["igd_plus"] - uniform["igd_plus"]
                       if taguchi["igd_plus"] is not None and uniform["igd_plus"] is not None else None})
    write_csv(output_dir / "reference_front.csv", reference_records, [*names, "is_feasible"])
    write_csv(output_dir / "paired_comparison.csv", paired, list(paired[0]))
    flattened = [{"arm": run["arm"], "seed": run["seed"], "hv": run["hv"], "igd_plus": run["igd_plus"],
                  "seconds": run["algorithm_seconds"], "feasible_ratio": run["stages"]["final"]["feasible_ratio"],
                  "initial_cells": run["stages"]["initial"]["occupied_cells"],
                  "guided_cells": run["stages"]["guided"]["occupied_cells"],
                  "pareto_cells": run["stages"]["pareto"]["feasible_cells"]} for run in runs]
    write_csv(output_dir / "runs.csv", flattened, list(flattened[0]))
    summary = {"objective_names": names, "ideal": ideal.tolist(), "nadir": nadir.tolist(),
               "normalization_scale": scale.tolist(), "reference_point": box.tolist(),
               "empirical_reference_count": len(reference), "arms": arms, "paired": paired, "runs": runs}
    _json(output_dir / "summary.json", summary)
    return summary


def compare(config: InitializationComparisonConfig) -> dict:
    if not config.seeds or len(set(config.seeds)) != len(config.seeds) or config.grid_m <= 0:
        raise ValueError("provide distinct seeds and a positive spatial grid size")
    base = load_project_config(config.config_path)
    device = resolve_guided_search_device(base.modeling.device)
    form = GuidedSiteConfig(experiment_name="initialization-comparison", scene_name=config.scene_name,
                            rect_w_m=base.modeling.rect_w_m, rect_h_m=base.modeling.rect_h_m,
                            include_demand=base.guided_search.include_demand,
                            diagonal_access=base.guided_search.diagonal_access).model_dump()
    problem, metadata = constrained_problem(form, device, base.modeling)
    from algorithms.guided_search.initialization import resolve_initialization_method
    from modeling.context import building_hard_mask

    method = resolve_initialization_method(
        "taguchi", building_hard_mask(problem) == 0, guide.initialization_bounds(problem, base.modeling),
        bool(problem.initialization_feasible_zones or problem.initialization_exclusion_zones),
    )
    if method != "taguchi":
        raise ValueError("three-method comparison requires an unconstrained center domain; constrained searches use uniform initialization")
    config.output_dir.mkdir(parents=True, exist_ok=False)
    scene = Path(metadata["scene_dir"])
    source_names = ("dem_1m.npy", "landuse_1m.npy", "road_segments_local.npy", "road_voronoi_1m.npy", "demand_points.npy")
    code_names = ("algorithms/guided_search/initialization.py", "algorithms/guided_search/guide.py",
                  "algorithms/guided_search/search.py", "experiments/compare_initialization.py")
    manifest = {"comparison": asdict(config), "base_config": asdict(base), "site_form": form,
                "scene_metadata": metadata, "shape": list(problem.dem.shape),
                "input_sha256": {name: hashlib.sha256((scene / name).read_bytes()).hexdigest() for name in source_names},
                "source_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in code_names},
                "git_head": subprocess.check_output(["rtk", "proxy", "git", "rev-parse", "HEAD"], text=True).strip(),
                "torch": torch.__version__, "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None}
    started = perf_counter()
    field = build_haul_field(problem.dem, problem.obstacle_mask == 0, problem.road_segments, segment_kinds=problem.road_segment_kinds,
                            diagonal=base.guided_search.diagonal_access,
                            access_elevation_weight=base.guided_search.access_elevation_weight)
    manifest["field_build_seconds"] = perf_counter() - started
    _json(config.output_dir / "manifest.json", manifest)
    # Exclude one-time CUDA/optimizer setup from the paired search timings.
    warm = replace(base.guided_search, popsize=4, initialization="uniform", generations=1, guide_steps=1)
    GuidedSearch(warm).search(problem, base.modeling, field=field)
    arms = [("gaussian", config.baseline_popsize), ("gaussian", config.popsize),
            ("uniform", config.popsize), ("taguchi", config.popsize)]
    runs = []
    for index, seed in enumerate(config.seeds):
        offset = index % len(arms)
        for method, popsize in arms[offset:] + arms[:offset]:
            search = replace(base.guided_search, seed=seed, popsize=popsize, initialization=method,
                             generations=config.generations)
            directory = config.output_dir / f"{method}-{popsize}-seed{seed}"
            result = _run(problem, base.modeling, field, search, directory, config.grid_m)
            runs.append(result)
            with (config.output_dir / "progress.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(json.dumps({"completed": len(runs), "total": len(arms) * len(config.seeds),
                              "arm": result["arm"], "seed": seed, "seconds": result["algorithm_seconds"],
                              "feasible": result["stages"]["final"]["feasible_count"],
                              "pareto": result["stages"]["pareto"]["count"]}), flush=True)
    summary = summarize(config.output_dir, runs)
    print(json.dumps(summary["arms"], ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scene-name", default="cangnan")
    parser.add_argument("--config-path", type=Path, default=Path("config/default_config.json"))
    parser.add_argument("--seeds", type=int, nargs="+", default=InitializationComparisonConfig.seeds)
    parser.add_argument("--popsize", type=int, default=100)
    parser.add_argument("--baseline-popsize", type=int, default=40)
    parser.add_argument("--generations", type=int, default=90)
    parser.add_argument("--grid-m", type=float, default=100.0)
    args = parser.parse_args()
    compare(InitializationComparisonConfig(**{**vars(args), "seeds": tuple(args.seeds)}))


if __name__ == "__main__":
    main()
