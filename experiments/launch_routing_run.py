"""Assemble a routing run from an independent snapshot of a prepared scene."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from dataclasses import asdict

import numpy as np

from config.project_config import RoutingConfig
from experiments.launch_site_run import prepare_output_dir
from experiments.output_writer import staged_experiment
from experiments.protected_farmland import MASK_NAME as FARMLAND_MASK, META_NAME as FARMLAND_METADATA
from experiments.routing_output import write_routing_json, write_routing_outputs
from experiments.scene_lock import scene_write_lock
from experiments.scene_store import ensure_scene_readable, scene_directory, scenes_root
from experiments.scene_version import scene_data_version
from modeling.routing.context import RoutingProblem, build_routing_problem, polygons, readonly
from modeling.routing.types import RoutingConstraints, RoutingFrame

INPUT_FILES = ("dem_1m.npy", "landuse_1m.npy", "road_segments_local.npy", "road_segment_kind.npy")


def snapshot_routing_scene(scene_name: str, destination: Path) -> dict:
    scene = scene_directory(scenes_root(), scene_name)
    destination.mkdir()
    with scene_write_lock(scene_name, scene.parent, blocking=True):
        ensure_scene_readable(scene)
        metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
        farmland = scene / FARMLAND_MASK
        registered_farmland = metadata.get("protected_farmland") or (scene / FARMLAND_METADATA).exists()
        if registered_farmland and not farmland.exists():
            raise FileNotFoundError(farmland)
        names = [*INPUT_FILES, *([farmland.name] if farmland.exists() else []),
                 *([FARMLAND_METADATA] if (scene / FARMLAND_METADATA).exists() else [])]
        hashes = {}
        for name in names:
            source, target = scene / name, destination / name
            shutil.copyfile(source, target)
            with target.open("rb") as stream:
                hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        metadata = {**metadata, "scene_id": scene_name, "data_version": scene_data_version(scene, metadata), "input_hashes": hashes}
        write_routing_json(destination / "data_metadata.json", metadata)
        ensure_scene_readable(scene)
    return metadata


def problem_from_snapshot(directory: Path, task, metadata: dict, *, cache_report: dict | None = None):
    from experiments.routing_context_cache import RASTER_CACHE
    frame = RoutingFrame.from_metadata(metadata)
    farmland = directory / "protected_farmland_mask_1m.npy"
    constraints = RoutingConstraints(task.max_span_m, task.tower_radius_m, task.max_turn_deg, task.road_setback_m, task.highway_setback_m)
    start, end = frame.to_local(task.start.lng, task.start.lat), frame.to_local(task.end.lng, task.end.lat)
    if np.array_equal(start, end):
        raise ValueError("start and end connection points must be different")
    for name in set(INPUT_FILES) | set(metadata.get("input_hashes", {})):
        if not (directory / name).is_file():
            raise FileNotFoundError(directory / name)
    hashes = metadata.get("input_hashes")
    key = json.dumps({"hashes": hashes, "frame": asdict(frame), "road_setback": task.road_setback_m,
                      "highway_setback": task.highway_setback_m}, sort_keys=True) if hashes else None
    def build():
        return build_routing_problem(
            np.load(directory / "dem_1m.npy", mmap_mode="r"),
            np.load(directory / "landuse_1m.npy", mmap_mode="r"),
            np.load(directory / "road_segments_local.npy", mmap_mode="r"),
            np.load(directory / "road_segment_kind.npy", mmap_mode="r"),
            np.load(farmland, mmap_mode="r") if farmland.exists() else None,
            start, end, frame, constraints,
        )
    rasters, hit, size = RASTER_CACHE.get(key, task.algorithm.context_cache_mib * 1024**2, build)
    if cache_report is not None:
        cache_report.update(hit=hit, raster_bytes=size)
    return RoutingProblem(**rasters, start=readonly(start), end=readonly(end), frame=frame, constraints=constraints,
                          no_tower_zones=polygons(task.no_tower_zones), no_cross_zones=polygons(task.no_cross_zones))


def launch_routing_run(task, reporter, *, output_root: str | Path | None = None) -> Path:
    from algorithms.routing.search import routing_search
    root = Path(output_root or os.getenv("EXPERIMENT_OUTPUT_ROOT", "outputs"))
    output_dir = prepare_output_dir(root, task.experiment_name, task.overwrite_existing)
    started = time.perf_counter()
    with staged_experiment(output_dir, overwrite=task.overwrite_existing) as staged:
        reporter(.02, "snapshot", "正在独立保存选线输入快照")
        metadata = snapshot_routing_scene(task.scene_name, staged / "scene_snapshot")
        snapshot_s = time.perf_counter() - started
        reporter(.1, "context", "正在构建道路控制范围与选线上下文（CPU）")
        cache_report = {}
        problem = problem_from_snapshot(staged / "scene_snapshot", task, metadata, cache_report=cache_report)
        context_s = time.perf_counter() - started - snapshot_s
        form = task.model_dump()
        write_routing_json(staged / "resolved_config.json", {**form, "output_dir": str(output_dir),
            "start_local": problem.start, "end_local": problem.end})
        write_routing_json(staged / "data_metadata.json", metadata)
        search_started = time.perf_counter()
        result = routing_search(problem, RoutingConfig(**task.algorithm.model_dump()),
            lambda progress, stage, message: reporter(.2 + .7 * progress, stage, message))
        search_s = time.perf_counter() - search_started
        result.execution["context_cache"] = cache_report
        write_routing_outputs(staged, problem, result, form, metadata, time.perf_counter() - started,
            timings={"snapshot_s": snapshot_s, "context_s": context_s, "search_and_validation_s": search_s,
                     "evaluations_per_search_second": result.evaluation_count / search_s})
        reporter(.98, "publishing", "线路已复核，正在发布完整实验")
    reporter(1., "completed", "选线结果已保存；净空未校核")
    return output_dir


def main() -> None:
    import argparse
    from plugins.routing_plugin import RoutingRunConfig
    parser = argparse.ArgumentParser(description="Run routing from a prepared scene and explicit connection points")
    parser.add_argument("--config", required=True, type=Path, help="Routing task JSON")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    task = RoutingRunConfig.model_validate(json.loads(args.config.read_text(encoding="utf-8")))
    directory = launch_routing_run(task, lambda p, stage, message: print(f"{p:.0%} {stage}: {message}", flush=True), output_root=args.output_root)
    print(directory)


if __name__ == "__main__":
    main()
