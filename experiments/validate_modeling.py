from __future__ import annotations

import argparse
import json
from dataclasses import replace
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.project_config import load_project_config, save_config, validate_cuda_device
from data_tools.io_utils import write_json
from experiments.problem_context import build_site_problem_context
from modeling.context import building_hard_mask, soft_obstacle_tensor
from modeling.evaluator import compute_hard_constraints, evaluate_site_objectives
from modeling.pose import decode_raw_pose


def main(
    config_path: str | Path = "config/default_config.json",
    output_dir: str | Path | None = None,
) -> None:
    config = load_project_config(Path(config_path))
    if output_dir is not None:
        config = replace(config, data=replace(config.data, output_dir=Path(output_dir)))
    device = validate_cuda_device(config.modeling.device)
    out = config.data.output_dir
    out.mkdir(parents=True, exist_ok=True)
    save_config(config, out / "resolved_config.json")

    problem, metadata = build_site_problem_context(config, out, device)
    dem_t = problem.dem_tensor
    obstacle_t = soft_obstacle_tensor(problem)
    road_segments_t = problem.road_segments_tensor
    road_voronoi_t = problem.road_voronoi_tensor
    demand_points_t = problem.demand_points_tensor
    demand_weights_t = problem.demand_weights_tensor
    for tensor in (dem_t, obstacle_t, road_segments_t, road_voronoi_t, demand_points_t):
        assert tensor.is_cuda

    raw_pose = torch.tensor(
        [[0.0, 0.0, 0.0], [-0.8, 0.7, 0.3], [0.5, -0.4, -0.6]],
        dtype=torch.float32,
        device=device,
        requires_grad=True,
    )
    pose = decode_raw_pose(raw_pose, problem.dem.shape, config.modeling.rect_w_m, config.modeling.rect_h_m)
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
        problem.dem,
        building_hard_mask(problem),
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
        "data": metadata,
        "objectives": {k: v.detach().cpu().tolist() for k, v in objectives.items()},
        "hard": {k: v.detach().cpu().tolist() for k, v in hard.items()},
        "raw_pose_grad": raw_pose.grad.detach().cpu().tolist(),
    }
    write_json(out / "validation_summary.json", summary)
    print(json.dumps(summary["python_torch"], indent=2))
    print(f"validation outputs: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate the data and modeling pipeline on CUDA.")
    parser.add_argument("--config", default="config/default_config.json")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    main(args.config, args.output_dir)
