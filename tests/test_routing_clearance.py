import numpy as np
import pytest
import torch
from shapely.geometry import Polygon

from modeling.routing.clearance import center_distance, zone_mask
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.tensor_queries import TensorRouteGeometry
from modeling.routing.tensor_geometry import tower_flags
from test_pilot_tensor_runtime import native_config
from test_routing_context import make_problem


def test_center_distance_matches_nearest_pixel_centers_and_empty_masks_are_infinite():
    rng = np.random.default_rng(3)
    mask = rng.random((12, 9)) < 0.2
    mask[4, 5] = True
    distance = center_distance(mask)
    rows, cols = np.nonzero(mask)
    for row, col in np.ndindex(mask.shape):
        expected = np.hypot(cols - col, rows - row).min()
        assert abs(float(distance[row, col]) - expected) < 1e-4
    assert np.isposinf(center_distance(np.zeros((4, 5), dtype=bool))).all()


def test_zone_mask_marks_only_cells_touched_by_the_polygon():
    mask = zone_mask((Polygon([(1.2, 1.2), (2.8, 1.2), (2.8, 2.4), (1.2, 2.4)]),), (6, 8))
    assert mask[1:3, 1:3].all()
    assert not mask[0].any() and not mask[:, 4:].any()


def _legacy_flags(dem, blocked, points, radius):
    return tower_flags(dem, blocked, points, radius, 1 << 20)


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_clearance_tower_flags_match_the_cell_scan(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA is not available")
    dem = np.arange(40 * 36, dtype=np.float32).reshape(40, 36)
    dem[8:11, 12:15] = np.nan
    blocked = np.zeros(dem.shape, dtype=bool)
    blocked[5:9, 4:10] = True
    blocked[20, 22] = True
    dem_t = torch.tensor(dem, device=device)
    blocked_t = torch.tensor(blocked, device=device)
    distances = (
        torch.tensor(center_distance(blocked), device=device),
        torch.tensor(center_distance(~np.isfinite(dem)), device=device),
    )
    rng = np.random.default_rng(17)
    samples = [rng.uniform([-2, -2], [38, 42], (300, 2))]
    samples.append(np.column_stack([rng.uniform(0, 36, 80), rng.uniform(0, 40, 80)]))
    samples.append(np.array([[10.0, 10.0], [4.2, 5.1], [22.0, 20.0], [0.0, 0.0], [35.9, 39.9]]))
    for row, col in zip(*np.nonzero(blocked | ~np.isfinite(dem))):
        for radius in (1.0, 3.5, 10.0):
            angle = rng.uniform(0, 2 * np.pi)
            samples.append([[col + 0.5 + (radius + 0.2) * np.cos(angle),
                             row + 0.5 + (radius + 0.2) * np.sin(angle)]])
    points = torch.tensor(np.vstack(samples), device=device, dtype=torch.float64)
    for radius in (1.0, 3.5, 10.0):
        legacy = _legacy_flags(dem_t, blocked_t, points, radius)
        accelerated = tower_flags(dem_t, blocked_t, points, radius, 1 << 20, *distances)
        names = ("outside", "hit", "missing")
        for name, old, new in zip(names, legacy, accelerated):
            mismatch = (old != new).nonzero().flatten()
            assert len(mismatch) == 0, (name, radius, int(mismatch[0]), bool(old[mismatch[0]]), bool(new[mismatch[0]]))
        # near is the recheck bit. It may stay false when another cell already decides the disk.
        assert not bool((accelerated[3] & ~legacy[3]).any())


def test_accelerated_queries_match_the_reference_with_forbidden_zones():
    dem = np.arange(32 * 32, dtype=np.float32).reshape(32, 32)
    dem[14:17, 18:21] = np.nan
    problem = make_problem(
        dem=dem,
        no_tower_zones=(((6, 6), (12, 6), (12, 11), (6, 11)),),
        no_cross_zones=(((20, 8), (28, 8), (28, 16), (20, 16)),),
    )
    evaluator = TensorRouteEvaluator(problem, native_config())
    try:
        geometry = TensorRouteGeometry(evaluator)
        rng = np.random.default_rng(23)
        points = torch.tensor(rng.uniform([0, 0], [31, 31], (180, 2)), dtype=torch.float64)
        towers = geometry.towers(points).numpy()
        assert 0 < geometry.cpu_rechecks < len(points)
        expected = np.array([geometry.reference.tower_allowed(point) for point in points.numpy()])
        np.testing.assert_array_equal(towers, expected)
        starts = torch.tensor(rng.uniform([1, 1], [30, 30], (120, 2)), dtype=torch.float64)
        ends = starts + torch.tensor(rng.uniform(-12, 12, (120, 2)), dtype=torch.float64)
        ends = torch.cat([ends, torch.tensor([[22., 4.], [30., 20.], [4., 4.]], dtype=torch.float64)])
        starts = torch.cat([starts, torch.tensor([[22., 20.], [18., 12.], [8., 30.]], dtype=torch.float64)])
        geometry.cpu_rechecks = 0
        spans = geometry.spans(starts, ends).numpy()
        assert 0 < geometry.cpu_rechecks < len(starts)
        reference = np.array([
            geometry.reference.span_allowed(start, end)
            for start, end in zip(starts.numpy(), ends.numpy())
        ])
        np.testing.assert_array_equal(spans, reference)
    finally:
        evaluator.close()
