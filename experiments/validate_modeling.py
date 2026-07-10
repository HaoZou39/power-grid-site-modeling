from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from config.project_config import load_project_config, save_config, validate_cuda_device
from data_tools.dem_tool import build_dem_product
from data_tools.demand_tool import generate_demand_points
from data_tools.io_utils import write_json
from data_tools.landuse_tool import build_landuse_product
from data_tools.traffic_tool import build_road_product
from modeling.evaluator import compute_hard_constraints, evaluate_site_objectives
from modeling.pose import decode_raw_pose


def _tensor_4d(array: np.ndarray, device: torch.device, dtype: torch.dtype = torch.float32) -> torch.Tensor:
    return torch.as_tensor(array, dtype=dtype, device=device)[None, None, :, :]


def main() -> None:
    config = load_project_config(Path("config/default_config.json"))
    device = validate_cuda_device(config.modeling.device)
    out = config.data.output_dir
    out.mkdir(parents=True, exist_ok=True)
    save_config(config, out / "resolved_config.json")

    dem, dem_meta = build_dem_product(
        config.data.dem_path,
        out / "dem_1m.npy",
        config.data.dem_input_resolution_m,
        config.data.target_resolution_m,
    )
    landuse, obstacle_mask, landuse_meta = build_landuse_product(
        config.data.landuse_path,
        config.data.obstacle_classes,
        expected_shape=dem.shape,
        output_landuse_path=out / "landuse_1m.npy",
        output_obstacle_path=out / "obstacle_mask_1m.npy",
        landuse_input_resolution_m=config.data.landuse_input_resolution_m,
        target_resolution_m=config.data.target_resolution_m,
    )
    expected_side = int(round(2 * config.data.half_side_m))
    if dem.shape != (expected_side, expected_side):
        raise ValueError(f"DEM shape {dem.shape} does not match half_side_m-derived shape {(expected_side, expected_side)}")
    road_segments, road_voronoi, road_meta = build_road_product(
        config.data.osm_roads_path,
        out / "road_segments_local.npy",
        out / "road_voronoi_1m.npy",
        config.data.center_lon,
        config.data.center_lat,
        config.data.half_side_m,
        config.data.road_dp_tolerance_m,
        config.data.road_resolution_m,
    )
    if road_voronoi.shape != dem.shape:
        raise ValueError(f"road_voronoi shape {road_voronoi.shape} does not match DEM shape {dem.shape}")
    demand_points, demand_weights, demand_meta = generate_demand_points(
        config.data.n_demand_points,
        config.data.demand_seed,
        config.data.half_side_m,
        config.data.demand_on_buildable_only,
        obstacle_mask,
    )
    np.save(out / "demand_points.npy", demand_points)
    write_json(out / "demand_points.json", demand_meta)

    dem_t = _tensor_4d(dem, device)
    obstacle_t = _tensor_4d(obstacle_mask, device)
    road_segments_t = torch.as_tensor(road_segments, dtype=torch.float32, device=device)
    road_voronoi_t = torch.as_tensor(road_voronoi, dtype=torch.long, device=device)
    demand_points_t = torch.as_tensor(demand_points, dtype=torch.float32, device=device)
    demand_weights_t = None if demand_weights is None else torch.as_tensor(demand_weights, dtype=torch.float32, device=device)
    for tensor in (dem_t, obstacle_t, road_segments_t, road_voronoi_t, demand_points_t):
        assert tensor.is_cuda

    raw_pose = torch.tensor(
        [[0.0, 0.0, 0.0], [-0.8, 0.7, 0.3], [0.5, -0.4, -0.6]],
        dtype=torch.float32,
        device=device,
        requires_grad=True,
    )
    pose = decode_raw_pose(raw_pose, dem.shape, config.modeling.rect_w_m, config.modeling.rect_h_m)
    assert pose.is_cuda
    objectives = evaluate_site_objectives(
        dem_t,
        obstacle_t,
        road_segments_t,
        road_voronoi_t,
        demand_points_t,
        demand_weights_t,
        pose,
        config.modeling.rect_w_m,
        config.modeling.rect_h_m,
        config.modeling.soft_mask_sharpness,
    )
    for name, value in objectives.items():
        if value.shape != (raw_pose.shape[0],):
            raise ValueError(f"{name} has shape {tuple(value.shape)}")
        if not value.is_cuda or not torch.isfinite(value).all():
            raise ValueError(f"{name} is not finite CUDA output")
    soft_total = sum(objectives.values())
    soft_total.sum().backward()
    if raw_pose.grad is None or not raw_pose.grad.is_cuda or not torch.isfinite(raw_pose.grad).all():
        raise ValueError("raw_pose gradient is missing, not CUDA, or not finite")

    hard = compute_hard_constraints(
        dem,
        obstacle_mask,
        pose.detach(),
        config.modeling.rect_w_m,
        config.modeling.rect_h_m,
        device=str(device),
    )
    for name, value in hard.items():
        if value.shape != (raw_pose.shape[0],):
            raise ValueError(f"{name} has shape {tuple(value.shape)}")
        if not value.is_cuda:
            raise ValueError(f"{name} is not CUDA output")
        if value.dtype != torch.bool and not torch.isfinite(value).all():
            raise ValueError(f"{name} contains NaN or Inf")

    summary = {
        "python_torch": {
            "torch": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "cuda_version": torch.version.cuda,
            "device_count": torch.cuda.device_count(),
            "device_name": torch.cuda.get_device_name(0),
            "memory_allocated": torch.cuda.memory_allocated(),
            "max_memory_allocated": torch.cuda.max_memory_allocated(),
        },
        "data": {
            "dem": dem_meta,
            "landuse": landuse_meta,
            "road": road_meta,
            "demand": demand_meta,
        },
        "objectives": {k: v.detach().cpu().tolist() for k, v in objectives.items()},
        "hard": {k: v.detach().cpu().tolist() for k, v in hard.items()},
        "raw_pose_grad": raw_pose.grad.detach().cpu().tolist(),
    }
    write_json(out / "validation_summary.json", summary)
    print(json.dumps(summary["python_torch"], indent=2))
    print(f"validation outputs: {out}")


if __name__ == "__main__":
    main()
