"""Bilinear sampling of a cell-center haul field. CPU only, no search."""

import numpy as np
import torch

from modeling.haul_field import build_haul_field, query_exact
from algorithms.nsga2.guided_search import _positive_scale, _sentinel_mask
from modeling.haul_model import UNREACHABLE_M, sample_center_field, torch_field


def _pair_field() -> torch.Tensor:
    field = torch.zeros((3, 3), dtype=torch.float32)
    field[1, 1] = 2.0
    field[1, 2] = 8.0
    return field


def test_cell_center_uses_that_cell_only() -> None:
    field = _pair_field()
    value = sample_center_field(field, torch.tensor([1.5]), torch.tensor([1.5]))
    assert float(value[0]) == 2.0


def test_midpoint_is_the_two_cell_average() -> None:
    field = _pair_field()
    value = sample_center_field(field, torch.tensor([2.0]), torch.tensor([1.5]))
    assert float(value[0]) == 5.0


def test_autograd_matches_the_central_difference() -> None:
    field = _pair_field()
    x = torch.tensor([2.0], dtype=torch.float32, requires_grad=True)
    y = torch.tensor([1.5], dtype=torch.float32, requires_grad=True)
    sample_center_field(field, x, y).sum().backward()
    assert x.grad is not None and y.grad is not None
    step = 1e-3
    plus = sample_center_field(field, torch.tensor([2.0 + step]), y.detach())
    minus = sample_center_field(field, torch.tensor([2.0 - step]), y.detach())
    finite = float((plus - minus) / (2 * step))
    assert abs(float(x.grad[0]) - finite) < 1e-3
    assert abs(float(x.grad[0])) > 0.0


def test_blocked_exact_query_stays_zero() -> None:
    dem = np.zeros((6, 6), dtype=np.float64)
    buildable = np.ones((6, 6), dtype=np.uint8)
    buildable[2, :] = 0
    segments = np.array([[0.0, 0.5, 5.9, 0.5]], dtype=np.float64)
    field = build_haul_field(dem, buildable, segments, (2.5, 0.5))
    values, blocked = query_exact(field, np.array([[2.5, 3.5]], dtype=np.float64))
    sampled = sample_center_field(
        torch_field(field.offroad_m, field.reachable),
        torch.tensor([2.5]),
        torch.tensor([3.5]),
    )
    assert blocked[0] == 1.0
    assert np.all(values[0] == 0.0)
    sampled_field = torch_field(field.offroad_m, field.reachable)
    assert float(sampled[0]) == UNREACHABLE_M
    mask = _sentinel_mask(sampled_field)
    assert bool(mask[3, 2])
    scale = _positive_scale(sampled_field.numpy(), ignore=mask)
    assert scale < UNREACHABLE_M
