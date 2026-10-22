"""Exact tensor lookups across roads, blocked cells, origins and center offsets."""

import numpy as np
import pytest
import torch

from modeling.haul_field import build_haul_field, query_exact
from modeling.tensor_evaluator import TensorHaulLookup


@pytest.mark.parametrize("diagonal", [False, True])
@pytest.mark.parametrize("origin", [None, (1.1, 2.3)])
def test_tensor_haul_matches_all_cells_and_continuous_queries(cuda_device, diagonal, origin):
    rows, cols = np.indices((12, 16))
    dem = np.sin(cols) + rows * 0.3
    buildable = np.ones_like(dem, dtype=bool)
    buildable[:, 7:9] = False
    buildable[5:7, 3:5] = False
    segments = np.array([[1.5, 0.1, 1.5, 11.9], [14.5, 0.1, 14.5, 11.9]])
    field = build_haul_field(dem, buildable, segments, origin, diagonal=diagonal, access_elevation_weight=1.7)
    centers = np.column_stack((cols.ravel() + 0.5, rows.ravel() + 0.5))
    sites = np.concatenate((centers, centers + [0.049, 0], centers + [0.051, 0],
                            centers + [0.25, -0.2], [[-1, 2], [16, 2]]))
    expected, flags = query_exact(field, sites)
    actual, blocked = TensorHaulLookup(field, cuda_device)(torch.tensor(sites, device=cuda_device))
    np.testing.assert_allclose(actual.cpu(), expected, rtol=1e-14, atol=1e-12)
    np.testing.assert_array_equal(blocked.cpu(), flags)
