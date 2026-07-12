from __future__ import annotations

import numpy as np
import torch

from modeling.dem_model import compute_dem_hard_loss
from modeling.obstacle_model import compute_obstacle_hard_loss


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

