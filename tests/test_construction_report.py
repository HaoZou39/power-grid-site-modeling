"""Construction reports stay outside the three search objectives."""

import math

import numpy as np

from algorithms.common.scalarization import OBJECTIVE_NAMES
from modeling.access_path import access_profile, access_warning
from modeling.evaluator import compute_hard_constraints
from modeling.logistics_cost import logistics_route
from modeling.slope import footprint_max_slope_deg
from experiments.site_report import build_precise_site_report, build_site_report


def test_uniform_slope_is_steeper_than_flat_ground() -> None:
    flat = np.full((8, 8), 3.0, dtype=np.float32)
    ramp = np.zeros((8, 8), dtype=np.float32)
    ramp[:] = np.arange(8, dtype=np.float32) * 0.5
    pose = (4.5, 4.5, 0.0)
    assert footprint_max_slope_deg(ramp, pose, 4.0, 4.0) > footprint_max_slope_deg(flat, pose, 4.0, 4.0)
    assert OBJECTIVE_NAMES == ("dem_soft", "road_distance", "demand_distance")


def test_nearby_origin_has_a_shorter_road_length() -> None:
    segments = np.array([[0.0, 0.0, 10.0, 0.0]], dtype=np.float64)
    near = logistics_route((0.0, 1.0), (1.0, 1.0), segments)
    far = logistics_route((0.0, 1.0), (10.0, 1.0), segments)
    assert near["road_m"] < far["road_m"]
    assert math.isclose(far["road_m"], 10.0)
    assert math.isclose(far["offroad_m"], 2.0)
    joined = np.array([[0.0, 0.0, 5.0, 0.0], [5.0, 0.0, 10.0, 0.0]], dtype=np.float64)
    route = logistics_route((0.0, 1.0), (10.0, 1.0), joined)
    assert route["points"][0] == (0.0, 1.0)
    assert route["points"][-1] == (10.0, 1.0)
    assert any(abs(point[1]) < 0.01 for point in route["points"])


def test_steep_approach_warns_without_changing_feasibility() -> None:
    dem = np.zeros((1, 7), dtype=np.float32)
    dem[0, 3] = 5.0
    segments = np.array([[6.5, 0.5, 8.5, 0.5]], dtype=np.float64)
    steep = access_profile(dem, (0.5, 0.5), segments)
    flat = access_profile(np.zeros_like(dem), (0.5, 0.5), segments)
    assert steep["max_slope_deg"] > flat["max_slope_deg"]
    assert access_warning(steep["max_slope_deg"], 10.0) is True
    feasible = compute_hard_constraints(
        dem,
        np.zeros_like(dem),
        np.array([[0.5, 0.5, 0.0]]),
        0.4,
        0.4,
        device="cpu",
    )
    assert bool(feasible["is_feasible"][0].item()) is True


def test_unreachable_construction_path_does_not_hide_infeasibility(tmp_path) -> None:
    _write_scene(tmp_path)
    report = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        obstacle_mask=np.ones((12, 12), dtype=np.float32),
        allow_unreachable=True,
    )
    assert report["offroad_haul_m"] is None
    assert "access_error" in report


def test_precise_report_evaluates_one_pose_with_search_masks(tmp_path, cuda_device) -> None:
    _write_scene(tmp_path)
    form = {
        "field_policy": "allowed",
        "mountain_policy": "allowed",
        "field_cost": 0.5,
        "exclusion_zones": [],
        "feasible_zones": [],
    }
    open_report = build_precise_site_report(
        tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, form, cuda_device, 8.0
    )
    assert open_report["is_feasible"] is True
    for name in ("dem_soft", "obstacle_soft", "road_distance", "demand_distance"):
        assert math.isfinite(open_report[name])

    blocked_report = build_precise_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        {**form, "exclusion_zones": [{"points": [[5, 5], [8, 5], [8, 8], [5, 8]]}]},
        cuda_device,
        8.0,
    )
    assert blocked_report["is_feasible"] is False
    assert blocked_report["obstacle_hard_count"] > 0
    assert blocked_report["constraint_violation"] == blocked_report["obstacle_hard_count"]
    assert "access_error" in blocked_report


def _write_scene(directory) -> None:
    shape = (12, 12)
    dem = np.arange(shape[0], dtype=np.float32)[:, None] * np.ones(shape, dtype=np.float32)
    np.save(directory / "dem_1m.npy", dem)
    np.save(directory / "obstacle_mask_1m.npy", np.zeros(shape, dtype=np.float32))
    np.save(directory / "landuse_1m.npy", np.zeros(shape, dtype=np.int32))
    np.save(directory / "road_segments_local.npy", np.array([[0.5, 0.5, 11.5, 0.5]], dtype=np.float32))
    np.save(directory / "road_voronoi_1m.npy", np.zeros(shape, dtype=np.int64))
    np.save(directory / "demand_points.npy", np.array([[10.5, 10.5]], dtype=np.float32))
