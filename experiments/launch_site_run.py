"""Launch one siting job through the guided search, CMA-ES, or Adam.

The decision button uses the guided search and its active objectives without weights.
CMA-ES remains available for the research weight-grid entry. Adam, if invoked,
still uses the submitted weight vector. VAE-like is not started from this launcher.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

import numpy as np

from experiments.output_writer import prepare_output_dir
from experiments.site_context import constrained_problem, haul_origin as _haul_origin, shared_haul_field as _shared_haul_field

from config.project_config import DEFAULT_CONFIG_PATH, ProjectConfig, ModelingConfig, load_project_config, load_default_config

Progress = Callable[[float, str, str], None]
_LOGGER = logging.getLogger("uvicorn.error")
_SCORED_SCENE_LOCK = threading.Lock()


def search_weights(form: dict[str, Any], algorithm: str) -> list[np.ndarray] | None:
    """CMA-ES uses the project weight grid. The guided search does not use weights."""

    if algorithm in {"cma_es", "guided_search"}:
        return None
    return [form_weight(form["objective_weights"])]


def form_weight(weights: dict[str, Any]) -> np.ndarray:
    """Return the three objective weights in dem, road, demand order."""

    try:
        vector = np.array(
            [
                float(weights["dem_soft"]),
                float(weights["road_distance"]),
                float(weights["demand_distance"]),
            ],
            dtype=np.float64,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("objective_weights must contain dem_soft, road_distance, and demand_distance") from exc
    if vector.shape != (3,) or not np.isfinite(vector).all():
        raise ValueError("objective_weights must be three finite numbers")
    return vector


def apply_site_form(base: ProjectConfig, form: dict[str, Any], algorithm: str) -> ProjectConfig:
    """Overlay the decision form onto the project config without changing data paths."""

    modeling = replace(
        base.modeling,
        rect_w_m=float(form["rect_w_m"]),
        rect_h_m=float(form["rect_h_m"]),
        device=str(form["device"]),
        road_setback_m=float(form.get("road_setback_m", base.modeling.road_setback_m)),
        water_setback_m=float(form.get("water_setback_m", base.modeling.water_setback_m)),
        highway_setback_m=float(form.get("highway_setback_m", base.modeling.highway_setback_m)),
    )
    data = replace(base.data, demand_on_buildable_only=bool(form["demand_on_buildable_only"]))
    if algorithm == "guided_search":
        guided_search = replace(
            base.guided_search,
            seed=int(form["seed"]),
            popsize=int(form["popsize"]),
            initialization=str(form.get("initialization", base.guided_search.initialization)),
            evaluation_batch_size=int(form.get("evaluation_batch_size", base.guided_search.evaluation_batch_size)),
            evolution_backend=str(form.get("evolution_backend", base.guided_search.evolution_backend)),
            sigma0=float(form["sigma0"]),
            generations=int(form["generations"]),
            include_demand=bool(form.get("include_demand", base.guided_search.include_demand)),
            diagonal_access=True,
        )
        return replace(base, data=data, modeling=modeling, guided_search=guided_search, experiment_name=str(form["experiment_name"]))
    if algorithm == "cma_es":
        cma_es = replace(
            base.cma_es,
            seed=int(form["seed"]),
            popsize=int(form["popsize"]),
            sigma0=float(form["sigma0"]),
            max_iters=int(form["max_iters"]),
            restarts_per_weight=int(form["restarts_per_weight"]),
        )
        return replace(base, data=data, modeling=modeling, cma_es=cma_es, experiment_name=str(form["experiment_name"]))
    if algorithm == "multistart_adam":
        multistart = replace(
            base.multistart_adam,
            seed=int(form["seed"]),
            starts_per_weight=int(form["starts_per_weight"]),
            max_steps=int(form["max_steps"]),
            learning_rate=float(form["learning_rate"]),
            init_eps=float(form["init_eps"]),
        )
        return replace(
            base,
            data=data,
            modeling=modeling,
            multistart_adam=multistart,
            experiment_name=str(form["experiment_name"]),
        )
    raise ValueError(f"unknown siting algorithm {algorithm!r}")


def evaluate_form_poses(
    form: dict[str, Any],
    poses: list[tuple[float, float, float]],
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> list[dict[str, Any]]:
    """按这张表单的约束，用决策搜索的同一口径重算若干个解码后的位姿。"""

    from algorithms.guided_search.search import pose_records

    project_config = load_project_config(config_path)
    modeling = replace(
        project_config.modeling,
        rect_w_m=float(form["rect_w_m"]),
        rect_h_m=float(form["rect_h_m"]),
    )
    from experiments.haul_field_cache import scene_source_signature
    from experiments.scene_store import DEFAULT_SCENE, scene_directory, scenes_root

    from modeling.context import require_road_setback_m, require_water_setback_m

    constraints = {key: form.get(key) for key in _CONSTRAINT_KEYS}
    constraints["road_setback_m"] = require_road_setback_m(form.get("road_setback_m", modeling.road_setback_m))
    constraints["water_setback_m"] = require_water_setback_m(form.get("water_setback_m", modeling.water_setback_m))
    constraints["access_elevation_weight"] = project_config.guided_search.access_elevation_weight
    constraints["highway_setback_m"] = require_road_setback_m(form.get("highway_setback_m", modeling.highway_setback_m))
    # 旧表单里的 false 不恢复四连通。缓存键因此始终是八连通。
    constraints["diagonal_access"] = True
    scene = scene_directory(scenes_root(None), str(form.get("scene_name") or DEFAULT_SCENE))
    started = perf_counter()
    # 重新构建场景后文件时间变了，缓存随之失效。场景锁只在 constrained_problem 读快照时持有，
    # 进站距离场在锁外读取或构建，提交优化不必等它。这把进程内锁让同一约束的并发批次只算一次。
    with _SCORED_SCENE_LOCK:
        constraints["scene_signature"] = scene_source_signature(scene, uses_landuse=True)
        hits = _scored_scene.cache_info().hits
        problem, field = _scored_scene(json.dumps(constraints, sort_keys=True), modeling.device)
        scene_cache = "memory_hit" if _scored_scene.cache_info().hits > hits else "miss"
    scene_seconds = perf_counter() - started
    records = pose_records(problem, modeling, _haul_origin(form), np.asarray(poses, dtype=np.float64), field=field)
    _LOGGER.info(
        "pose_objectives total_s=%.3f scene_cache=%s scene_s=%.3f eval_s=%.3f poses=%d scene=%s",
        perf_counter() - started,
        scene_cache,
        scene_seconds,
        perf_counter() - started - scene_seconds,
        len(poses),
        scene.name,
    )
    return records


# 这组字段决定重算时复用的场景和建筑硬掩膜。道路退距与水体退距都不进入进站距离场的缓存键。
_CONSTRAINT_KEYS = (
    "scene_name",
    "mountain_policy",
    "field_policy",
    "field_cost",
    "exclusion_zones",
    "feasible_zones",
    "origin_x",
    "origin_y",
    "road_setback_m",
    "water_setback_m",
    "highway_setback_m",
    "max_elevation_m",
)


@lru_cache(maxsize=4)
def _scored_scene(constraints_json: str, device_name: str) -> tuple[Any, Any]:
    from config.project_config import resolve_guided_search_device

    form = json.loads(constraints_json)
    started = perf_counter()
    problem, metadata = constrained_problem(form, resolve_guided_search_device(device_name), load_default_config().modeling)
    problem_seconds = perf_counter() - started
    field = _shared_haul_field(
        problem,
        metadata,
        form,
        float(form.get("access_elevation_weight", 1.0)),
    )
    _LOGGER.info(
        "pose_objectives scene_build problem_s=%.3f field_s=%.3f scene=%s",
        problem_seconds,
        perf_counter() - started - problem_seconds,
        Path(metadata["scene_dir"]).name,
    )
    return problem, field


def _publish_search(
    config: ProjectConfig,
    output_dir: Path,
    problem: Any,
    result: Any,
    reporter: Progress,
    *,
    run_records: list[dict[str, Any]] | None = None,
    summary_extra: dict[str, Any],
) -> None:
    """Write the shared maps and Pareto files after a search has finished."""

    from algorithms.common.pareto import extract_feasible_pareto_front
    from algorithms.common.scalarization import OBJECTIVE_NAMES
    from algorithms.guided_search.batch_planner import write_resolved_batch_plan
    from experiments.auto_result_retention import auto_marker_fields, snapshot_scene_name
    from experiments.output_writer import write_standard_outputs

    batch_plan = result.normalization.get("batch_plan")
    if isinstance(batch_plan, dict):
        write_resolved_batch_plan(output_dir / "resolved_config.json", batch_plan)

    names = tuple(getattr(result, "objective_names", OBJECTIVE_NAMES))
    pareto_records = extract_feasible_pareto_front(result.solutions, names)
    execution = result.normalization.get("execution_description")
    message = "正在保存优化结果（CSV / JSON）"
    reporter(0.9, "figures", f"{execution}｜{message}" if execution else message)
    write_standard_outputs(
        config,
        output_dir,
        problem,
        result.normalization,
        result.solutions,
        pareto_records,
        run_records=run_records,
        summary_extra={**summary_extra, **auto_marker_fields(snapshot_scene_name(output_dir), "site")},
        objective_names=names,
    )


def launch_site_run(
    form: dict[str, Any],
    algorithm: str,
    reporter: Progress,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_root: str | Path | None = None,
) -> Path:
    """Publish a complete run, preserving the old experiment if its replacement fails."""

    base = load_project_config(config_path)
    config = apply_site_form(base, form, algorithm)
    output_dir = prepare_output_dir(
        Path(output_root or os.getenv("EXPERIMENT_OUTPUT_ROOT", "outputs")),
        str(form["experiment_name"]),
        bool(form.get("overwrite_existing", False)),
    )
    config = replace(config, data=replace(config.data, output_dir=output_dir))
    from experiments.output_writer import staged_experiment
    with staged_experiment(output_dir, overwrite=bool(form.get("overwrite_existing", False))) as staged:
        _run_site_search(form, algorithm, reporter, config, staged)
    from experiments.auto_result_retention import retain_published_auto_result
    retain_published_auto_result(output_dir, "site")
    return output_dir


def _run_site_search(
    form: dict[str, Any],
    algorithm: str,
    reporter: Progress,
    config: ProjectConfig,
    output_dir: Path,
) -> None:
    from config.project_config import save_config, validate_cuda_device, resolve_guided_search_device
    from data_tools.io_utils import write_json

    save_config(config, output_dir / "resolved_config.json")
    write_json(output_dir / "site_form_snapshot.json", form)
    reporter(0.1, "context", "正在读取已构建的场景数据")
    device = resolve_guided_search_device(config.modeling.device) if algorithm == "guided_search" else validate_cuda_device(config.modeling.device)
    execution = None
    if algorithm == "guided_search":
        from algorithms.guided_search.evolution import describe_evolution_runtime

        execution = describe_evolution_runtime(config.guided_search.evolution_backend, device)
        reporter(0.12, "context", f"{execution}｜正在加载场景与约束")
    problem, metadata = constrained_problem(form, device, config.modeling)
    write_json(output_dir / "data_metadata.json", metadata)
    if algorithm == "guided_search":
        from algorithms.guided_search.search import guided_objective_names

        names = guided_objective_names(_haul_origin(form) is not None, config.guided_search.include_demand)
        search_message = f"{execution}｜比较 {len(names)} 个目标；正在读取或构建进站距离场（CPU）"
    elif algorithm == "cma_es":
        search_message = "正在沿权重网格搜索帕累托方案"
    else:
        search_message = "正在按提交的目标权重运行优化"
    reporter(0.35, "haul_field" if algorithm == "guided_search" else "search", search_message)
    if algorithm == "guided_search":
        from algorithms.guided_search.search import run_guided_search

        field = _shared_haul_field(
            problem,
            metadata,
            form,
            config.guided_search.access_elevation_weight,
        )
        result = run_guided_search(
            problem,
            config.modeling,
            config.guided_search,
            _haul_origin(form),
            reporter,
            field=field,
        )
        _publish_search(
            config,
            output_dir,
            problem,
            result,
            reporter,
            summary_extra={"n_runs": config.guided_search.generations, "algorithm": "guided_search"},
        )
    elif algorithm == "cma_es":
        from algorithms.cma_es.cma_es import run_cma_es_search

        result = run_cma_es_search(
            problem,
            config.modeling,
            config.common,
            config.cma_es,
            weights=search_weights(form, algorithm),
        )
        _publish_search(
            config,
            output_dir,
            problem,
            result,
            reporter,
            run_records=result.runs,
            summary_extra={"n_runs": len(result.runs)},
        )
    elif algorithm == "multistart_adam":
        from algorithms.multistart_adam.multistart_adam import run_multistart_adam_search

        result = run_multistart_adam_search(
            problem,
            config.modeling,
            config.common,
            config.multistart_adam,
            weights=search_weights(form, algorithm),
        )
        _publish_search(
            config,
            output_dir,
            problem,
            result,
            reporter,
            run_records=result.runs,
            summary_extra={"n_runs": len(result.runs)},
        )
    else:
        raise ValueError(f"unknown siting algorithm {algorithm!r}")
    reporter(1.0, "completed", "实验产物已写入")
