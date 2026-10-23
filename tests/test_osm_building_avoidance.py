"""OSM centerlines block building footprints without changing haul access."""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import torch

from algorithms.common.pareto import extract_feasible_pareto_front
from algorithms.guided_search.search import pose_records
from config.project_config import load_default_config
from experiments.constraint_mask import compose_constraint_masks, policy_from_form
from experiments.haul_field_cache import scene_source_signature
from experiments.problem_context import context_from_arrays, with_constraint_masks
from modeling.context import building_hard_mask
from modeling.evaluator import compute_hard_constraints
from modeling.haul_field import build_haul_field, query_exact


def test_osm_centerline_blocks_axis_aligned_and_rotated_footprints() -> None:
    problem = _problem()
    assert np.count_nonzero(problem.osm_road_mask[8]) == problem.dem.shape[1]
    assert np.count_nonzero(problem.osm_road_mask[7]) == 0
    assert np.count_nonzero(problem.osm_road_mask[9]) == 0
    poses = torch.tensor(
        [
            [8.5, 8.5, 0.0],
            [8.5, 10.5, math.pi / 4.0],
            [8.5, 15.5, 0.0],
        ],
        dtype=torch.float32,
    )
    hard = compute_hard_constraints(
        problem.dem,
        building_hard_mask(problem),
        poses,
        6.0,
        1.0,
        device="cpu",
    )

    assert hard["obstacle_hard_count"].tolist()[0] > 0
    assert hard["obstacle_hard_count"].tolist()[1] > 0
    assert hard["obstacle_hard_count"].tolist()[2] == 0
    assert hard["is_feasible"].tolist() == [False, False, True]


def test_osm_rule_remains_active_with_landuse_policy_and_drawn_exclusion() -> None:
    base = _problem()
    landuse = np.zeros(base.dem.shape, dtype=np.int32)
    landuse[14, 14] = 1
    exclusion = [[(2.0, 2.0), (5.0, 2.0), (5.0, 5.0), (2.0, 5.0)]]
    hard_mask, soft_mask = compose_constraint_masks(
        landuse,
        exclusion,
        policy_from_form({"field_policy": "blocked", "mountain_policy": "allowed"}),
    )
    problem = with_constraint_masks(base, hard_mask, soft_mask)
    poses = torch.tensor(
        [[3.5, 3.5, 0.0], [14.5, 14.5, 0.0], [10.5, 8.5, 0.0], [10.5, 17.5, 0.0]],
        dtype=torch.float32,
    )
    metrics = compute_hard_constraints(
        problem.dem,
        building_hard_mask(problem),
        poses,
        0.8,
        0.8,
        device="cpu",
    )

    assert metrics["is_feasible"].tolist() == [False, False, False, True]
    assert np.count_nonzero(problem.obstacle_mask[8]) == 0
    assert np.count_nonzero(problem.building_obstacle_mask[8]) > 0


def test_pose_rescoring_uses_building_mask_but_haul_field_keeps_original_mask(cuda_device) -> None:
    problem = _problem(cuda_device)
    modeling = replace(load_default_config().modeling, rect_w_m=2.0, rect_h_m=2.0, device="cuda")
    field = build_haul_field(
        problem.dem,
        problem.obstacle_mask == 0,
        problem.road_segments,
        None,
    )
    # y=14.5 lies inside the default 5 m grid buffer of the row-8 centerline.
    poses = np.array([[10.5, 8.5, 0.0], [10.5, 18.5, 0.0]], dtype=np.float64)
    rows = pose_records(problem, modeling, None, poses, field=field)
    haul, blocked = query_exact(field, poses[:, :2])

    assert rows[0]["obstacle_hard_count"] > 0
    assert rows[0]["is_feasible"] is False
    assert rows[1]["obstacle_hard_count"] == 0
    assert rows[1]["is_feasible"] is True
    assert blocked.tolist() == [0.0, 0.0]
    assert rows[1]["offroad_haul_m"] == haul[1, 0]
    assert rows[1]["haul_rise_m"] == haul[1, 1]
    assert field.gate_count > 0
    assert np.count_nonzero(problem.obstacle_mask) == 0
    assert np.count_nonzero(problem.osm_road_mask) > 0
    pareto = extract_feasible_pareto_front(rows, ("dem_soft", "offroad_haul_m", "haul_rise_m"))
    assert [row["x"] for row in pareto] == [poses[1, 0]]


def test_scene_signature_changes_when_osm_segments_are_replaced(tmp_path) -> None:
    np.save(tmp_path / "dem_1m.npy", np.zeros((4, 4), dtype=np.float32))
    np.save(tmp_path / "landuse_1m.npy", np.zeros((4, 4), dtype=np.int32))
    np.save(tmp_path / "road_segments_local.npy", np.array([[0.5, 0.5, 3.5, 0.5]], dtype=np.float32))
    before = scene_source_signature(tmp_path, uses_landuse=True)

    np.save(
        tmp_path / "road_segments_local.npy",
        np.array([[0.5, 0.5, 3.5, 0.5], [0.5, 2.5, 3.5, 2.5]], dtype=np.float32),
    )
    after = scene_source_signature(tmp_path, uses_landuse=True)

    assert after != before


def _problem(device: torch.device = torch.device("cpu")):
    shape = (20, 20)
    dem = np.zeros(shape, dtype=np.float32)
    obstacle = np.zeros(shape, dtype=np.float32)
    roads = np.array([[0.5, 8.5, 19.5, 8.5]], dtype=np.float64)
    demand = np.array([[4.5, 16.5]], dtype=np.float32)
    arrays = {
        "dem": dem,
        "obstacle_mask": obstacle,
        "road_segments": roads,
        "road_voronoi": np.zeros(shape, dtype=np.int64),
        "demand_points": demand,
        "landuse": np.zeros(shape, dtype=np.int32),
    }
    return context_from_arrays(arrays, device)
