from __future__ import annotations

import pytest
import torch

from modeling.demand_model import compute_demand_distance_loss
from modeling.masks import compute_soft_footprint
from modeling.pose import decode_raw_pose
from modeling.road_model import compute_road_distance_loss


def test_modeling_rejects_non_cuda_tensors() -> None:
    with pytest.raises(ValueError, match="CUDA"):
        decode_raw_pose(torch.zeros((1, 3)), (32, 32), 4.0, 4.0)


def test_soft_footprint_rejects_nan(cuda_device: torch.device) -> None:
    pose = torch.tensor([[10.0, float("nan"), 0.0]], dtype=torch.float32, device=cuda_device)
    with pytest.raises(ValueError, match="NaN|Inf"):
        compute_soft_footprint(pose, 4.0, 4.0, (32, 32))


def test_demand_weights_must_be_valid(cuda_device: torch.device) -> None:
    demand_points = torch.tensor([[0.0, 0.0], [1.0, 1.0]], dtype=torch.float32, device=cuda_device)
    pose = torch.tensor([[2.0, 2.0, 0.0]], dtype=torch.float32, device=cuda_device)
    with pytest.raises(ValueError, match="non-negative"):
        compute_demand_distance_loss(
            demand_points,
            torch.tensor([1.0, -1.0], dtype=torch.float32, device=cuda_device),
            pose,
        )
    with pytest.raises(ValueError, match="positive sum"):
        compute_demand_distance_loss(
            demand_points,
            torch.tensor([0.0, 0.0], dtype=torch.float32, device=cuda_device),
            pose,
        )


def test_road_voronoi_invalid_segment_id_raises(cuda_device: torch.device) -> None:
    road_segments = torch.tensor([[0.0, 0.0, 4.0, 0.0]], dtype=torch.float32, device=cuda_device)
    road_voronoi = torch.full((8, 8), 2, dtype=torch.long, device=cuda_device)
    pose = torch.tensor([[2.5, 2.5, 0.0]], dtype=torch.float32, device=cuda_device)
    with pytest.raises(ValueError, match="invalid segment"):
        compute_road_distance_loss(road_segments, road_voronoi, pose)

