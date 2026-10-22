from __future__ import annotations

import math

import numpy as np
import pytest
import torch

from modeling.masks import compute_hard_footprint_indices, compute_soft_footprint
from modeling.pose import compute_safe_margin, decode_raw_pose


def test_decode_raw_pose_bounds_and_soft_hard_masks(model_device: torch.device) -> None:
    raw_pose = torch.tensor(
        [[0.0, 0.0, 0.0], [0.8, -0.5, 0.3]],
        dtype=torch.float32,
        device=model_device,
        requires_grad=True,
    )
    matrix_shape = (64, 80)
    rect_w_m = 8.0
    rect_h_m = 6.0
    pose = decode_raw_pose(raw_pose, matrix_shape, rect_w_m, rect_h_m)

    assert pose.shape == (2, 3)
    assert pose.device == model_device
    assert torch.isfinite(pose).all()

    safe_margin = compute_safe_margin(rect_w_m, rect_h_m)
    assert torch.all(pose[:, 0] >= safe_margin)
    assert torch.all(pose[:, 0] <= matrix_shape[1] - 1 - safe_margin)
    assert torch.all(pose[:, 1] >= safe_margin)
    assert torch.all(pose[:, 1] <= matrix_shape[0] - 1 - safe_margin)
    assert torch.all(pose[:, 2] >= -math.pi)
    assert torch.all(pose[:, 2] <= math.pi)

    footprint = compute_soft_footprint(pose, rect_w_m, rect_h_m, matrix_shape, sharpness=8.0)
    assert footprint["grid"].shape[0] == 2
    assert footprint["grid"].shape[-1] == 2
    assert footprint["weights"].shape == footprint["grid"].shape[:3]
    assert footprint["grid"].device == model_device
    assert footprint["weights"].device == model_device
    assert torch.isfinite(footprint["grid"]).all()
    assert torch.isfinite(footprint["weights"]).all()

    hard_indices = compute_hard_footprint_indices(pose.detach(), rect_w_m, rect_h_m, matrix_shape)
    assert len(hard_indices) == 2
    for indices in hard_indices:
        assert indices.ndim == 2
        assert indices.shape[1] == 2
        assert indices.shape[0] > 0
        assert np.issubdtype(indices.dtype, np.integer)
        assert indices[:, 0].min() >= 0
        assert indices[:, 0].max() < matrix_shape[0]
        assert indices[:, 1].min() >= 0
        assert indices[:, 1].max() < matrix_shape[1]


def test_decode_raw_pose_respects_optional_partition_bounds(model_device: torch.device) -> None:
    raw_pose = torch.zeros((1, 3), dtype=torch.float32, device=model_device)
    pose = decode_raw_pose(raw_pose, (100, 100), 10.0, 10.0, (20.0, 40.0, 30.0, 50.0))
    assert pose[0, 0].item() == pytest.approx(30.0)
    assert pose[0, 1].item() == pytest.approx(40.0)
    assert pose[0, 2].item() == pytest.approx(0.0)

    with pytest.raises(ValueError, match="pose_bounds"):
        decode_raw_pose(raw_pose, (100, 100), 10.0, 10.0, (1.0, 40.0, 30.0, 50.0))
