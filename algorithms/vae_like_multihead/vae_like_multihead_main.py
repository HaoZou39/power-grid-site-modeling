from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch

from algorithms.common.pareto import extract_feasible_pareto_front
from algorithms.common.scalarization import generate_weight_grid
from config.project_config import ProjectConfig, load_project_config, save_config, validate_cuda_device
from data_tools.dem_tool import build_dem_product
from data_tools.demand_tool import generate_demand_points
from data_tools.io_utils import write_json
from data_tools.landuse_tool import build_landuse_product
from data_tools.traffic_tool import build_road_product
from figures import plot_candidate_map, write_pareto_3d_html

from .vae_like_multihead import VAELikeMultiheadProblem, run_vae_like_multihead


def _tensor_4d(array: np.ndarray, device: torch.device, dtype: torch.dtype = torch.float32) -> torch.Tensor:
    return torch.as_tensor(array, dtype=dtype, device=device)[None, None, :, :]


def _write_csv(path: Path, records: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({name: record.get(name, "") for name in fieldnames})


def _read_validation_preferences(path: Path, device: torch.device) -> torch.Tensor:
    if not path.exists():
        raise FileNotFoundError(path)
    expected = ["preference_id", "weight_dem", "weight_road", "weight_demand"]
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != expected:
            raise ValueError(f"validation preference fields must be {expected}, got {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise ValueError("validation preference CSV must contain at least one row")
    weights: list[list[float]] = []
    for expected_id, row in enumerate(rows):
        if int(row["preference_id"]) != expected_id:
            raise ValueError("validation preference_id must be consecutive from 0")
        weight = [float(row["weight_dem"]), float(row["weight_road"]), float(row["weight_demand"])]
        if not np.isfinite(weight).all() or np.any(np.asarray(weight) < 0) or not np.isclose(sum(weight), 1.0):
            raise ValueError(f"invalid validation preference at row {expected_id}")
        weights.append(weight)
    if len({tuple(weight) for weight in weights}) != len(weights):
        raise ValueError("validation preferences must not contain duplicate rows")
    return torch.as_tensor(weights, dtype=torch.float32, device=device)


def build_problem(
    config: ProjectConfig,
    out: Path,
    device: torch.device,
) -> tuple[VAELikeMultiheadProblem, dict[str, Any]]:
    _, obstacle_mask, landuse_meta = build_landuse_product(
        config.data.landuse_path,
        config.data.obstacle_classes,
        expected_shape=None,
        output_landuse_path=out / "landuse_1m.npy",
        output_obstacle_path=out / "obstacle_mask_1m.npy",
        landuse_input_resolution_m=config.data.landuse_input_resolution_m,
        target_resolution_m=config.data.target_resolution_m,
    )
    primary_grid_shape = obstacle_mask.shape
    dem, dem_meta = build_dem_product(
        config.data.dem_path,
        config.data.reference_geotiff_path,
        primary_grid_shape,
        out / "dem_1m.npy",
        config.data.target_resolution_m,
    )
    road_segments, road_voronoi, road_meta = build_road_product(
        config.data.osm_roads_path,
        out / "road_segments_local.npy",
        out / "road_voronoi_1m.npy",
        config.data.reference_geotiff_path,
        primary_grid_shape,
        config.data.road_dp_tolerance_m,
        config.data.road_resolution_m,
    )
    if road_voronoi.shape != dem.shape:
        raise ValueError(f"road_voronoi shape {road_voronoi.shape} does not match DEM shape {dem.shape}")
    demand_points, demand_weights, demand_meta = generate_demand_points(
        config.data.n_demand_points,
        config.data.demand_seed,
        primary_grid_shape,
        config.data.demand_on_buildable_only,
        obstacle_mask,
    )
    np.save(out / "demand_points.npy", demand_points)
    write_json(out / "demand_points.json", demand_meta)
    problem = VAELikeMultiheadProblem(
        dem=dem,
        obstacle_mask=obstacle_mask,
        road_segments=road_segments,
        dem_tensor=_tensor_4d(dem, device),
        obstacle_tensor=_tensor_4d(obstacle_mask, device),
        road_segments_tensor=torch.as_tensor(road_segments, dtype=torch.float32, device=device),
        road_voronoi_tensor=torch.as_tensor(road_voronoi, dtype=torch.long, device=device),
        demand_points=demand_points,
        demand_weights=demand_weights,
        demand_points_tensor=torch.as_tensor(demand_points, dtype=torch.float32, device=device),
        demand_weights_tensor=None
        if demand_weights is None
        else torch.as_tensor(demand_weights, dtype=torch.float32, device=device),
        device=device,
    )
    return problem, {"dem": dem_meta, "landuse": landuse_meta, "road": road_meta, "demand": demand_meta}


def _write_outputs(
    config: ProjectConfig,
    out: Path,
    problem: VAELikeMultiheadProblem,
    result,
    pareto_records: list[dict[str, Any]],
) -> None:
    write_json(out / "normalization.json", dict(result.normalization))
    history_fields = list(result.training_history[0].keys()) if result.training_history else ["step"]
    for row in result.training_history:
        for name in row:
            if name not in history_fields:
                history_fields.append(name)
    _write_csv(out / "training_history.csv", result.training_history, history_fields)
    solution_fields = list(result.solutions[0].keys()) if result.solutions else ["run_id"]
    _write_csv(out / "solutions.csv", result.solutions, solution_fields)
    _write_csv(out / "pareto_solutions.csv", pareto_records, solution_fields)
    feasible = [record for record in result.solutions if bool(record["is_feasible"])]
    maps = (
        ("all_candidates_points_map.png", feasible, "points", "Hard feasible candidates"),
        ("all_candidates_footprints_map.png", feasible, "footprints", "Hard feasible candidate footprints"),
        ("pareto_points_map.png", pareto_records, "points", "Pareto optimal candidates"),
        ("pareto_footprints_map.png", pareto_records, "footprints", "Pareto optimal footprints"),
    )
    for filename, records, mode, title in maps:
        plot_candidate_map(
            out / filename,
            problem.dem,
            problem.obstacle_mask,
            problem.road_segments,
            problem.demand_points,
            records,
            config.modeling.rect_w_m,
            config.modeling.rect_h_m,
            mode,
            title,
        )
    write_pareto_3d_html(out / "pareto_3d_interactive.html", pareto_records, "Pareto 3D Front")
    n_center = sum(record["inference_mode"] == "center" for record in result.solutions)
    n_sample = len(result.solutions) - n_center
    write_json(
        out / "run_summary.json",
        {
            "n_preferences": len(generate_weight_grid(config.common.weight_grid_step, config.common.min_weight)),
            "n_heads": config.vae_like_multihead.n_heads,
            "n_center_candidates": n_center,
            "n_random_candidates": n_sample,
            "n_solutions": len(result.solutions),
            "n_feasible": len(feasible),
            "n_pareto": len(pareto_records),
            "no_feasible_solution": len(feasible) == 0,
        },
    )


def main(
    config_path: str | Path = "config/default_config.json",
    output_dir: str | Path = "outputs/vae_like_multihead_region",
) -> None:
    try:
        from torch.utils.tensorboard import SummaryWriter
    except ImportError as exc:
        raise ImportError("tensorboard is required for VAE-like training") from exc

    config = load_project_config(config_path)
    device = validate_cuda_device(config.modeling.device)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_config(config, out / "resolved_config.json")
    problem, metadata = build_problem(config, out, device)
    write_json(out / "data_metadata.json", metadata)
    validation_preferences = _read_validation_preferences(
        config.vae_like_multihead.validation_preferences_path,
        device,
    )
    writer = SummaryWriter(log_dir=str(out / "tensorboard"))
    checkpoints = out / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(step: int, model: torch.nn.Module, optimizer: torch.optim.Optimizer) -> None:
        torch.save(
            {
                "step": step,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "algorithm_config": asdict(config.vae_like_multihead),
            },
            checkpoints / f"step_{step:06d}.pt",
        )

    try:
        result = run_vae_like_multihead(
            problem,
            config.modeling,
            config.common,
            config.vae_like_multihead,
            validation_preferences,
            writer=writer,
            checkpoint_callback=save_checkpoint,
        )
    finally:
        writer.close()
    torch.save(
        {
            "model_state_dict": result.model.state_dict(),
            "algorithm_config": asdict(config.vae_like_multihead),
            "normalization": result.normalization,
        },
        out / "model_final.pt",
    )
    pareto_records = extract_feasible_pareto_front(
        result.solutions,
        ("dem_soft", "road_distance", "demand_distance"),
    )
    _write_outputs(config, out, problem, result, pareto_records)
    print(f"VAE-like multi-head outputs: {out}")


if __name__ == "__main__":
    main()
