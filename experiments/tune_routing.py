"""Equal-search-time calibration of one routing default across scene classes.

Protocol: markdown/ALGORITHMS_MODULE_SUMMARY.md「选线默认参数校准」. Candidates only override
config/default_config.json; fronts are cut at the recorded first-completion search time.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

from algorithms.common.four_objective_front import four_objective_front
from experiments.routing_metrics import compare_front, reference_front

SCENES_ROOT = Path(__file__).resolve().parents[1] / "scenes"
OBSTACLE_CLASSES = (2, 5)
NO_STOP = 10**6


class _SearchTimeUp(Exception):
    pass


def merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if key not in result:
            raise ValueError(f"unknown routing field {key!r}")
        result[key] = merge(result[key], value) if isinstance(value, dict) else value
    return result


def candidate_config(overrides, seed):
    from config.project_config import RoutingConfig, load_default_config

    raw = merge(asdict(load_default_config().routing), overrides)
    return RoutingConfig(**{**raw, "seed": seed, "max_generations": NO_STOP, "devices": ["cpu"],
                            "evolution_backend": "tensor", "evaluation_backend": "tensor"})


def sample_endpoints(landuse, distance_range, obstacle, seed, margin=40.0, draws=500):
    """Straight-line obstacle fraction samples the segment at 120 points; `obstacle` is low, high or any."""
    rng = np.random.default_rng(seed)
    height, width = landuse.shape
    low, high = distance_range
    best = None
    for _ in range(draws):
        start = rng.uniform((margin, margin), (width - margin, height - margin))
        end = rng.uniform((margin, margin), (width - margin, height - margin))
        distance = float(np.linalg.norm(end - start))
        if not low <= distance <= high:
            continue
        t = np.linspace(0, 1, 120)[:, None]
        points = start * (1 - t) + end * t
        hit = float(np.isin(landuse[points[:, 1].astype(int), points[:, 0].astype(int)], OBSTACLE_CLASSES).mean())
        if obstacle == "any":
            return start, end, distance, hit
        rank = hit if obstacle == "high" else -hit
        if best is None or rank > best[0]:
            best = (rank, start, end, distance, hit)
    if best is None:
        raise RuntimeError(f"no endpoint pair within {distance_range} m")
    return best[1:]


def class_seed(name, draw):
    return int.from_bytes(hashlib.sha256(f"{name}:{draw}".encode()).digest()[:4], "little")


def instances(manifest, split):
    rows = []
    for item in manifest["scene_classes"]:
        landuse = np.load(SCENES_ROOT / item["scene"] / "landuse_1m.npy", mmap_mode="r")
        for draw in manifest[split]["endpoint_draws"]:
            start, end, distance, hit = sample_endpoints(landuse, item["distance_m"], item["obstacle"],
                                                         class_seed(item["name"], draw))
            rows.append({"class": item["name"], "scene": item["scene"], "span_m": item["span_m"], "draw": draw,
                         "start": start.tolist(), "end": end.tolist(), "distance_m": distance,
                         "straight_obstacle_fraction": hit})
    return rows


@lru_cache(maxsize=2)
def _scene_problem(scene):
    from config.project_config import load_default_config
    from modeling.routing.context import build_routing_problem
    from modeling.routing.types import RoutingConstraints, RoutingFrame

    directory = SCENES_ROOT / scene
    frame = RoutingFrame.from_metadata(json.loads((directory / "data_metadata.json").read_text(encoding="utf-8")))
    farmland = directory / "protected_farmland_mask_1m.npy"
    modeling = load_default_config().modeling
    # 道路占地只取决于退距，与端点和档距无关；每个场景只建一次，再替换端点与约束。
    return build_routing_problem(
        np.load(directory / "dem_1m.npy", mmap_mode="r"), np.load(directory / "landuse_1m.npy", mmap_mode="r"),
        np.load(directory / "road_segments_local.npy", mmap_mode="r"),
        np.load(directory / "road_segment_kind.npy", mmap_mode="r"),
        np.load(farmland, mmap_mode="r") if farmland.exists() else None,
        (1.0, 1.0), (2.0, 1.0), frame,
        RoutingConstraints(1.0, 3, 90, modeling.road_setback_m, modeling.highway_setback_m))


def run_job(job):
    import torch
    import algorithms.routing.search as search
    from modeling.routing.types import RoutingConstraints

    torch.set_num_threads(1)
    instance, candidate, seed, limit_s = job["instance"], job["candidate"], job["seed"], job["search_seconds"]
    base = _scene_problem(instance["scene"])
    c = base.constraints
    problem = replace(base, start=np.asarray(instance["start"]), end=np.asarray(instance["end"]),
                      constraints=RoutingConstraints(float(instance["span_m"]), c.tower_radius_m, c.max_turn_deg,
                                                     c.road_setback_m, c.highway_setback_m))
    config = candidate_config(candidate["routing"], seed)
    budgets = []
    original = search.EvaluationBudget

    class Recorded(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            budgets.append(self)

    def stop_after_limit(fraction, stage, message):
        if stage == "evolution" and time.perf_counter() - budgets[0].started > limit_s:
            raise _SearchTimeUp

    search.EvaluationBudget = Recorded
    started = time.perf_counter()
    try:
        search.routing_search(problem, config, stop_after_limit)
        raise RuntimeError("search ended before the time limit; raise max_generations")
    except _SearchTimeUp:
        pass
    finally:
        search.EvaluationBudget = original
    budget = budgets[0]
    seen, objectives, feasible, times = set(), [], [], []
    for (route, value), at in zip(budget.records, budget.times):
        key = route.towers.tobytes()
        if key in seen:
            continue
        seen.add(key)
        objectives.append(value.objectives)
        feasible.append(value.is_feasible)
        times.append(at)
    objectives, feasible, times = np.asarray(objectives), np.asarray(feasible), np.asarray(times)
    valid = feasible & (times <= limit_s)
    values = objectives[valid]
    front = values[four_objective_front(values)] if len(values) else np.empty((0, 4))
    return {"class": instance["class"], "draw": instance["draw"], "candidate": candidate["name"], "seed": seed,
            "front": front.tolist(), "generations": budget.completed_generations,
            "evaluations_by_limit": int((np.asarray(budget.times) <= limit_s).sum()),
            "feasible_by_limit": int(valid.sum()), "wall_s": time.perf_counter() - started}


def score(runs, ratio_floor):
    """Rank candidates by their worst class ratio of mean IGD+ to the best mean IGD+ in that class.

    `ratio_floor` is added to both sides, so normalized IGD+ gaps below it count as no difference.
    """
    fronts = {}
    for run in runs:
        fronts.setdefault((run["class"], run["draw"]), []).append(np.asarray(run["front"], dtype=float).reshape(-1, 4))
    references, skipped = {}, []
    for key, items in fronts.items():
        reference = reference_front(items)
        if len(reference):
            references[key] = reference
        else:
            skipped.append({"class": key[0], "draw": key[1]})
    candidates = sorted({run["candidate"] for run in runs})
    eliminated = sorted({run["candidate"] for run in runs
                         if (run["class"], run["draw"]) in references and not len(run["front"])})
    quality = {}
    for run in runs:
        key = (run["class"], run["draw"])
        if key not in references or not len(run["front"]):
            continue
        reference = references[key]
        minimum = reference.min(0)
        scale = np.where(reference.max(0) > minimum, reference.max(0) - minimum, 1.)
        metric = compare_front(np.asarray(run["front"], dtype=float), reference, minimum, scale)["igd_plus"]
        quality.setdefault((run["candidate"], run["class"]), []).append(metric)
    classes = sorted({run["class"] for run in runs if (run["class"], run["draw"]) in references})
    means = {key: float(np.mean(values)) for key, values in quality.items()}
    table = {}
    for name in candidates:
        if name in eliminated:
            continue
        ratios = {}
        for scene_class in classes:
            best = min(means[(other, scene_class)] for other in candidates
                       if other not in eliminated and (other, scene_class) in means)
            ratios[scene_class] = (means[(name, scene_class)] + ratio_floor) / (best + ratio_floor)
        table[name] = {"worst_ratio": max(ratios.values()), "ratios": ratios,
                       "mean_igd_plus": {k: means[(name, k)] for k in classes}}
    ranking = sorted(table, key=lambda name: table[name]["worst_ratio"])
    return {"ranking": ranking, "candidates": table, "eliminated": eliminated, "skipped_instances": skipped}


def engineering_summary(runs):
    result = {}
    for run in runs:
        front = np.asarray(run["front"], dtype=float).reshape(-1, 4)
        entry = result.setdefault(run["candidate"], {}).setdefault(run["class"], {"min_towers": [], "min_crossing_m": []})
        entry["min_towers"].append(float(front[:, 0].min()) if len(front) else None)
        entry["min_crossing_m"].append(float(front[:, 3].min()) if len(front) else None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--split", choices=("tuning", "holdout"), required=True)
    parser.add_argument("--stage", required=True, help="candidate list name inside the manifest")
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if os.environ.get("OMP_NUM_THREADS") != "1":
        raise RuntimeError("set OMP_NUM_THREADS=1 so parallel runs do not oversubscribe cores")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    cases = instances(manifest, args.split)
    jobs = [{"instance": instance, "candidate": candidate, "seed": seed, "search_seconds": manifest["search_seconds"]}
            for instance in cases for candidate in manifest["stages"][args.stage]
            for seed in manifest[args.split]["search_seeds"]]
    (args.output_dir / "plan.json").write_text(json.dumps(
        {"manifest": manifest, "split": args.split, "stage": args.stage, "workers": args.workers,
         "instances": cases, "jobs": len(jobs)}, ensure_ascii=False, indent=2), encoding="utf-8")
    runs = []
    with ProcessPoolExecutor(args.workers) as pool, (args.output_dir / "runs.jsonl").open("w", encoding="utf-8") as out:
        for run in pool.map(run_job, jobs):
            runs.append(run)
            out.write(json.dumps(run) + "\n")
            out.flush()
            print(json.dumps({k: run[k] for k in ("class", "draw", "candidate", "seed", "generations",
                                                 "feasible_by_limit", "wall_s")}), flush=True)
    summary = {"score": score(runs, manifest["ratio_floor"]), "engineering": engineering_summary(runs)}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["score"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
