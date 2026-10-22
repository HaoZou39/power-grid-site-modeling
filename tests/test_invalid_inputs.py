from __future__ import annotations

import pytest
import torch

from modeling.demand_model import compute_demand_distance_loss
from modeling.masks import compute_soft_footprint
from modeling.pose import decode_raw_pose
from modeling.road_model import compute_road_distance_loss


def test_modeling_rejects_mixed_devices() -> None:
    from modeling.dem_model import compute_dem_soft_loss

    with pytest.raises(ValueError, match="same device"):
        compute_dem_soft_loss(torch.zeros((1, 1, 8, 8)), torch.empty((1, 2, 2, 2), device="meta"), torch.ones((1, 2, 2)))


def test_soft_footprint_rejects_nan(model_device: torch.device) -> None:
    pose = torch.tensor([[10.0, float("nan"), 0.0]], dtype=torch.float32, device=model_device)
    with pytest.raises(ValueError, match="NaN|Inf"):
        compute_soft_footprint(pose, 4.0, 4.0, (32, 32))


def test_demand_weights_must_be_valid(model_device: torch.device) -> None:
    demand_points = torch.tensor([[0.0, 0.0], [1.0, 1.0]], dtype=torch.float32, device=model_device)
    pose = torch.tensor([[2.0, 2.0, 0.0]], dtype=torch.float32, device=model_device)
    with pytest.raises(ValueError, match="non-negative"):
        compute_demand_distance_loss(
            demand_points,
            torch.tensor([1.0, -1.0], dtype=torch.float32, device=model_device),
            pose,
        )
    with pytest.raises(ValueError, match="positive sum"):
        compute_demand_distance_loss(
            demand_points,
            torch.tensor([0.0, 0.0], dtype=torch.float32, device=model_device),
            pose,
        )


def test_road_voronoi_invalid_segment_id_raises(model_device: torch.device) -> None:
    road_segments = torch.tensor([[0.0, 0.0, 4.0, 0.0]], dtype=torch.float32, device=model_device)
    road_voronoi = torch.full((8, 8), 2, dtype=torch.long, device=model_device)
    pose = torch.tensor([[2.5, 2.5, 0.0]], dtype=torch.float32, device=model_device)
    with pytest.raises(ValueError, match="invalid segment"):
        compute_road_distance_loss(road_segments, road_voronoi, pose)

