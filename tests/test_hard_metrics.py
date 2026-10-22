from __future__ import annotations

import math

import numpy as np
import torch

import pytest

from modeling.dem_model import compute_dem_hard_loss
from modeling.masks import compute_hard_footprints
from modeling.obstacle_model import compute_obstacle_hard_loss
from modeling.site_model import ObstacleCountConstraint


def test_hard_metrics_match_manual_values(cuda_device: torch.device) -> None:
    dem = np.array(
        [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
        ],
        dtype=np.float32,
    )
    obstacle = np.array(
        [
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    hard_indices = [np.array([[0, 0], [0, 1], [1, 0], [1, 1]], dtype=np.int64)]

    dem_metrics = compute_dem_hard_loss(dem, hard_indices, device="cuda")
    obstacle_metrics = compute_obstacle_hard_loss(obstacle, hard_indices, device="cuda")

    values = np.array([1.0, 2.0, 4.0, 5.0], dtype=np.float32)
    assert dem_metrics["dem_hard_var"].is_cuda
    assert dem_metrics["dem_hard_range"].is_cuda
    assert obstacle_metrics["obstacle_hard_count"].is_cuda
    assert obstacle_metrics["obstacle_hard_ratio"].is_cuda
    torch.testing.assert_close(dem_metrics["dem_hard_var"], torch.tensor([float(np.var(values))], device=cuda_device))
    torch.testing.assert_close(dem_metrics["dem_hard_range"], torch.tensor([4.0], device=cuda_device))
    torch.testing.assert_close(obstacle_metrics["obstacle_hard_count"], torch.tensor([3.0], device=cuda_device))
    torch.testing.assert_close(obstacle_metrics["obstacle_hard_ratio"], torch.tensor([0.75], device=cuda_device))
    assert bool((obstacle_metrics["obstacle_hard_count"] == 0).item()) is False


def test_overhanging_rectangle_is_infeasible_without_counting_as_obstacle() -> None:
    dem = np.zeros((20, 20), dtype=np.float32)
    obstacle = np.zeros_like(dem)
    pose = torch.tensor([[0.5, 10.0, 0.0]], dtype=torch.float32)
    metrics = ObstacleCountConstraint().metrics(dem, obstacle, pose, 4.0, 4.0, device="cpu")
    assert float(metrics["obstacle_hard_count"][0]) == 0.0
    assert float(metrics["constraint_violation"][0]) > 0.0
    assert bool(metrics["is_feasible"][0].item()) is False
    footprints = compute_hard_footprints(pose, 4.0, 4.0, dem.shape)
    assert footprints[0].outside_count == int(metrics["constraint_violation"][0])
    slight = torch.tensor([[1.9, 10.0, 0.0]], dtype=torch.float32)
    slight_metrics = ObstacleCountConstraint().metrics(dem, obstacle, slight, 4.0, 4.0, device="cpu")
    assert float(slight_metrics["obstacle_hard_count"][0]) == 0.0
    assert float(slight_metrics["constraint_violation"][0]) > 0.0
    assert bool(slight_metrics["is_feasible"][0].item()) is False
    inside = torch.tensor([[10.0, 10.0, 0.3]], dtype=torch.float32)
    inside_metrics = ObstacleCountConstraint().metrics(dem, obstacle, inside, 4.0, 4.0, device="cpu")
    assert float(inside_metrics["constraint_violation"][0]) == 0.0
    assert bool(inside_metrics["is_feasible"][0].item()) is True


def test_rectangle_entirely_outside_the_grid_is_rejected() -> None:
    pose = torch.tensor([[-100.0, -100.0, 0.0]], dtype=torch.float32)
    with pytest.raises(ValueError, match="no pixels"):
        compute_hard_footprints(pose, 4.0, 4.0, (20, 20))


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("side", ["left", "right", "top", "bottom"])
def test_rotated_rectangle_touching_boundary_survives_pose_rounding(dtype, side) -> None:
    shape = (100, 100)
    width, height, theta = 77.0, 51.5, 0.3
    extent_x = (width * math.cos(theta) + height * math.sin(theta)) / 2
    extent_y = (width * math.sin(theta) + height * math.cos(theta)) / 2
    centers = {
        "left": (extent_x, 50.0),
        "right": (shape[1] - extent_x, 50.0),
        "top": (50.0, extent_y),
        "bottom": (50.0, shape[0] - extent_y),
    }
    x, y = centers[side]
    dem = np.zeros(shape, dtype=np.float32)
    pose = np.array([[x, y, theta]], dtype=dtype)
    metrics = ObstacleCountConstraint().metrics(dem, np.zeros_like(dem), pose, width, height, device="cpu")
    assert metrics["constraint_violation"].tolist() == [0.0]
    assert metrics["is_feasible"].tolist() == [True]

    dx, dy = {"left": (-0.1, 0), "right": (0.1, 0), "top": (0, -0.1), "bottom": (0, 0.1)}[side]
    overhang = np.array([[x + dx, y + dy, theta]], dtype=dtype)
    outside = ObstacleCountConstraint().metrics(dem, np.zeros_like(dem), overhang, width, height, device="cpu")
    assert outside["constraint_violation"][0] > 0
    assert outside["is_feasible"].tolist() == [False]

