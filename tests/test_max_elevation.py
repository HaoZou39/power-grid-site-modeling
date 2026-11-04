"""Highest ground elevation is a building-only hard limit."""

from time import perf_counter

import numpy as np
import pytest
import torch

from experiments.constraint_mask import elevation_forbidden, parse_max_elevation
from experiments.problem_context import context_from_arrays, with_constraint_masks
from modeling.evaluator import compute_hard_constraints
from modeling.haul_field import build_haul_field, query_exact
from modeling.site_model import default_site_model


def _context(dem: np.ndarray):
    segments = np.array([[1.0, 1.0, dem.shape[1] - 2.0, 1.0]], dtype=np.float64)
    arrays = {
        "dem": np.asarray(dem, dtype=np.float32),
        "obstacle_mask": np.zeros(dem.shape, dtype=np.float32),
        "road_segments": segments,
        "road_voronoi": np.zeros(dem.shape, dtype=np.int64),
        "road_segment_kinds": np.array([0], dtype=np.int8),
        "demand_points": np.zeros((0, 2), dtype=np.float32),
        "landuse": np.zeros(dem.shape, dtype=np.int16),
    }
    return context_from_arrays(arrays, torch.device("cpu"), 0.0, 0.0, 0.0)


def _limited(context, limit):
    clear = np.zeros(context.dem.shape, dtype=np.float32)
    return with_constraint_masks(context, clear, clear, access_mask=clear, max_elevation_m=limit)


def _feasible(problem, x: float, y: float, theta: float, width: float, height: float) -> bool:
    pose = torch.tensor([[x, y, theta]], dtype=torch.float32)
    hard = compute_hard_constraints(problem.dem, problem.building_obstacle_mask, pose, width, height, "cpu")
    return bool(hard["is_feasible"][0].item())


def test_missing_limit_adds_no_cells() -> None:
    dem = np.full((12, 12), 350.0, dtype=np.float32)
    bare = _limited(_context(dem), None)
    assert bare.building_obstacle_mask.sum() == _context(dem).building_obstacle_mask.sum()


def test_cells_above_the_limit_block_only_the_building() -> None:
    dem = np.full((16, 16), 100.0, dtype=np.float32)
    dem[4, :] = 250.0
    open_ground = _limited(_context(dem), None)
    limited = _limited(open_ground, 200.0)
    assert limited.building_obstacle_mask[4].all()
    assert not limited.building_obstacle_mask[8].any()
    assert np.array_equal(limited.obstacle_mask, open_ground.obstacle_mask)
    assert limited.building_soft_tensor[0, 0, 4, 8].item() == 1


def test_equal_to_the_limit_stays_feasible_and_a_higher_cell_does_not() -> None:
    dem = np.full((16, 16), 180.0, dtype=np.float32)
    dem[8, 8] = 200.0
    problem = _limited(_context(dem), 200.0)
    assert _feasible(problem, 8.5, 8.5, 0.0, 2.0, 2.0)
    dem[8, 8] = 200.1
    exceeded = _limited(_context(dem), 200.0)
    assert not _feasible(exceeded, 8.5, 8.5, 0.0, 2.0, 2.0)


def test_part_of_the_rectangle_above_the_limit_is_infeasible() -> None:
    dem = np.full((16, 16), 180.0, dtype=np.float32)
    dem[8, 10] = 230.0
    problem = _limited(_context(dem), 200.0)
    assert not _feasible(problem, 8.5, 8.5, 0.0, 6.0, 2.0)


def test_rotation_changes_which_cells_count() -> None:
    dem = np.full((20, 20), 100.0, dtype=np.float32)
    dem[10, 16] = 260.0
    problem = _limited(_context(dem), 200.0)
    flat = _feasible(problem, 10.5, 10.5, 0.0, 2.0, 12.0)
    turned = _feasible(problem, 10.5, 10.5, np.pi / 2, 2.0, 12.0)
    assert flat != turned


def test_non_finite_elevation_is_not_buildable() -> None:
    dem = np.full((8, 8), 10.0, dtype=np.float32)
    dem[3, 3] = np.nan
    forbidden = elevation_forbidden(dem, 200.0)
    assert forbidden[3, 3] == 1
    assert forbidden[1, 1] == 0


def test_cpu_and_tensor_violation_agree() -> None:
    dem = np.full((16, 16), 150.0, dtype=np.float32)
    dem[8, 8] = 240.0
    problem = _limited(_context(dem), 200.0)
    pose = torch.tensor([[8.5, 8.5, 0.0], [4.5, 4.5, 0.2]], dtype=torch.float32)
    model = default_site_model()
    cpu = model.hard_metrics(problem.dem, problem.building_obstacle_mask, pose, 2.0, 2.0, "cpu")
    tensor = model.constraint.violation(torch.as_tensor(problem.building_obstacle_mask > 0), pose, 2.0, 2.0)
    assert torch.equal(cpu["constraint_violation"] > 0, tensor > 0)
    assert bool(cpu["is_feasible"][0].item()) is False
    assert bool(cpu["is_feasible"][1].item()) is True


def test_high_ground_does_not_block_the_access_road() -> None:
    dem = np.full((12, 12), 50.0, dtype=np.float32)
    dem[1, :] = 400.0
    problem = _limited(_context(dem), 200.0)
    assert problem.obstacle_mask[1].sum() == 0
    field = build_haul_field(problem.dem, problem.obstacle_mask == 0, problem.road_segments, None, diagonal=True)
    _values, blocked = query_exact(field, np.array([[6.5, 4.5]], dtype=np.float64))
    assert blocked[0] == 0


def test_changing_the_limit_does_not_reuse_the_previous_mask() -> None:
    dem = np.full((10, 10), 180.0, dtype=np.float32)
    base = _context(dem)
    plain = _limited(base, None)
    loose = _limited(base, 200.0)
    tight = _limited(base, 150.0)
    off = _limited(tight, None)
    assert loose.building_obstacle_mask.sum() == plain.building_obstacle_mask.sum()
    assert tight.building_obstacle_mask.sum() == dem.size
    assert off.building_obstacle_mask.sum() == plain.building_obstacle_mask.sum()
    assert np.array_equal(tight.obstacle_mask, loose.obstacle_mask)


def test_parse_accepts_zero_and_negative_and_rejects_junk() -> None:
    assert parse_max_elevation(None) is None
    assert parse_max_elevation(0) == 0
    assert parse_max_elevation(-3.5) == -3.5
    for value in (True, False, "200", "nan", float("nan"), float("inf"), object()):
        with pytest.raises(ValueError):
            parse_max_elevation(value)


def test_elevation_mask_stays_cheap_on_a_small_grid() -> None:
    dem = np.full((400, 400), 12.0, dtype=np.float32)
    started = perf_counter()
    mask = elevation_forbidden(dem, 20.0)
    elapsed = perf_counter() - started
    assert mask.shape == dem.shape and mask.sum() == 0
    assert elapsed < 1.0
