"""Rectangular, shared-scene parallel execution for guided site searches."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
import math
from pathlib import Path
from threading import Lock
from typing import Any, Callable

import numpy as np

from config.project_config import DEFAULT_CONFIG_PATH
from modeling.pose import compute_safe_margin

Progress = Callable[[float, str, str], None]
CenterBounds = tuple[float, float, float, float]
PoseBounds = tuple[float, float, float, float]


@dataclass(frozen=True)
class SearchPartition:
    partition_id: str
    row: int
    column: int
    center_bounds_m: CenterBounds
    seed: int

    @property
    def pose_bounds(self) -> PoseBounds:
        xmin, ymin, xmax, ymax = self.center_bounds_m
        return xmin, xmax, ymin, ymax


@dataclass(frozen=True)
class PartitionedGuidedSearchResult:
    normalization: dict[str, Any]
    solutions: list[dict[str, Any]]
    objective_names: tuple[str, ...]
    partitions: list[dict[str, Any]]


def plan_search_partitions(
    matrix_shape: tuple[int, int],
    rect_w_m: float,
    rect_h_m: float,
    partition_count: int,
    seed: int,
    search_bounds_m: CenterBounds | None = None,
) -> list[SearchPartition]:
    """Split safe building-center bounds into equal, non-overlapping rectangles."""

    if partition_count not in {4, 6}:
        raise ValueError("partition_count must be 4 or 6")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    height, width = matrix_shape
    margin = compute_safe_margin(rect_w_m, rect_h_m)
    full_bounds = (margin, margin, width - 1 - margin, height - 1 - margin)
    if full_bounds[2] <= full_bounds[0] or full_bounds[3] <= full_bounds[1]:
        raise ValueError("matrix shape is too small for the configured rectangle")
    bounds = full_bounds if search_bounds_m is None else tuple(float(value) for value in search_bounds_m)
    if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
        raise ValueError("search_bounds_m must contain four finite values")
    xmin, ymin, xmax, ymax = bounds
    if (
        xmax <= xmin
        or ymax <= ymin
        or xmin < full_bounds[0]
        or ymin < full_bounds[1]
        or xmax > full_bounds[2]
        or ymax > full_bounds[3]
    ):
        raise ValueError("search_bounds_m must be a non-empty rectangle inside the safe scene bounds")

    rows, columns = _partition_grid(bounds, partition_count)
    row_edges = np.linspace(ymin, ymax, rows + 1)
    column_edges = np.linspace(xmin, xmax, columns + 1)
    child_seeds = np.random.SeedSequence(seed).spawn(partition_count)
    partitions: list[SearchPartition] = []
    for row in range(rows):
        for column in range(columns):
            tile_bounds = (
                float(column_edges[column]),
                float(row_edges[row]),
                float(column_edges[column + 1]),
                float(row_edges[row + 1]),
            )
            if tile_bounds[2] <= tile_bounds[0] or tile_bounds[3] <= tile_bounds[1]:
                raise ValueError("search rectangle is too small for the requested partition count")
            index = row * columns + column
            child_seed = int(child_seeds[index].generate_state(1, dtype=np.uint32)[0])
            partitions.append(
                SearchPartition(
                    partition_id=f"tile-{index + 1:02d}",
                    row=row,
                    column=column,
                    center_bounds_m=tile_bounds,
                    seed=child_seed,
                )
            )
    return partitions


def _partition_grid(bounds: CenterBounds, count: int) -> tuple[int, int]:
    xmin, ymin, xmax, ymax = bounds
    width = xmax - xmin
    height = ymax - ymin
    candidates = [
        (rows, count // rows)
        for rows in range(1, count + 1)
        if count % rows == 0
    ]
    rows, columns = min(
        candidates,
        key=lambda shape: (
            abs(math.log((width / shape[1]) / (height / shape[0]))),
            abs(shape[0] - shape[1]),
            shape[0],
        ),
    )
    return rows, columns


def run_partitioned_guided_search(
    problem: Any,
    modeling: Any,
    config: Any,
    origin: tuple[float, float] | None,
    field: Any,
    partitions: list[SearchPartition],
    max_parallel_tiles: int,
    reporter: Progress,
) -> PartitionedGuidedSearchResult:
    """Run bounded searches against one immutable global context and merge candidates."""

    if not partitions:
        raise ValueError("at least one search partition is required")
    if max_parallel_tiles < 1 or max_parallel_tiles > len(partitions):
        raise ValueError("max_parallel_tiles must be between 1 and the partition count")

    from algorithms.guided_search.search import pose_records, run_guided_search

    progress_lock = Lock()
    tile_progress = {partition.partition_id: 0.0 for partition in partitions}
    last_progress = 0.35

    def run_one(partition: SearchPartition) -> tuple[SearchPartition, Any]:
        tile_config = replace(config, seed=partition.seed)

        def report_tile(progress: float, stage: str, message: str) -> None:
            nonlocal last_progress
            with progress_lock:
                tile_progress[partition.partition_id] = max(
                    tile_progress[partition.partition_id],
                    min(max(float(progress), 0.0), 1.0),
                )
                overall = 0.35 + 0.5 * sum(tile_progress.values()) / len(partitions)
                if overall > last_progress:
                    last_progress = overall
                    reporter(overall, "partition_search", f"{partition.partition_id}: {stage}: {message}")

        result = run_guided_search(
            problem,
            modeling,
            tile_config,
            origin,
            report_tile,
            field=field,
            pose_bounds=partition.pose_bounds,
        )
        return partition, result

    completed: dict[str, tuple[SearchPartition, Any]] = {}
    with ThreadPoolExecutor(
        max_workers=max_parallel_tiles,
        thread_name_prefix="site-search-tile",
    ) as executor:
        futures: dict[Future[tuple[SearchPartition, Any]], SearchPartition] = {
            executor.submit(run_one, partition): partition for partition in partitions
        }
        try:
            for future in as_completed(futures):
                partition, result = future.result()
                completed[partition.partition_id] = (partition, result)
        except Exception:
            for future in futures:
                future.cancel()
            raise

    ordered = [completed[partition.partition_id] for partition in partitions]
    candidate_rows: list[tuple[str, dict[str, Any]]] = []
    partition_records: list[dict[str, Any]] = []
    for partition, result in ordered:
        rows = result.solutions
        partition_records.append(
            {
                "partition_id": partition.partition_id,
                "row": partition.row,
                "column": partition.column,
                "center_bounds_m": list(partition.center_bounds_m),
                "seed": partition.seed,
                "n_solutions": len(rows),
                "n_feasible": sum(bool(row["is_feasible"]) for row in rows),
                **{key: result.normalization[key] for key in
                   ("requested_initialization", "initialization", "initialization_fallback_reason")
                   if key in result.normalization},
            }
        )
        candidate_rows.extend((partition.partition_id, row) for row in rows)

    unique_rows: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[float, float, float]] = set()
    for partition_id, row in candidate_rows:
        key = tuple(round(float(row[name]), 8) for name in ("x", "y", "theta"))
        if key not in seen:
            seen.add(key)
            unique_rows.append((partition_id, row))
    poses = np.asarray(
        [[float(row[name]) for name in ("x", "y", "theta")] for _, row in unique_rows],
        dtype=np.float64,
    )
    raw = np.asarray(
        [[float(row[name]) for name in ("raw_x", "raw_y", "raw_theta")] for _, row in unique_rows],
        dtype=np.float64,
    )
    solution_records = pose_records(problem, modeling, origin, poses, field=field, raw=raw)
    for record, source in zip(solution_records, unique_rows, strict=True):
        record["partition_id"] = source[0]

    first_result = ordered[0][1]
    runtime = {key: first_result.normalization[key] for key in
        ("requested_evolution_backend", "evolution_backend", "device", "backend_fallback_reason", "execution_description")
        if key in first_result.normalization}
    return PartitionedGuidedSearchResult(
        normalization={
            **runtime,
            "algorithm": "partitioned_guided_search",
            "uses_objective_weights": False,
            "partition_count": len(partitions),
            "max_parallel_tiles": max_parallel_tiles,
            "partitions": partition_records,
        },
        solutions=solution_records,
        objective_names=tuple(first_result.objective_names),
        partitions=partition_records,
    )


def launch_partitioned_site_run(
    form: dict[str, Any],
    reporter: Progress,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_root: str | Path = "outputs",
) -> Path:
    """Assemble one reproducible, catalog-compatible partitioned experiment."""

    from config.project_config import load_project_config, save_config, resolve_guided_search_device
    from data_tools.io_utils import write_json
    from experiments.launch_site_run import (
        _haul_origin,
        _publish_search,
        _shared_haul_field,
        apply_site_form,
        constrained_problem,
        prepare_output_dir,
    )
    from experiments.output_writer import write_csv

    base = load_project_config(config_path)
    config = apply_site_form(base, form, "guided_search")
    output_dir = prepare_output_dir(
        Path(output_root),
        str(form["experiment_name"]),
        bool(form.get("overwrite_existing", False)),
    )
    config = replace(config, data=replace(config.data, output_dir=output_dir))
    save_config(config, output_dir / "resolved_config.json")
    write_json(output_dir / "site_form_snapshot.json", form)

    reporter(0.1, "context", "正在读取全局场景数据")
    problem, metadata = constrained_problem(form, resolve_guided_search_device(config.modeling.device))
    partitions = plan_search_partitions(
        problem.dem.shape,
        config.modeling.rect_w_m,
        config.modeling.rect_h_m,
        int(form["partition_count"]),
        config.guided_search.seed,
        form.get("search_bounds_m"),
    )
    metadata = {
        **metadata,
        "partition_count": len(partitions),
        "shared_scene_context": True,
    }
    write_json(output_dir / "data_metadata.json", metadata)
    reporter(0.28, "context", "正在构建全局进站距离场")
    field = _shared_haul_field(
        problem,
        metadata,
        form,
        config.guided_search.access_elevation_weight,
    )
    reporter(0.35, "partition_search", f"开始并行搜索 {len(partitions)} 个矩形分区")
    result = run_partitioned_guided_search(
        problem,
        config.modeling,
        config.guided_search,
        _haul_origin(form),
        field,
        partitions,
        int(form["max_parallel_tiles"]),
        reporter,
    )

    manifest = {
        "coordinate_frame": "scene-local meters; x east, y south",
        "search_bounds_m": list(form["search_bounds_m"]) if form.get("search_bounds_m") else None,
        "partition_count": len(partitions),
        "max_parallel_tiles": int(form["max_parallel_tiles"]),
        "tiles": result.partitions,
    }
    write_json(output_dir / "partition_manifest.json", manifest)
    write_csv(
        output_dir / "partitions.csv",
        result.partitions,
        (
            "partition_id",
            "row",
            "column",
            "center_bounds_m",
            "seed",
            "n_solutions",
            "n_feasible",
        ),
    )
    _publish_search(
        config,
        output_dir,
        problem,
        result,
        reporter,
        summary_extra={
            "algorithm": "guided_search",
            "execution_mode": "rectangular_partitioned",
            "partition_count": len(partitions),
            "max_parallel_tiles": int(form["max_parallel_tiles"]),
            "n_partition_candidates": sum(part["n_solutions"] for part in result.partitions),
        },
    )
    reporter(1.0, "completed", "分区搜索结果已全局复核并写入")
    return output_dir
