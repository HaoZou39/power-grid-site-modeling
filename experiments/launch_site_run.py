"""Launch one siting job through the guided search, CMA-ES, or Adam.

The decision button uses the guided search. It compares four objectives, or five when an origin is set, and does not ask for weights.
CMA-ES remains available for the research weight-grid entry. Adam, if invoked,
still uses the submitted weight vector. VAE-like is not started from this launcher.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Callable

import numpy as np

from config.project_config import ProjectConfig, load_project_config

Progress = Callable[[float, str, str], None]


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


def prepare_output_dir(output_root: Path, experiment_name: str, overwrite: bool) -> Path:
    """Create one catalog directory. Refuse path escape and silent overwrite."""

    name = experiment_name.strip()
    if not name or name in {".", ".."} or any(separator in name for separator in ("/", "\\")):
        raise ValueError("experiment_name must be a single directory name")
    root = output_root.expanduser().resolve()
    path = (root / name).resolve()
    if path.parent != root:
        raise ValueError("experiment_name must stay inside the output root")
    if (path / "run_summary.json").is_file() and not overwrite:
        raise ValueError(f"experiment already exists: {name}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def apply_site_form(base: ProjectConfig, form: dict[str, Any], algorithm: str) -> ProjectConfig:
    """Overlay the decision form onto the project config without changing data paths."""

    modeling = replace(
        base.modeling,
        rect_w_m=float(form["rect_w_m"]),
        rect_h_m=float(form["rect_h_m"]),
        device=str(form["device"]),
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
            include_demand=bool(form.get("include_demand", False)),
            diagonal_access=bool(form.get("diagonal_access", False)),
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


def _haul_origin(form: dict[str, Any]) -> tuple[float, float] | None:
    """进货原点。不填就不比较沿路运输长度。"""

    x = form.get("origin_x")
    y = form.get("origin_y")
    if x is None and y is None:
        return None
    if x is None or y is None:
        raise ValueError("进货原点需要同时给出 x 和 y")
    return float(x), float(y)


def constrained_problem(form: dict[str, Any], device: Any) -> tuple[Any, dict[str, Any]]:
    """已构建的场景加上表单里的用地策略、禁区和可行域。"""

    from experiments.constraint_mask import compose_constraint_masks, polygons_from_form, policy_from_form
    from experiments.problem_context import with_constraint_masks
    from experiments.scene_store import DEFAULT_SCENE, load_scene
    from modeling.context import require_road_setback_m

    setback = require_road_setback_m(form.get("road_setback_m", 5.0))
    problem, metadata = load_scene(
        str(form.get("scene_name") or DEFAULT_SCENE),
        device,
        road_setback_m=setback,
    )
    scene_dir = Path(metadata["scene_dir"])
    landuse_path = scene_dir / "landuse_1m.npy"
    if not landuse_path.is_file():
        raise FileNotFoundError(f"场景 {scene_dir.name} 缺少 landuse_1m.npy，无法按用地类别合成约束")
    zones = polygons_from_form(form)
    feasible = polygons_from_form(form, "feasible_zones")
    hard_mask, soft_mask = compose_constraint_masks(np.load(landuse_path), zones, policy_from_form(form), feasible)
    metadata = {
        **metadata,
        "field_policy": str(form.get("field_policy") or "allowed"),
        "mountain_policy": str(form.get("mountain_policy") or "allowed"),
        "field_cost": float(form.get("field_cost", 0.5)),
        "exclusion_zone_count": len(zones),
        "feasible_zone_count": len(feasible),
        "road_setback_m": setback,
    }
    return with_constraint_masks(problem, hard_mask, soft_mask, road_setback_m=setback), metadata


def _shared_haul_field(
    problem: Any,
    metadata: dict[str, Any],
    form: dict[str, Any],
    access_elevation_weight: float = 1.0,
) -> Any:
    """Use the scene volume so Worker and API can share one compatible field."""

    from experiments.haul_field_cache import get_or_build_haul_field

    return get_or_build_haul_field(
        metadata["scene_dir"],
        problem.dem,
        problem.obstacle_mask == 0,
        problem.road_segments,
        _haul_origin(form),
        form,
        uses_landuse=True,
        access_elevation_weight=access_elevation_weight,
    ).field


def evaluate_form_poses(
    form: dict[str, Any],
    poses: list[tuple[float, float, float]],
    config_path: str | Path = "config/default_config.json",
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

    from modeling.context import require_road_setback_m

    constraints = {key: form.get(key) for key in _CONSTRAINT_KEYS}
    constraints["road_setback_m"] = require_road_setback_m(form.get("road_setback_m", 5.0))
    constraints["access_elevation_weight"] = project_config.guided_search.access_elevation_weight
    # 关闭时不进入键，进程内横竖场缓存与原来相同。
    if form.get("diagonal_access"):
        constraints["diagonal_access"] = True
    scene = scene_directory(scenes_root(None), str(form.get("scene_name") or DEFAULT_SCENE))
    # 重新构建场景后文件时间变了，缓存随之失效。
    constraints["scene_signature"] = scene_source_signature(scene, uses_landuse=True)
    problem, field = _scored_scene(json.dumps(constraints, sort_keys=True), modeling.device)
    return pose_records(problem, modeling, _haul_origin(form), np.asarray(poses, dtype=np.float64), field=field)


# 这组字段决定重算时复用的场景。道路退距只改变建筑硬掩膜；进站距离场的缓存键仍不含它。
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
)


@lru_cache(maxsize=4)
def _scored_scene(constraints_json: str, device_name: str) -> tuple[Any, Any]:
    from config.project_config import resolve_guided_search_device

    form = json.loads(constraints_json)
    problem, metadata = constrained_problem(form, resolve_guided_search_device(device_name))
    field = _shared_haul_field(
        problem,
        metadata,
        form,
        float(form.get("access_elevation_weight", 1.0)),
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
    from experiments.output_writer import write_standard_outputs

    names = tuple(getattr(result, "objective_names", OBJECTIVE_NAMES))
    pareto_records = extract_feasible_pareto_front(result.solutions, names)
    reporter(0.9, "figures", "正在写入地图和 Pareto 图")
    write_standard_outputs(
        config,
        output_dir,
        problem,
        result.normalization,
        result.solutions,
        pareto_records,
        run_records=run_records,
        summary_extra=summary_extra,
        objective_names=names,
    )


def launch_site_run(
    form: dict[str, Any],
    algorithm: str,
    reporter: Progress,
    config_path: str | Path = "config/default_config.json",
    output_root: str | Path = "outputs",
) -> Path:
    """Publish a complete run, preserving the old experiment if its replacement fails."""

    base = load_project_config(config_path)
    config = apply_site_form(base, form, algorithm)
    output_dir = prepare_output_dir(
        Path(output_root),
        str(form["experiment_name"]),
        bool(form.get("overwrite_existing", False)),
    )
    config = replace(config, data=replace(config.data, output_dir=output_dir))
    staging_root = Path(mkdtemp(prefix=".site-run-", dir=output_dir.parent))
    staged = staging_root / "run"
    previous = staging_root / "previous"
    staged.mkdir()
    try:
        _run_site_search(form, algorithm, reporter, config, staged)
        if not (staged / "run_summary.json").is_file():
            raise ValueError("search did not write run_summary.json")
        if (output_dir / "run_summary.json").is_file() and not form.get("overwrite_existing", False):
            raise ValueError(f"experiment already exists: {output_dir.name}")
        output_dir.rename(previous)
        try:
            staged.rename(output_dir)
        except OSError:
            previous.rename(output_dir)
            raise
        shutil.rmtree(previous)
    finally:
        # 恢复旧目录本身若失败，保留 previous 供人工恢复。
        if not previous.exists():
            shutil.rmtree(staging_root)
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
    problem, metadata = constrained_problem(form, device)
    write_json(output_dir / "data_metadata.json", metadata)
    if algorithm == "guided_search":
        search_message = (
            "正在用引导式多目标搜索比较五个目标，包含沿路运输"
            if _haul_origin(form) is not None
            else "正在用引导式多目标搜索比较四个目标，不含沿路运输"
        )
    elif algorithm == "cma_es":
        search_message = "正在沿权重网格搜索帕累托方案"
    else:
        search_message = "正在按提交的目标权重运行优化"
    reporter(0.35, "search", search_message)
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
