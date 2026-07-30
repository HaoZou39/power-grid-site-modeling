from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
import torch

from config.project_config import ProjectConfig, load_project_config, save_config, validate_cuda_device
from data_tools.dem_tool import build_dem_product
from data_tools.demand_tool import generate_demand_points
from data_tools.io_utils import write_json
from data_tools.landuse_tool import build_landuse_product
from data_tools.traffic_tool import build_road_product
from algorithms.common.pareto import extract_feasible_pareto_front
from figures import plot_candidate_map, write_pareto_3d_html

from .cma_es import CMAESProblem, run_cma_es_search

SOLUTION_FIELDS = [
    "run_id",
    "weight_dem",
    "weight_road",
    "weight_demand",
    "raw_x",
    "raw_y",
    "raw_theta",
    "x",
    "y",
    "theta",
    "scalar",
    "dem_soft",
    "obstacle_soft",
    "road_distance",
    "demand_distance",
    "dem_hard_var",
    "dem_hard_range",
    "obstacle_hard_count",
    "obstacle_hard_ratio",
    "is_feasible",
]


def _tensor_4d(array: np.ndarray, device: torch.device, dtype: torch.dtype = torch.float32) -> torch.Tensor:
    return torch.as_tensor(array, dtype=dtype, device=device)[None, None, :, :]


def _write_csv(path: Path, records: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({name: record.get(name, "") for name in fieldnames})


def build_problem(config: ProjectConfig, out: Path, device: torch.device) -> tuple[CMAESProblem, dict[str, Any]]:
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
    problem = CMAESProblem(
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
        demand_weights_tensor=None if demand_weights is None else torch.as_tensor(demand_weights, dtype=torch.float32, device=device),
        device=device,
    )
    metadata = {"dem": dem_meta, "landuse": landuse_meta, "road": road_meta, "demand": demand_meta}
    return problem, metadata


def write_outputs(config: ProjectConfig, out: Path, problem: CMAESProblem, result, pareto_records: list[dict[str, Any]]) -> None:
    write_json(out / "normalization.json", dict(result.normalization))
    _write_csv(out / "runs.csv", result.runs, list(result.runs[0].keys()) if result.runs else ["run_id"])
    _write_csv(out / "solutions.csv", result.solutions, SOLUTION_FIELDS)
    _write_csv(out / "pareto_solutions.csv", pareto_records, SOLUTION_FIELDS)
    feasible = [record for record in result.solutions if bool(record["is_feasible"])]
    plot_candidate_map(
        out / "all_candidates_points_map.png",
        problem.dem,
        problem.obstacle_mask,
        problem.road_segments,
        problem.demand_points,
        feasible,
        config.modeling.rect_w_m,
        config.modeling.rect_h_m,
        "points",
        "Hard feasible candidates",
    )
    plot_candidate_map(
        out / "all_candidates_footprints_map.png",
        problem.dem,
        problem.obstacle_mask,
        problem.road_segments,
        problem.demand_points,
        feasible,
        config.modeling.rect_w_m,
        config.modeling.rect_h_m,
        "footprints",
        "Hard feasible candidate footprints",
    )
    plot_candidate_map(
        out / "pareto_points_map.png",
        problem.dem,
        problem.obstacle_mask,
        problem.road_segments,
        problem.demand_points,
        pareto_records,
        config.modeling.rect_w_m,
        config.modeling.rect_h_m,
        "points",
        "Pareto optimal candidates",
    )
    plot_candidate_map(
        out / "pareto_footprints_map.png",
        problem.dem,
        problem.obstacle_mask,
        problem.road_segments,
        problem.demand_points,
        pareto_records,
        config.modeling.rect_w_m,
        config.modeling.rect_h_m,
        "footprints",
        "Pareto optimal footprints",
    )
    write_pareto_3d_html(out / "pareto_3d_interactive.html", pareto_records, "Pareto 3D Front")
    write_json(
        out / "run_summary.json",
        {
            "n_runs": len(result.runs),
            "n_solutions": len(result.solutions),
            "n_feasible": len(feasible),
            "n_pareto": len(pareto_records),
            "no_feasible_solution": len(feasible) == 0,
        },
    )


def main(config_path: str | Path = "config/default_config.json", output_dir: str | Path = "outputs/cmaes_region") -> None:
    config = load_project_config(config_path)
    device = validate_cuda_device(config.modeling.device)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_config(config, out / "resolved_config.json")
    problem, metadata = build_problem(config, out, device)
    write_json(out / "data_metadata.json", metadata)
    result = run_cma_es_search(problem, config.modeling, config.common, config.cma_es)
    pareto_records = extract_feasible_pareto_front(result.solutions, ("dem_soft", "road_distance", "demand_distance"))
    write_outputs(config, out, problem, result, pareto_records)
    print(f"CMA-ES outputs: {out}")


if __name__ == "__main__":
    main()
