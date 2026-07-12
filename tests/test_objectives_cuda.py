from __future__ import annotations

import torch

from modeling.demand_model import compute_demand_distance_loss
from modeling.dem_model import compute_dem_soft_loss
from modeling.masks import compute_soft_footprint
from modeling.obstacle_model import compute_obstacle_soft_loss
from modeling.pose import decode_raw_pose
from modeling.road_model import compute_road_distance_loss


def test_soft_objectives_are_cuda_and_backpropagate(cuda_device: torch.device) -> None:
    h, w = 64, 64
    y = torch.arange(h, dtype=torch.float32, device=cuda_device)[:, None]
    x = torch.arange(w, dtype=torch.float32, device=cuda_device)[None, :]
    dem = (0.2 * x + 0.5 * y)[None, None, :, :]
    obstacle = torch.zeros((1, 1, h, w), dtype=torch.float32, device=cuda_device)
    obstacle[:, :, 25:34, 28:36] = 1.0

    road_segments = torch.tensor(
        [[0.0, 8.0, 63.0, 8.0], [12.0, 0.0, 12.0, 63.0]],
        dtype=torch.float32,
        device=cuda_device,
    )
    road_voronoi = torch.zeros((h, w), dtype=torch.long, device=cuda_device)
    road_voronoi[:, :32] = 1

    demand_points = torch.tensor(
        [[8.0, 8.0], [48.0, 52.0], [30.0, 18.0]],
        dtype=torch.float32,
        device=cuda_device,
    )
    demand_weights = torch.tensor([1.0, 2.0, 1.5], dtype=torch.float32, device=cuda_device)

    raw_pose = torch.tensor(
        [[0.0, 0.0, 0.0], [0.4, -0.6, 0.2]],
        dtype=torch.float32,
        device=cuda_device,
        requires_grad=True,
    )
    pose = decode_raw_pose(raw_pose, (h, w), rect_w_m=8.0, rect_h_m=6.0)
    footprint = compute_soft_footprint(pose, 8.0, 6.0, (h, w), sharpness=8.0)

    losses = {
        "dem": compute_dem_soft_loss(dem, footprint["grid"], footprint["weights"]),
        "obstacle": compute_obstacle_soft_loss(obstacle, footprint["grid"], footprint["weights"]),
        "road": compute_road_distance_loss(road_segments, road_voronoi, pose),
        "demand": compute_demand_distance_loss(demand_points, demand_weights, pose),
    }

    total = torch.zeros((), dtype=torch.float32, device=cuda_device)
    for loss in losses.values():
        assert loss.shape == (2,)
        assert loss.is_cuda
        assert torch.isfinite(loss).all()
        total = total + loss.sum()

    total.backward()
    assert raw_pose.grad is not None
    assert raw_pose.grad.is_cuda
    assert torch.isfinite(raw_pose.grad).all()

