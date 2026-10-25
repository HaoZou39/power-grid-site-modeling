"""Compare the original CPU builder and bounded-memory CUDA on full grids."""

import argparse
import ast
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import statistics
import subprocess
import sys
from time import perf_counter

import numba
import numpy as np
import torch

from data_tools.road_voronoi import compute_segment_voronoi


def _hash_array(array):
    digest = hashlib.sha256()
    flat = array.reshape(-1)
    for start in range(0, flat.size, 1048576):
        digest.update(flat[start:start + 1048576].tobytes())
    return digest.hexdigest()


def _original_cpu(ref, output):
    source = subprocess.check_output(
        ["git", "show", f"{ref}:data_tools/traffic_tool.py"], text=True,
    )
    root = ast.parse(source)
    function = next(node for node in ast.walk(root)
                    if isinstance(node, ast.FunctionDef) and node.name == "_segment_voronoi_numba")
    # Keep the original body and decorator verbatim, including cache/fastmath settings.
    lines = source.splitlines(keepends=True)
    first = min(node.lineno for node in [function, *function.decorator_list]) - 1
    body = "".join(line[4:] for line in lines[first:function.end_lineno])
    snapshot = output / "original_cpu.py"
    snapshot.write_text("import numpy as np\nfrom numba import njit, prange\n\n" + body)
    spec = importlib.util.spec_from_file_location("voronoi_baseline", snapshot)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module._segment_voronoi_numba, hashlib.sha256(source.encode()).hexdigest()


def _process_gpu_mib():
    if not shutil.which("nvidia-smi"):
        return None
    output = subprocess.check_output([
        "nvidia-smi", "--query-compute-apps=pid,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ], text=True)
    values = [int(line.split(",")[1]) for line in output.splitlines()
              if line.split(",")[0].strip() == str(os.getpid())]
    return sum(values) if values else None


def _check_road_product(config_path, segments, size, output):
    from config.project_config import load_project_config
    from data_tools.traffic_tool import build_road_product

    config = load_project_config(config_path).data
    reference = None
    frame = config.target_grid
    if (frame["height"], frame["width"]) != (size, size):
        raise ValueError("comparison size must match data.target_grid")
    report = {}
    for backend in ("cpu", "auto"):
        target = output / f"product-{backend}"
        target.mkdir()
        roads, labels, kinds, metadata = build_road_product(
            config.osm_roads_path, target / "road_segments_local.npy", target / "road_voronoi_1m.npy",
            None, (size, size), config.road_dp_tolerance_m, config.road_resolution_m,
            reference_frame=frame,
            kind_rules=config.road_kind_rules,
            voronoi_backend=backend, voronoi_device=config.road_voronoi_device,
            voronoi_chunk_points=config.road_voronoi_chunk_points,
            voronoi_segment_tile=config.road_voronoi_segment_tile,
        )
        np.testing.assert_array_equal(roads, segments)
        np.testing.assert_array_equal(np.load(target / "road_voronoi_1m.npy"), labels)
        if reference is None:
            reference = labels
        else:
            np.testing.assert_array_equal(labels, reference)
            assert metadata["voronoi_backend"] == "cuda"
        report[backend] = {"actual_backend": metadata["voronoi_backend"],
                           "label_sha256": _hash_array(labels), "segments_sha256": _hash_array(roads),
                           "mismatched_cells": 0, "saved_grid_exact": True}
    (output / "product_validation.json").write_text(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", type=Path, default=Path("scenes/cangnan/road_segments_local.npy"))
    parser.add_argument("--source-size", type=int, default=1800)
    parser.add_argument("--large-size", type=int, default=9000)
    parser.add_argument("--baseline-ref", default="a4e4f4a")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--threads", type=int, default=numba.config.NUMBA_NUM_THREADS)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--chunk-points", type=int, default=1048576)
    parser.add_argument("--segment-tile", type=int, default=128)
    parser.add_argument("--product-config", type=Path,
                        help="Also rebuild/safely save CPU and auto products from these real inputs in the output directory")
    parser.add_argument("--cases", nargs="+", choices=["original", "scaled", "tiled"],
                        default=["original", "scaled", "tiled"])
    args = parser.parse_args()
    if args.repeats < 2 or args.source_size <= 0 or args.large_size % args.source_size:
        parser.error("repeats >= 2; large-size must be a positive multiple of source-size")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    numba.set_num_threads(args.threads)
    original, baseline_hash = _original_cpu(args.baseline_ref, args.output_dir)
    segments = np.ascontiguousarray(np.load(args.segments), dtype=np.float32)
    torch.cuda.set_device(args.device)
    manifest = {
        "baseline_ref": args.baseline_ref, "baseline_file_sha256": baseline_hash,
        "source_segments": str(args.segments), "source_segments_sha256": _hash_array(segments),
        "torch": torch.__version__, "gpu": torch.cuda.get_device_name(),
        "gpu_total_bytes": torch.cuda.get_device_properties(args.device).total_memory,
        "cpu_threads": numba.get_num_threads(), "cpu_name": next(
            (line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
             if line.startswith("model name")), "unknown"),
        "arguments": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "source_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (
            "data_tools/road_voronoi.py", "data_tools/road_voronoi_cuda.py",
            "data_tools/traffic_tool.py", "experiments/compare_road_voronoi.py")},
        "timing": "Complete label construction, output allocation and GPU-to-CPU copies; no disk I/O or comparison. Device selection/initialization is outside the timer. First calls include lazy import/JIT if uncached; later calls are warm. RSS is cumulative process high-water mark (comparison retains two label arrays). CUDA peaks include output batch and segments but exclude driver context. nvidia_process_after_mib is a post-call process snapshot including CUDA context, not a sampled peak.",
        "runs": [],
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    results = []
    factor = args.large_size // args.source_size
    for case in args.cases:
        if case == "original":
            roads, size = segments, args.source_size
            construction = "Unchanged prepared Cangnan segments and scene dimensions"
        elif case == "scaled":
            roads, size = segments * np.float32(factor), args.large_size
            construction = f"Synthetic stress case: original coordinates multiplied by {factor}; road count unchanged"
        else:
            roads = np.concatenate([segments + np.array([x, y, x, y], np.float32) * args.source_size
                                    for y in range(factor) for x in range(factor)])
            size = args.large_size
            construction = f"Synthetic density-preserving stress case: {factor}x{factor} translated copies; no geographic claim"
        case_result = {"case": case, "shape": [size, size], "segments": len(roads),
                       "construction": construction, "input_sha256": _hash_array(roads), "runs": []}
        reference = None
        for repeat in range(args.repeats):
            # Rotate order after the first pair; retain only one reference and one result.
            for backend in (["cpu", "cuda"] if repeat % 2 == 0 else ["cuda", "cpu"]):
                gc.collect()
                torch.cuda.synchronize()
                torch.cuda.reset_peak_memory_stats()
                started = perf_counter()
                if backend == "cpu":
                    labels = original(roads, size, size, np.float32(1))
                else:
                    labels = compute_segment_voronoi(
                        roads, size, size, backend="cuda", device=args.device,
                        gpu_chunk_points=args.chunk_points, segment_tile=args.segment_tile,
                    )
                torch.cuda.synchronize()
                elapsed = perf_counter() - started
                run = {"backend": backend, "repeat": repeat, "seconds": elapsed,
                       "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                       "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                       "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                       "output_bytes": labels.nbytes, "output_sha256": _hash_array(labels)}
                run["nvidia_process_after_mib"] = _process_gpu_mib()
                if reference is None:
                    reference = labels
                    run["mismatched_cells"] = 0
                else:
                    mismatch = 0
                    for first in range(0, size, 128):
                        mismatch += int(np.count_nonzero(labels[first:first + 128] != reference[first:first + 128]))
                    run["mismatched_cells"] = mismatch
                    del labels
                case_result["runs"].append(run)
                manifest["runs"].append({"case": case, **run})
                (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
                print(json.dumps({"case": case, **run}), flush=True)
                if run["mismatched_cells"]:
                    raise AssertionError(f"{case}: exact Voronoi labels differ")
        cpu = [run["seconds"] for run in case_result["runs"] if run["backend"] == "cpu" and run["repeat"] > 0]
        cuda = [run["seconds"] for run in case_result["runs"] if run["backend"] == "cuda" and run["repeat"] > 0]
        case_result.update(cpu_warm_median_s=statistics.median(cpu), cuda_warm_median_s=statistics.median(cuda),
                           speedup=statistics.median(cpu) / statistics.median(cuda))
        results.append(case_result)
        (args.output_dir / "summary.json").write_text(json.dumps(results, indent=2))
        reference = None
        del roads
    if args.product_config is not None:
        _check_road_product(args.product_config, segments, args.source_size, args.output_dir)
    print(json.dumps([{key: value for key, value in result.items() if key != "runs"} for result in results]), flush=True)


if __name__ == "__main__":
    main()
