from __future__ import annotations

import numpy as np
import torch

from algorithms.multistart_adam.multistart_adam import (
    MultiStartAdamProblem,
    initialize_raw_pose_starts,
    run_multistart_adam_search,
)
from config.project_config import AlgorithmCommonConfig, ModelingConfig, MultiStartAdamConfig


def _synthetic_problem(device: torch.device) -> MultiStartAdamProblem:
    h, w = 64, 64
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dem = 0.2 * xx + 0.5 * yy
    obstacle_mask = np.zeros((h, w), dtype=np.float32)
    obstacle_mask[25:34, 28:36] = 1.0
    road_segments = np.array([[0.0, 8.0, 63.0, 8.0], [12.0, 0.0, 12.0, 63.0]], dtype=np.float32)
    road_voronoi = np.zeros((h, w), dtype=np.int64)
    road_voronoi[:, :32] = 1
    demand_points = np.array([[8.0, 8.0], [48.0, 52.0], [30.0, 18.0]], dtype=np.float32)
    demand_weights = np.array([1.0, 2.0, 1.5], dtype=np.float32)
    return MultiStartAdamProblem(
        dem=dem,
        obstacle_mask=obstacle_mask,
        road_segments=road_segments,
        dem_tensor=torch.as_tensor(dem, dtype=torch.float32, device=device)[None, None, :, :],
        obstacle_tensor=torch.as_tensor(obstacle_mask, dtype=torch.float32, device=device)[None, None, :, :],
        road_segments_tensor=torch.as_tensor(road_segments, dtype=torch.float32, device=device),
        road_voronoi_tensor=torch.as_tensor(road_voronoi, dtype=torch.long, device=device),
        demand_points=demand_points,
        demand_weights=demand_weights,
        demand_points_tensor=torch.as_tensor(demand_points, dtype=torch.float32, device=device),
        demand_weights_tensor=torch.as_tensor(demand_weights, dtype=torch.float32, device=device),
        device=device,
    )


def test_initialize_raw_pose_starts_is_deterministic(cuda_device: torch.device) -> None:
    raw_a = initialize_raw_pose_starts(16, seed=7, init_eps=0.05, device=cuda_device)
    raw_b = initialize_raw_pose_starts(16, seed=7, init_eps=0.05, device=cuda_device)
    torch.testing.assert_close(raw_a, raw_b)
    u = torch.sigmoid(raw_a)
    assert torch.all(u >= 0.05)
    assert torch.all(u <= 0.95)


def test_multistart_adam_smoke_outputs_finite_candidates(cuda_device: torch.device) -> None:
    problem = _synthetic_problem(cuda_device)
    modeling = ModelingConfig(rect_w_m=8.0, rect_h_m=6.0, soft_mask_sharpness=8.0, device="cuda")
    common = AlgorithmCommonConfig(
        normalization_samples=8,
        normalization_scale_percentile=95.0,
        normalization_seed=11,
        weight_grid_step=1.0,
        obstacle_penalty_scale=2.0,
    )
    config = MultiStartAdamConfig(
        seed=5,
        starts_per_weight=2,
        max_steps=1,
        learning_rate=0.01,
        init_eps=0.05,
    )

    result = run_multistart_adam_search(problem, modeling, common, config)

    assert len(result.runs) == 3
    assert len(result.solutions) == 6
    assert result.normalization["normalization_samples"] == 8
    for row in result.solutions:
        assert row["preference_id"] in (0, 1, 2)
        assert row["start_id"] in (0, 1)
        assert row["best_step"] in (0, 1)
        for field in ("raw_x", "raw_y", "raw_theta", "x", "y", "theta", "scalar"):
            assert np.isfinite(float(row[field]))
