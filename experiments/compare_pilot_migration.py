"""Compare paired migration trials against one frozen per-problem reference front."""

import argparse
import json
from pathlib import Path

import numpy as np

from experiments.pilot_migration_metrics import migration_gate, shape_diversity
from experiments.routing_metrics import compare_front, reference_front
from experiments.routing_output import write_routing_json
from modeling.routing.types import RoutingFrame
from plugins.routing_plugin import RoutingRunConfig


def problem_form(config):
    return RoutingRunConfig.model_validate(config).model_dump(exclude={"algorithm", "experiment_name", "overwrite_existing"})


def load_trials(entry, expected):
    report = json.loads(Path(entry["report"]).read_text())
    rows = [row for row in report["rows"] if row["case"] == entry["case"] and row["repeat"] == 0
            and ("task_id" not in entry or row.get("task_id", row["scene"]) == entry["task_id"])]
    if len({row["seed"] for row in rows}) != len(rows):
        raise ValueError("ambiguous problem or duplicate seed in migration report")
    legacy_problems = {}
    if any("problem" not in row for row in rows):
        manifest = json.loads((Path(entry["report"]).parent / "manifest.json").read_text())
        for task in manifest["tasks"]:
            path = task["config"] if isinstance(task, dict) else task
            form = problem_form(json.loads(Path(path).read_text()))
            legacy_problems[task["id"] if isinstance(task, dict) else form["scene_name"]] = form
    for row in rows:
        actual = row.get("problem", legacy_problems.get(row.get("task_id", row["scene"])))
        if actual != expected:
            raise ValueError("migration engineering inputs differ")
    return {row["seed"]: row for row in rows}


def initial_diversity(saved, row, endpoints, samples):
    counts, xy = saved["counts"], saved["xy"]
    offsets = np.r_[0, np.cumsum(counts)]
    eligible = saved["feasible"] & (saved["evaluation_indices"] <= row["initialization_evaluations"])
    eligible &= counts <= row["initial_tower_upper"]
    eligible &= counts >= row["tower_count_lower"]
    paths = [np.vstack([endpoints[0], xy[offsets[i]:offsets[i + 1]], endpoints[1]])
             for i in np.flatnonzero(eligible)]
    return shape_diversity(paths, float(np.linalg.norm(endpoints[1] - endpoints[0])), samples)


def compare_migration(spec):
    if set(spec["baseline"]) != set(spec["candidate"]) or set(spec["tasks"]) != set(spec["baseline"]):
        raise ValueError("migration comparison requires identical problem IDs")
    before, after, references = {}, {}, {}
    for task_id in spec["baseline"]:
        task = json.loads(Path(spec["tasks"][task_id]).read_text())
        expected = problem_form(task)
        old, new = load_trials(spec["baseline"][task_id], expected), load_trials(spec["candidate"][task_id], expected)
        if set(old) != set(new) or not old:
            raise ValueError("migration comparison requires paired seeds")
        first = next(iter(old.values()))
        snapshot = Path(first["candidate_file"]).parent / "snapshot" / "data_metadata.json"
        frame = RoutingFrame.from_metadata(json.loads(snapshot.read_text()))
        endpoints = np.array([frame.to_local(task[name]["lng"], task[name]["lat"]) for name in ["start", "end"]])
        fronts = []
        for seed in old:
            if old[seed]["input_hashes"] != new[seed]["input_hashes"] or old[seed]["evaluation_count"] != new[seed]["evaluation_count"]:
                raise ValueError("migration inputs or evaluation budgets differ")
            for row in [old[seed], new[seed]]:
                with np.load(row["candidate_file"]) as saved:
                    fronts.append(saved["objectives"][saved["pareto"]])
        reference = reference_front(fronts)
        if not len(reference):
            raise ValueError("migration comparison has no feasible reference")
        minimum = reference.min(0)
        scale = np.where(reference.max(0) > minimum, reference.max(0) - minimum, 1.)
        references[task_id] = {"objectives": reference.tolist(), "minimum": minimum.tolist(), "scale": scale.tolist()}
        before[task_id], after[task_id] = {}, {}
        for group, destination in [(old, before[task_id]), (new, after[task_id])]:
            for seed, row in group.items():
                with np.load(row["candidate_file"]) as saved:
                    quality = compare_front(saved["objectives"][saved["pareto"]], reference, minimum, scale)
                    destination[seed] = {"feasible": row["n_feasible"] > 0, **quality,
                        "initial_shape_diversity": initial_diversity(saved, row, endpoints, spec["shape_samples"]),
                        "evaluation_count": row["evaluation_count"], "source": row["candidate_file"]}
    return {"gate": migration_gate(before, after, **spec["gate"]), "baseline": before,
            "candidate": after, "references": references, "protocol": spec}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = compare_migration(json.loads(args.config.read_text()))
    write_routing_json(args.output, report)
    print(json.dumps(report["gate"], ensure_ascii=False))


if __name__ == "__main__":
    main()
