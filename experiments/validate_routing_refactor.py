"""Record routing behavior independently of the implementation being refactored."""

import argparse
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import pickle
import random
import sys

import numpy as np
import torch


def digest(value):
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def genes(value):
    if isinstance(value, torch.Tensor):
        value = value.detach().cpu().numpy()
    return hashlib.sha256(np.asarray(value).tobytes()).hexdigest()


def candidate(route, evaluation):
    return {"count": len(route.towers), "xy": genes(route.towers),
            "objectives": genes(evaluation.objectives), "violations": evaluation.violations,
            "violation": evaluation.violation, "feasible": evaluation.is_feasible}


@contextmanager
def trace_search():
    from algorithms.routing.evaluation_budget import EvaluationBudget
    import algorithms.common.nsga2 as numpy_selection
    import algorithms.common.tensor_nsga2 as tensor_selection
    trace = {"evaluations": [], "selection": []}
    streams, restores = [], []
    previous_profile = sys.getprofile()
    random_state_type, python_random_type = np.random.RandomState, random.Random

    class TracedRandomState(random_state_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            streams.append(("pilot_numpy", self))

    class TracedRandom(python_random_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            streams.append(("python", self))

    def profile(frame, event, method):
        if (event == "c_return" and getattr(method, "__name__", "") == "manual_seed"
                and "/algorithms/routing/" in frame.f_code.co_filename):
            owner = getattr(method, "__self__", None)
            if isinstance(owner, torch.Generator):
                streams.append(("torch", owner))

    def patch(owner, name, value):
        previous = getattr(owner, name)
        restores.append((owner, name, previous))
        setattr(owner, name, value)

    def capture_factory(factory, name):
        def create(*args, **kwargs):
            value = factory(*args, **kwargs)
            streams.append((name, value))
            return value
        return create

    original_evaluate = EvaluationBudget.evaluate_many
    def evaluate(budget, routes, source):
        values = original_evaluate(budget, routes, source)
        trace["evaluations"].extend({"source": source, **candidate(route, value)}
                                    for route, value in zip(routes, values))
        return values

    try:
        patch(EvaluationBudget, "evaluate_many", evaluate)
        patch(np.random, "default_rng", capture_factory(np.random.default_rng, "numpy"))
        patch(np.random, "RandomState", TracedRandomState)
        patch(random, "Random", TracedRandom)
        sys.setprofile(profile)
        functions = [(numpy_selection, "tournament"), (numpy_selection, "select_population"),
                     (tensor_selection, "tournament")]
        for owner, name in functions:
            original = getattr(owner, name)
            def wrapped(*args, _fn=original, _name=name, **kwargs):
                result = _fn(*args, **kwargs)
                if isinstance(result, torch.Tensor):
                    identity = result.detach().cpu().tolist()
                elif isinstance(result, list):
                    identity = [genes(item.genes) for item in result]
                else:
                    identity = genes(result.genes)
                trace["selection"].append([_name, identity])
                return result
            # Existing modules import these functions directly; patch those aliases too.
            for module_name, module in list(sys.modules.items()):
                if module is None or not module_name.startswith("algorithms."):
                    continue
                for attr, value in list(vars(module).items()):
                    if value is original:
                        patch(module, attr, wrapped)
        yield trace
        states = []
        for name, stream in streams:
            if name == "numpy":
                state = stream.bit_generator.state
            elif name == "python":
                state = stream.getstate()
            elif name == "torch":
                state = stream.get_state().cpu().numpy()
            else:
                state = stream.get_state()
            states.append([name, digest(state)])
        trace["random_states"] = states
    finally:
        sys.setprofile(previous_profile)
        for owner, name, value in reversed(restores):
            setattr(owner, name, value)


def synthetic_cases():
    from config.project_config import load_default_config
    base = replace(load_default_config().routing, devices=["cpu"], seed=123,
                   popsize=8, max_evaluations=57, reference_count=2, expansion_interval=1)
    cases = {}
    for evolution in ["numpy", "tensor"]:
        for evaluation in ["reference", "compiled_cpu", "tensor"]:
            cases[f"{evolution}-{evaluation}-cpu"] = replace(base, evolution_backend=evolution,
                evaluation_backend=evaluation)
    cases["initial-budget"] = replace(base, evolution_backend="numpy", max_evaluations=8)
    for mode in ["legacy", "pruned", "balanced", "bounded"]:
        for enabled in [False, True]:
            for evaluation in ["reference", "compiled_cpu"]:
                pilot = replace(base.pilot, initialization_mode=mode,
                                enabled_mechanisms=["rrt"] if enabled else [], rrt_goal_bias=1.)
                cases[f"pilot-{mode}-{enabled}-{evaluation}"] = replace(base, search_strategy="pilot_reference",
                    evolution_backend="numpy", evaluation_backend=evaluation, pilot=pilot, max_evaluations=256)
    if torch.cuda.is_available():
        for evolution, evaluation in [("numpy", "compiled_cpu"), ("numpy", "tensor"),
                                       ("tensor", "compiled_cpu"), ("tensor", "tensor")]:
            cases[f"{evolution}-{evaluation}-cuda"] = replace(base, evolution_backend=evolution,
                evaluation_backend=evaluation, devices=["cuda:0"])
        if torch.cuda.device_count() > 1:
            cases["tensor-two-devices"] = replace(base, evolution_backend="tensor",
                evaluation_backend="tensor", devices=["cuda:0", "cuda:1"])
    return cases


def capture_synthetic():
    from algorithms.routing.search import routing_search
    from config.project_config import load_default_config
    from modeling.routing.context import build_routing_problem
    from modeling.routing.types import RoutingConstraints, RoutingFrame
    from plugins.routing_plugin import RoutingPlugin
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[19:24, 18:23] = 5
    problem = build_routing_problem(np.zeros_like(landuse, dtype=float), landuse,
        np.empty((0, 4)), np.empty(0, dtype=np.int8), None, [2., 8.], [28., 8.],
        RoutingFrame("EPSG:32651", (1., 0., 221000., 0., -1., 3046000.), 32, 32),
        RoutingConstraints(13., .4, 90., 0., 0.),
        no_cross_zones=[[[14., 20.], [16., 20.], [16., 23.], [14., 23.]]])
    snapshots = {}
    for name, config in synthetic_cases().items():
        routing_search(problem, config)  # Import/JIT/cache warmup is outside the trace.
        with trace_search() as trace:
            result = routing_search(problem, config)
        execution = {key: value for key, value in result.execution.items()
                     if key not in {"timings", "validation_s", "archive_s", "gpu_memory"}}
        snapshots[name] = {**trace, "archive": [candidate(r, e) for r, e in zip(result.routes, result.evaluations)],
            "pareto": result.pareto_indices, "indices": result.evaluation_indices.tolist(),
            "evaluation_count": result.evaluation_count, "generations": result.generation_count,
            "initialization_evaluations": result.initialization_evaluations,
            "bounds": [result.lower, result.initial_upper, result.final_upper],
            "expansions": result.expansions, "stop_reason": result.stop_reason, "execution": execution}
        print(name, len(trace["evaluations"]), flush=True)
    return {"kind": "routing_refactor_synthetic", "cases": snapshots,
            "schema": RoutingPlugin().describe().config_schema, "defaults": asdict(load_default_config().routing)}


def compare_snapshots(before, after):
    if before != after:
        if before.get("cases", {}).keys() != after.get("cases", {}).keys():
            raise AssertionError("routing backend coverage differs")
        for name in before.get("cases", {}):
            for field, value in before["cases"][name].items():
                if value != after["cases"][name].get(field):
                    raise AssertionError(f"routing behavior differs: {name}.{field}")
        raise AssertionError("routing configuration or schema differs")
    return {"matched": True, "cases": len(before["cases"]),
            "complete_evaluations": sum(len(case["evaluations"]) for case in before["cases"].values())}



def compare_benchmarks(before_root, after_root):
    before_files = sorted(before_root.glob("*/report.json"))
    after_files = sorted(after_root.glob("*/report.json"))
    if [p.parent.name for p in before_files] != [p.parent.name for p in after_files]:
        raise AssertionError("completed routing benchmark jobs differ")
    runs, evaluations, candidates = 0, 0, 0
    volatile = {"elapsed_s", "snapshot_s", "context_s", "candidate_file", "process_peak_rss_mib",
                "git_commit", "quality_at_search_seconds"}
    for before_file, after_file in zip(before_files, after_files):
        before, after = json.loads(before_file.read_text()), json.loads(after_file.read_text())
        if len(before["rows"]) != len(after["rows"]):
            raise AssertionError(f"benchmark row count differs: {before_file.parent.name}")
        for left, right in zip(before["rows"], after["rows"]):
            for field in left.keys() | right.keys():
                if field in volatile:
                    continue
                a, b = left.get(field), right.get(field)
                if field == "execution":
                    a = {k: v for k, v in a.items() if k not in {"timings", "validation_s", "archive_s", "gpu_memory"}}
                    b = {k: v for k, v in b.items() if k not in {"timings", "validation_s", "archive_s", "gpu_memory"}}
                if a != b:
                    raise AssertionError(f"benchmark differs: {before_file.parent.name}/seed{left['seed']}.{field}")
            with np.load(left["candidate_file"]) as old, np.load(right["candidate_file"]) as new:
                if old.files != new.files:
                    raise AssertionError("candidate artifact fields differ")
                for field in old.files:
                    if field != "evaluation_times_s" and not np.array_equal(old[field], new[field], equal_nan=True):
                        raise AssertionError(f"candidate artifact differs: {before_file.parent.name}.{field}")
            runs += 1
            evaluations += left["evaluation_count"]
            candidates += left["n_candidates"]
    if not runs:
        raise AssertionError("no completed routing benchmark runs")
    return {"matched": True, "jobs": len(before_files), "runs": runs,
            "complete_evaluations_per_version": evaluations, "unique_candidates_per_version": candidates}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.source_root:
        sys.path.insert(0, str(args.source_root.resolve()))
    if args.before or args.after:
        if not (args.before and args.after):
            parser.error("comparison requires --before and --after")
        result = (compare_benchmarks(args.before, args.after) if args.benchmark else
                  compare_snapshots(json.loads(args.before.read_text()), json.loads(args.after.read_text())))
        print(json.dumps(result))
    else:
        result = capture_synthetic()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=lambda value: value.item()))


if __name__ == "__main__":
    main()
