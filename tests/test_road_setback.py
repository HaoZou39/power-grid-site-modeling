"""1 m grid road setback. Distance is to the nearest road cell, not a continuous clearance."""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pytest
import torch
from scipy.ndimage import distance_transform_edt

from algorithms.guided_search.search import pose_records
from config.project_config import load_default_config
from experiments.constraint_mask import compose_constraint_masks, policy_from_form
from experiments.problem_context import context_from_arrays, with_constraint_masks
from experiments.scene_store import construction_feasibility_png
from modeling.context import (
    building_hard_mask,
    compose_building_hard_mask,
    require_road_setback_m,
    road_building_buffer,
    soft_obstacle_tensor,
)
from modeling.evaluator import compute_hard_constraints
from modeling.haul_field import build_haul_field, query_exact
from modeling.masks import compute_hard_footprint_indices
from modeling.masks import compute_soft_footprint
from modeling.obstacle_model import compute_obstacle_soft_loss


SHAPE = (40, 40)


def _arrays(landuse: np.ndarray, segments: np.ndarray, obstacle: np.ndarray | None = None) -> dict[str, np.ndarray]:
    return {
        "dem": np.zeros(SHAPE, dtype=np.float32),
        "landuse": landuse,
        "obstacle_mask": np.zeros(SHAPE, dtype=np.float32) if obstacle is None else obstacle,
        "road_segments": segments,
        "road_segment_kinds": np.zeros(len(segments), np.int8),
        "road_voronoi": np.zeros(SHAPE, dtype=np.int64),
        "demand_points": np.array([[4.5, 4.5]], dtype=np.float32),
    }


def _osm_row(row: int = 20) -> np.ndarray:
    return np.array([[0.5, row + 0.5, SHAPE[1] - 0.5, row + 0.5]], dtype=np.float64)


def test_building_soft_penalty_includes_setbacks_without_changing_walkable_land():
    problem = context_from_arrays(_arrays(np.zeros(SHAPE, dtype=np.uint8), _osm_row()), torch.device("cpu"), road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    assert soft_obstacle_tensor(problem)[0, 0, 18, 20].item() == 1
    assert problem.obstacle_mask[18, 20] == 0
    updated = with_constraint_masks(problem, np.zeros(SHAPE), np.full(SHAPE, .25))
    assert soft_obstacle_tensor(updated)[0, 0, 18, 20].item() == 1
    assert soft_obstacle_tensor(updated)[0, 0, 0, 20].item() == .25


def test_land_masks_stay_on_cpu_while_building_soft_stays_on_device():
    landuse = np.zeros(SHAPE, dtype=np.uint8)
    landuse[0, 0] = 1
    device = torch.device("cpu")
    problem = context_from_arrays(
        _arrays(landuse, _osm_row()), device,
        road_setback_m=5.0, water_setback_m=5.0, highway_setback_m=30.0,
    )
    assert problem.obstacle_tensor is None and problem.obstacle_soft_tensor is None
    assert problem.obstacle_soft_mask is problem.obstacle_mask
    soft = soft_obstacle_tensor(problem)
    assert soft is problem.building_soft_tensor
    assert soft.shape == (1, 1, *SHAPE) and soft.dtype == torch.float32 and soft.device == device
    assert soft.untyped_storage().size() == SHAPE[0] * SHAPE[1] * soft.element_size()

    allowed_hard, allowed_soft = compose_constraint_masks(landuse, [], policy_from_form({"field_policy": "allowed"}))
    allowed = with_constraint_masks(problem, allowed_hard, allowed_soft)
    assert allowed.obstacle_tensor is None and allowed.obstacle_soft_tensor is None
    assert np.array_equal(allowed.obstacle_mask, allowed.obstacle_soft_mask)
    assert soft_obstacle_tensor(allowed) is allowed.building_soft_tensor
    assert allowed.building_soft_tensor[0, 0, 18, 20].item() == 1
    assert allowed.obstacle_mask[18, 20] == 0

    costly_hard, costly_soft = compose_constraint_masks(
        landuse, [], policy_from_form({"field_policy": "costly", "field_cost": 0.5}),
    )
    costly = with_constraint_masks(problem, costly_hard, costly_soft)
    assert costly.obstacle_tensor is None and costly.obstacle_soft_tensor is None
    assert costly.obstacle_soft_mask[0, 0] == np.float32(0.5)
    assert costly.obstacle_mask[0, 0] == 0
    assert soft_obstacle_tensor(costly) is costly.building_soft_tensor
    assert costly.building_soft_tensor.dtype == torch.float32 and costly.building_soft_tensor.device == device
    assert costly.building_soft_tensor[0, 0, 0, 0].item() == pytest.approx(0.5)


def test_setback_soft_gradient_pushes_a_boundary_pose_away_from_the_road():
    problem = context_from_arrays(_arrays(np.zeros(SHAPE, dtype=np.uint8), _osm_row()), torch.device("cpu"), road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    pose = torch.tensor([[20.5, 25.5, 0.0]], requires_grad=True)
    footprint = compute_soft_footprint(pose, 2., 2., SHAPE, load_default_config().modeling.soft_mask_sharpness)
    loss = compute_obstacle_soft_loss(soft_obstacle_tensor(problem), footprint["grid"], footprint["weights"])
    loss.sum().backward()
    assert loss.item() > 0
    assert torch.isfinite(pose.grad).all()
    assert pose.grad[0, 1] < 0  # Gradient descent increases y, away from the horizontal road.


def _counts(problem, poses, width, height):
    return compute_hard_constraints(
        problem.dem,
        building_hard_mask(problem),
        torch.tensor(poses, dtype=torch.float32),
        width,
        height,
        device="cpu",
    )


def test_satellite_road_buffer_follows_cell_distance() -> None:
    landuse = np.zeros(SHAPE, dtype=np.int32)
    landuse[20, 20] = 3
    before = landuse.tobytes()
    buffer = road_building_buffer(landuse, np.zeros(SHAPE, dtype=bool), 5.0)
    assert landuse.tobytes() == before
    assert buffer[20, 20]
    assert buffer[20, 25]
    assert not buffer[20, 26]
    assert buffer[24, 23]
    assert not buffer[24, 24]


def test_osm_centerline_buffer_follows_cell_distance() -> None:
    buffer = road_building_buffer(np.zeros(SHAPE, dtype=np.int32), _centerline_mask(), 5.0)
    assert buffer[20].all()
    assert buffer[15].all()
    assert not buffer[14].any()
    assert not buffer[26].any()


def test_satellite_and_osm_buffers_are_the_union() -> None:
    landuse = np.zeros(SHAPE, dtype=np.int32)
    landuse[5, 5] = 3
    osm = _centerline_mask()
    combined = road_building_buffer(landuse, osm, 5.0)
    satellite = road_building_buffer(landuse, np.zeros(SHAPE, dtype=bool), 5.0)
    roads = road_building_buffer(np.zeros(SHAPE, dtype=np.int32), osm, 5.0)
    assert np.array_equal(combined, np.logical_or(satellite, roads))
    assert combined[5, 10]
    assert not roads[5, 10]
    assert combined[20, 0]
    assert not satellite[20, 0]


def test_footprint_is_infeasible_only_when_it_covers_a_buffer_cell() -> None:
    problem = context_from_arrays(
        _arrays(np.zeros(SHAPE, dtype=np.int32), _osm_row()),
        torch.device("cpu"),
     road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    clear = _counts(problem, [[10.5, 27.5, 0.0]], 1.0, 1.0)
    touching = _counts(problem, [[10.5, 25.5, 0.0]], 1.0, 1.0)
    assert clear["is_feasible"].tolist() == [True]
    assert touching["obstacle_hard_count"].tolist() == [1]
    assert touching["is_feasible"].tolist() == [False]


def test_rotated_footprint_uses_the_same_buffer() -> None:
    problem = context_from_arrays(
        _arrays(np.zeros(SHAPE, dtype=np.int32), _osm_row()),
        torch.device("cpu"),
     road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    pose = [[10.5, 27.5, 0.0], [10.5, 27.5, math.pi / 2.0]]
    hard = _counts(problem, pose, 6.0, 1.0)
    mask = building_hard_mask(problem)
    for index, item in enumerate(compute_hard_footprint_indices(np.asarray(pose), 6.0, 1.0, SHAPE)):
        covered = bool(mask[item[:, 0], item[:, 1]].any())
        assert covered is (index == 1)
        assert bool(hard["is_feasible"][index]) is (not covered)


def test_zero_setback_forbids_the_road_cell_without_a_neighbour() -> None:
    landuse = np.zeros(SHAPE, dtype=np.int32)
    landuse[20, 20] = 3
    buffer = road_building_buffer(landuse, np.zeros(SHAPE, dtype=bool), 0.0)
    assert buffer[20, 20]
    assert not buffer[20, 21]
    assert not buffer[21, 20]


@pytest.mark.parametrize("value", [-0.1, math.nan, math.inf, "five", None])
def test_illegal_setback_is_rejected(value) -> None:
    with pytest.raises(ValueError, match="road_setback_m"):
        require_road_setback_m(value)


def test_land_constraints_and_drawn_exclusion_still_block() -> None:
    landuse = np.zeros(SHAPE, dtype=np.int32)
    landuse[2, 2] = 2
    base = context_from_arrays(_arrays(landuse, _osm_row()), torch.device("cpu"), road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    exclusion = [[(30.0, 30.0), (34.0, 30.0), (34.0, 34.0), (30.0, 34.0)]]
    hard_mask, soft_mask = compose_constraint_masks(
        landuse,
        exclusion,
        policy_from_form({"field_policy": "allowed", "mountain_policy": "allowed"}),
    )
    problem = with_constraint_masks(base, hard_mask, soft_mask)
    metrics = _counts(
        problem,
        [[2.5, 2.5, 0.0], [32.5, 32.5, 0.0], [4.5, 4.5, 0.0]],
        0.8,
        0.8,
    )
    assert metrics["is_feasible"].tolist() == [False, False, True]
    assert problem.obstacle_mask[15, 20] == 0
    assert problem.building_obstacle_mask[15, 20] == 1


def test_setback_does_not_change_the_haul_mask_or_route(cuda_device) -> None:
    landuse = np.zeros(SHAPE, dtype=np.int32)
    segments = _osm_row()
    narrow = context_from_arrays(_arrays(landuse, segments), torch.device("cpu"), road_setback_m=0.0, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    wide = context_from_arrays(_arrays(landuse, segments), torch.device("cpu"), road_setback_m=5.0, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    assert np.array_equal(narrow.obstacle_mask, wide.obstacle_mask)
    assert wide.building_obstacle_mask[15, 10] == 1
    assert narrow.building_obstacle_mask[15, 10] == 0
    field = build_haul_field(wide.dem, wide.obstacle_mask == 0, wide.road_segments, None)
    site = np.array([[10.5, 15.5], [10.5, 27.5]])
    measured, blocked = query_exact(field, site)
    assert blocked.tolist() == [0.0, 0.0]
    assert _counts(wide, [[10.5, 15.5, 0.0]], 1.0, 1.0)["is_feasible"].tolist() == [False]
    other = build_haul_field(narrow.dem, narrow.obstacle_mask == 0, narrow.road_segments, None)
    again, again_blocked = query_exact(other, site)
    assert again_blocked.tolist() == [0.0, 0.0]
    assert again.tolist() == measured.tolist()
    modeling = replace(load_default_config().modeling, rect_w_m=1.0, rect_h_m=1.0, device="cuda")
    posed = context_from_arrays(_arrays(landuse, segments), cuda_device, road_setback_m=5.0, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    rows = pose_records(
        posed,
        modeling,
        None,
        np.column_stack([site, np.zeros(len(site))]),
        field=field,
    )
    assert [row["is_feasible"] for row in rows] == [False, True]
    assert rows[0]["offroad_haul_m"] == measured[0, 0]
    assert rows[1]["haul_rise_m"] == measured[1, 1]


def test_search_pose_rescore_and_preview_share_the_building_mask(tmp_path) -> None:
    landuse = np.zeros(SHAPE, dtype=np.int32)
    landuse[8, 8] = 3
    stored = landuse.copy()
    obstacle = np.zeros(SHAPE, dtype=np.float32)
    problem = context_from_arrays(
        _arrays(landuse, np.zeros((0, 4), dtype=np.float64), obstacle),
        torch.device("cpu"),
        road_setback_m=5.0,
     water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    scene = tmp_path / "cangnan"
    scene.mkdir()
    np.save(scene / "landuse_1m.npy", stored)
    np.save(scene / "road_segments_local.npy", np.zeros((0, 4), dtype=np.float64))
    np.save(scene / "road_segment_kind.npy", np.zeros(len(np.load(scene / "road_segments_local.npy")), np.int8))
    before_landuse = (scene / "landuse_1m.npy").read_bytes()
    form = {
        "mountain_policy": "allowed",
        "field_policy": "allowed",
        "field_cost": 0.5,
        "exclusion_zones": [],
        "feasible_zones": [],
        "road_setback_m": 5.0,
    }
    from io import BytesIO

    from PIL import Image

    pixels = np.asarray(Image.open(BytesIO(construction_feasibility_png("cangnan", form, tmp_path))).convert("RGBA"))
    expected = compose_building_hard_mask(obstacle, stored, np.zeros(SHAPE, dtype=bool), 5.0)
    assert np.array_equal(building_hard_mask(problem) > 0, expected > 0)
    assert np.all(pixels[expected > 0, 0] == 235)
    assert np.all(pixels[expected == 0, 0] == 45)
    direct = _counts(problem, [[13.5, 8.5, 0.0], [20.5, 8.5, 0.0]], 1.0, 1.0)
    assert direct["is_feasible"].tolist() == [False, True]
    assert (scene / "landuse_1m.npy").read_bytes() == before_landuse
    assert np.array_equal(landuse, stored)


def test_distance_transform_is_not_repeated_for_the_same_setback(monkeypatch) -> None:
    calls = {"count": 0}
    real = distance_transform_edt

    def _counting(mask, sampling):
        calls["count"] += 1
        return real(mask, sampling=sampling)

    monkeypatch.setattr("modeling.context.distance_transform_edt", _counting)
    landuse = np.zeros(SHAPE, dtype=np.int32)
    landuse[20, 20] = 3
    problem = context_from_arrays(
        _arrays(landuse, np.zeros((0, 4))),
        torch.device("cpu"),
     road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    assert calls["count"] == 1
    _counts(problem, [[4.5, 4.5, 0.0]], 1.0, 1.0)
    with_constraint_masks(problem, np.zeros(SHAPE, dtype=np.float32), np.zeros(SHAPE, dtype=np.float32))
    assert calls["count"] == 1
    with_constraint_masks(
        problem,
        np.zeros(SHAPE, dtype=np.float32),
        np.zeros(SHAPE, dtype=np.float32),
        road_setback_m=0.0,
    )
    assert calls["count"] == 2


def test_empty_roads_do_not_run_a_distance_transform(monkeypatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("empty roads must not run a distance transform")

    monkeypatch.setattr("modeling.context.distance_transform_edt", _forbidden)
    buffer = road_building_buffer(np.zeros(SHAPE, dtype=np.int32), np.zeros(SHAPE, dtype=bool), 5.0)
    assert not buffer.any()


def test_mismatched_shapes_are_rejected() -> None:
    with pytest.raises(ValueError, match="share a 2D shape"):
        road_building_buffer(np.zeros((4, 4), dtype=np.int32), np.zeros((4, 5), dtype=bool), 5.0)


def _centerline_mask() -> np.ndarray:
    from modeling.context import rasterize_osm_centerlines

    return rasterize_osm_centerlines(_osm_row(), SHAPE)
