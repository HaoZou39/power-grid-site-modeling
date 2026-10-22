"""Tensor hard footprints must agree with the report geometry, including edges."""

import math

import numpy as np
import pytest
import torch

from modeling.masks import compute_hard_footprints
from modeling.site_model import ObstacleCountConstraint


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("size", [(4, 4), (77, 51.5)])
def test_tensor_violation_matches_scalar_footprints(cuda_device, dtype, size):
    rng = np.random.default_rng(7)
    mask = (rng.random((180, 200)) < 0.2).astype(np.float32)
    w, h = size
    theta = 0.3
    half_x = math.cos(theta) * w / 2 + math.sin(theta) * h / 2
    poses = np.column_stack((rng.uniform(40, 160, 24), rng.uniform(40, 140, 24), rng.uniform(-math.pi, math.pi, 24)))
    poses = np.concatenate((poses, [[half_x, 90, theta], [half_x - 0.1, 90, theta], [200 - half_x, 90, theta], [200 - half_x + 0.1, 90, theta], [0.5, 90, 0], [1.9, 90, 0]])).astype(dtype)
    footprints = compute_hard_footprints(poses, w, h, mask.shape)
    expected = [np.count_nonzero(mask[fp.inside[:, 0], fp.inside[:, 1]]) + fp.outside_count for fp in footprints]
    actual = ObstacleCountConstraint().violation(torch.tensor(mask, device=cuda_device), torch.tensor(poses, device=cuda_device), w, h)
    np.testing.assert_array_equal(actual.cpu(), expected)


def test_tensor_footprint_rejects_completely_outside_pose(cuda_device):
    with pytest.raises(ValueError, match="no pixels"):
        ObstacleCountConstraint().violation(torch.zeros((10, 10), device=cuda_device), torch.tensor([[-100, -100, 0]], device=cuda_device), 4, 4)
