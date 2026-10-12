"""Launch one siting job through NSGA-II, CMA-ES, or Adam.

The decision button uses NSGA-II. It compares four objectives, or five when an origin is set, and does not ask for weights.
CMA-ES remains available for the research weight-grid entry. Adam, if invoked,
still uses the submitted weight vector. VAE-like is not started from this launcher.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

from config.project_config import ProjectConfig, load_project_config

Progress = Callable[[float, str, str], None]


def search_weights(form: dict[str, Any], algorithm: str) -> list[np.ndarray] | None:
    """CMA-ES uses the project weight grid. NSGA-II does not use weights."""

    if algorithm in {"cma_es", "nsga2"}:
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
    if algorithm == "nsga2":
        nsga2 = replace(
            base.nsga2,
            seed=int(form["seed"]),
            popsize=int(form["popsize"]),
            sigma0=float(form["sigma0"]),
            generations=int(form["generations"]),
            include_demand=bool(form.get("include_demand", False)),
        )
        return replace(base, data=data, modeling=modeling, nsga2=nsga2, experiment_name=str(form["experiment_name"]))
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
    )


def launch_site_run(
    form: dict[str, Any],
    algorithm: str,
    reporter: Progress,
    config_path: str | Path = "config/default_config.json",
    output_root: str | Path = "outputs",
) -> Path:
    """Run one existing algorithm entry and write its catalog directory."""

    from config.project_config import save_config, validate_cuda_device
    from data_tools.io_utils import write_json
    from experiments.constraint_mask import compose_constraint_masks, polygons_from_form, policy_from_form
    from experiments.problem_context import with_constraint_masks
    from experiments.scene_store import DEFAULT_SCENE, load_scene

    base = load_project_config(config_path)
    config = apply_site_form(base, form, algorithm)
    output_dir = prepare_output_dir(
        Path(output_root),
        str(form["experiment_name"]),
        bool(form.get("overwrite_existing", False)),
    )
    config = replace(config, data=replace(config.data, output_dir=output_dir))
    save_config(config, output_dir / "resolved_config.json")
    reporter(0.1, "context", "正在读取已构建的场景数据")
    device = validate_cuda_device(config.modeling.device)
    problem, metadata = load_scene(str(form.get("scene_name") or DEFAULT_SCENE), device)
    scene_dir = Path(metadata["scene_dir"])
    landuse_path = scene_dir / "landuse_1m.npy"
    if not landuse_path.is_file():
        raise FileNotFoundError(f"场景 {scene_dir.name} 缺少 landuse_1m.npy，无法按用地类别合成约束")
    landuse = np.load(landuse_path)
    policy = policy_from_form(form)
    zones = polygons_from_form(form)
    feasible = polygons_from_form(form, "feasible_zones")
    hard_mask, soft_mask = compose_constraint_masks(landuse, zones, policy, feasible)
    problem = with_constraint_masks(problem, hard_mask, soft_mask)
    metadata = {
        **metadata,
        "field_policy": str(form.get("field_policy") or "allowed"),
        "mountain_policy": str(form.get("mountain_policy") or "allowed"),
        "field_cost": float(form.get("field_cost", 0.5)),
        "exclusion_zone_count": len(zones),
        "feasible_zone_count": len(feasible),
    }
    write_json(output_dir / "data_metadata.json", metadata)
    if algorithm == "nsga2":
        search_message = (
            "正在用 NSGA-II 比较五个目标，包含沿路运输"
            if _haul_origin(form) is not None
            else "正在用 NSGA-II 比较四个目标，不含沿路运输"
        )
    elif algorithm == "cma_es":
        search_message = "正在沿权重网格搜索帕累托方案"
    else:
        search_message = "正在按提交的目标权重运行优化"
    reporter(0.35, "search", search_message)
    if algorithm == "nsga2":
        from algorithms.nsga2.nsga2 import run_nsga2_search

        result = run_nsga2_search(problem, config.modeling, config.nsga2, _haul_origin(form), reporter)
        _publish_search(
            config,
            output_dir,
            problem,
            result,
            reporter,
            summary_extra={"n_runs": config.nsga2.generations, "algorithm": "nsga2"},
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
    return output_dir
