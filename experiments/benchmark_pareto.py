"""Compare exact front extraction on fixed 40k records in isolated CPU processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", default="148b2e0")
    parser.add_argument("--variant", choices=("old", "new"))
    args = parser.parse_args()
    if args.variant:
        if hasattr(os, "sched_setaffinity"):
            os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
        if args.variant == "old":
            code = subprocess.check_output(["git", "show", f"{args.baseline}:algorithms/common/pareto.py"], text=True)
        else:
            code = Path("algorithms/common/pareto.py").read_text()
        # Both variants load only this module, excluding unrelated package imports from RSS.
        namespace = {}
        exec(compile(code, f"{args.variant}-pareto", "exec"), namespace)
        extract = namespace["extract_feasible_pareto_front"]
        values = np.random.default_rng(20261026).random((40_000,3))
        records = [dict(id=i,a=a,b=b,c=c,is_feasible=True) for i,(a,b,c) in enumerate(values)]
        started = time.perf_counter()
        front = extract(records, ("a","b","c"))
        result = {"seconds":time.perf_counter()-started, "peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "front_count":len(front), "ordered_id_sha256":hashlib.sha256(json.dumps([r["id"] for r in front]).encode()).hexdigest()}
        print(json.dumps(result))
        return
    results = {}
    for variant in ("old", "new"):
        runs = []
        for _ in range(3):
            raw = subprocess.check_output([sys.executable, "-m", "experiments.benchmark_pareto", str(args.output),
                "--baseline", args.baseline, "--variant", variant], text=True)
            runs.append(json.loads(raw))
        results[variant] = {"runs":runs, "median_seconds":statistics.median(run["seconds"] for run in runs)}
    assert len({r["ordered_id_sha256"] for v in results.values() for r in v["runs"]}) == 1
    results["speedup"] = results["old"]["median_seconds"] / results["new"]["median_seconds"]
    results["passes_fourfold_target"] = results["speedup"] >= 4
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2)+"\n")
    print(json.dumps(results, indent=2))
    if not results["passes_fourfold_target"]:
        raise RuntimeError("Pareto benchmark did not meet the fourfold target")


if __name__ == "__main__":
    main()
