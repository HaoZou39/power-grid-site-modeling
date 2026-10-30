"""From-scratch Nanxi comparison of strict initialization and the placeable corridor."""

import argparse
from dataclasses import replace
from functools import partial
import json
from pathlib import Path
import time

import numpy as np

from algorithms.routing.components import SearchComponents
from algorithms.routing.pilot_reference.tensor_driver import evolve, initialize
from algorithms.routing.search import run_with_components
from config.project_config import load_default_config
from config.routing_task import RoutingRunConfig
from experiments.launch_routing_run import problem_from_snapshot
from experiments.routing_metrics import compare_front, reference_front
from experiments.routing_output import write_routing_json

MECHANISMS = ["cpu_driver", "astar", "rrt", "nearby_crossover", "distinct_parents", "path_mutation",
              "shorten", "smooth", "elite_local_search", "global_injection", "population_dedup"]
SNAPSHOT = Path("outputs/validation/pilot-batch-20261027/matrix/nanxi-100m--gpu--1001--0/nanxi-100m/snapshot")
TASK = Path("outputs/validation/routing-modularity-20261027/configs/nanxi-100m.json")


def load_problem():
    task = RoutingRunConfig.model_validate_json(TASK.read_text())
    metadata = json.loads((SNAPSHOT / "data_metadata.json").read_text())
    return problem_from_snapshot(SNAPSHOT, task, metadata)


def make_config(seed):
    base = load_default_config().routing
    pilot = replace(base.pilot, enabled_mechanisms=list(MECHANISMS), initialization_mode="hybrid")
    return replace(base, search_strategy="pilot_reference", evolution_backend="tensor", evaluation_backend="tensor",
                   devices=["cuda:0"], popsize=256, max_evaluations=65536, seed=seed, pilot=pilot)


def run_once(problem, seed, corridor, output):
    output.mkdir(parents=True, exist_ok=True)
    config = make_config(seed)
    components = SearchComponents(partial(initialize, corridor=corridor), partial(evolve, max_generations=9))
    started = time.perf_counter()
    result = run_with_components(problem, config, components)
    elapsed = time.perf_counter() - started
    front = np.array([result.evaluations[index].objectives for index in result.pareto_indices], dtype=float)
    name = f"{'corridor' if corridor else 'strict'}-seed{seed}"
    np.save(output / f"{name}-pareto.npy", front)
    stats = result.execution.get("pilot_initialization", {})
    row = {"seed": seed, "corridor": corridor, "elapsed_s": elapsed,
           "initialization_s": result.execution["timings"]["initialization_s"],
           "generation_count": result.generation_count, "stop_reason": result.stop_reason,
           "evaluation_count": result.evaluation_count,
           "n_feasible": sum(value.is_feasible for value in result.evaluations),
           "n_pareto": len(result.pareto_indices),
           "rrt_iterations": stats.get("rrt_iterations"), "rrt_attempts": stats.get("rrt_attempts"),
           "timings": result.execution["timings"]}
    write_routing_json(output / f"{name}.json", row)
    print(json.dumps(row), flush=True)
    return row


def summarize(output):
    rows = [json.loads(path.read_text()) for path in sorted(output.glob("*-seed*.json"))]
    fronts = [np.load(output / f"{'corridor' if row['corridor'] else 'strict'}-seed{row['seed']}-pareto.npy") for row in rows]
    reference = reference_front(fronts)
    minimum, scale = reference.min(0), np.where(reference.max(0) > reference.min(0), reference.max(0) - reference.min(0), 1.)
    for row, front in zip(rows, fronts):
        row["quality"] = compare_front(front, reference, minimum, scale)
    write_routing_json(output / "summary.json", {"rows": rows})
    print(json.dumps(rows, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--corridor", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    if args.summarize:
        summarize(args.output)
        return
    run_once(load_problem(), args.seed, args.corridor, args.output)


if __name__ == "__main__":
    main()
