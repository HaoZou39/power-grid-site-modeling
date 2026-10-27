"""Class policy and drawn exclusions compose masks without rewriting a scene."""

from pathlib import Path

import numpy as np
import torch
from PIL import Image

from experiments.constraint_mask import LandusePolicy, compose_constraint_masks, default_policy, policy_from_form
from experiments.scene_store import write_obstacle_overlay
from modeling.evaluator import compute_hard_constraints
from modeling.masks import compute_soft_footprint
from modeling.obstacle_model import compute_obstacle_soft_loss


def test_mountain_is_blocked_unless_the_form_allows_it() -> None:
    landuse = np.zeros((3, 3), dtype=np.int32)
    landuse[1, 1] = 4
    blocked, _soft = compose_constraint_masks(landuse, [], policy_from_form({"mountain_policy": "blocked"}))
    allowed, _allowed_soft = compose_constraint_masks(landuse, [], policy_from_form({}))
    assert blocked[1, 1] == 1
    assert allowed[1, 1] == 0
    landuse = np.array([[0, 1], [4, 5], [3, 2]], dtype=np.int32)
    hard, soft = compose_constraint_masks(landuse, [], default_policy())
    expected = np.array([[0, 1], [0, 1], [1, 1]], dtype=np.float32)
    assert np.array_equal(hard, expected)
    assert np.array_equal(soft, expected)


def test_costly_field_stays_feasible_and_costs_more_than_open_ground(cuda_device: torch.device) -> None:
    landuse = np.zeros((8, 8), dtype=np.int32)
    landuse[4, 4] = 1
    pose = torch.tensor([[4.5, 4.5, 0.0]], dtype=torch.float32, device=cuda_device)
    dem = np.zeros_like(landuse, dtype=np.float32)
    blocked_hard, _blocked_soft = compose_constraint_masks(landuse, [], default_policy())
    blocked = compute_hard_constraints(dem, blocked_hard, pose, 0.8, 0.8, device="cpu")
    assert bool(blocked["is_feasible"][0].item()) is False

    allowed_hard, allowed_soft = compose_constraint_masks(
        landuse,
        [],
        LandusePolicy(hard_classes=(2, 3, 5), costly=((1, 0.5),)),
    )
    allowed = compute_hard_constraints(dem, allowed_hard, pose, 0.8, 0.8, device="cpu")
    assert bool(allowed["is_feasible"][0].item()) is True
    field_cost = _soft_overlap(allowed_soft, pose, cuda_device)
    open_cost = _soft_overlap(np.zeros_like(allowed_soft), pose, cuda_device)
    assert field_cost > open_cost


def test_drawn_polygon_blocks_only_the_cells_it_covers() -> None:
    landuse = np.zeros((6, 6), dtype=np.int32)
    polygon = [[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]]
    hard, soft = compose_constraint_masks(landuse, polygon, default_policy())
    assert hard[0, 0] == 0
    assert hard[2, 2] == 1
    assert soft[2, 2] == 1
    dem = np.zeros_like(landuse, dtype=np.float32)
    inside = compute_hard_constraints(
        dem,
        hard,
        torch.tensor([[2.5, 2.5, 0.0]]),
        0.8,
        0.8,
        device="cpu",
    )
    outside = compute_hard_constraints(
        dem,
        hard,
        torch.tensor([[0.5, 0.5, 0.0]]),
        0.8,
        0.8,
        device="cpu",
    )
    assert bool(inside["is_feasible"][0].item()) is False
    assert bool(outside["is_feasible"][0].item()) is True
    assert torch.equal(inside["constraint_violation"], inside["obstacle_hard_count"])


def test_feasible_zone_blocks_outside_and_keeps_an_interior_exclusion() -> None:
    landuse = np.zeros((6, 6), dtype=np.int32)
    dem = np.zeros_like(landuse, dtype=np.float32)
    feasible = [[(1.0, 1.0), (5.0, 1.0), (5.0, 5.0), (1.0, 5.0)]]
    open_hard, open_soft = compose_constraint_masks(landuse, [], default_policy(), feasible)
    assert open_hard[0, 0] == 1
    assert open_soft[0, 0] == 1
    assert open_hard[4, 1] == 0
    outside = compute_hard_constraints(
        dem,
        open_hard,
        torch.tensor([[0.5, 0.5, 0.0]]),
        0.8,
        0.8,
        device="cpu",
    )
    inside = compute_hard_constraints(
        dem,
        open_hard,
        torch.tensor([[3.5, 3.5, 0.0]]),
        0.8,
        0.8,
        device="cpu",
    )
    assert bool(outside["is_feasible"][0].item()) is False
    assert bool(inside["is_feasible"][0].item()) is True
    blocked, _soft = compose_constraint_masks(
        landuse,
        [[(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]],
        default_policy(),
        feasible,
    )
    assert blocked[3, 3] == 1
    assert blocked[4, 1] == 0
    hole = compute_hard_constraints(
        dem,
        blocked,
        torch.tensor([[3.5, 3.5, 0.0]]),
        0.8,
        0.8,
        device="cpu",
    )
    assert bool(hole["is_feasible"][0].item()) is False
    union, _union_soft = compose_constraint_masks(
        landuse,
        [],
        default_policy(),
        [
            [(0.2, 0.2), (1.5, 0.2), (1.5, 1.5), (0.2, 1.5)],
            [(3.2, 3.2), (4.8, 3.2), (4.8, 4.8), (3.2, 4.8)],
        ],
    )
    assert union[1, 1] == 0
    assert union[4, 4] == 0
    assert union[0, 5] == 1
    polygon = [[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]]
    without = compose_constraint_masks(landuse, polygon, default_policy())
    empty = compose_constraint_masks(landuse, polygon, default_policy(), [])
    assert np.array_equal(without[0], empty[0])
    assert np.array_equal(without[1], empty[1])


def test_compose_does_not_rewrite_scene_landuse(tmp_path: Path) -> None:
    landuse = np.zeros((4, 4), dtype=np.int32)
    landuse[1, 1] = 1
    path = tmp_path / "landuse_1m.npy"
    obstacle = tmp_path / "obstacle_mask_1m.npy"
    np.save(path, landuse)
    np.save(obstacle, (landuse == 1).astype(np.float32))
    before_landuse = path.read_bytes()
    before_obstacle = obstacle.read_bytes()
    compose_constraint_masks(np.load(path), [[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]], default_policy())
    assert path.read_bytes() == before_landuse
    assert obstacle.read_bytes() == before_obstacle


def test_class_overlay_uses_four_colors_and_leaves_buildable_clear(tmp_path: Path) -> None:
    landuse = np.array([[0, 1], [4, 2], [3, 5]], dtype=np.int32)
    np.save(tmp_path / "landuse_1m.npy", landuse)
    write_obstacle_overlay(tmp_path)
    field = Image.open(tmp_path / "landuse_field.png").convert("RGBA")
    building = Image.open(tmp_path / "landuse_building.png").convert("RGBA")
    road = Image.open(tmp_path / "landuse_road.png").convert("RGBA")
    water = Image.open(tmp_path / "landuse_water.png").convert("RGBA")
    assert field.getpixel((0, 0))[3] == 0
    assert field.getpixel((1, 0))[3] > 0
    assert building.getpixel((1, 1))[3] > 0
    assert road.getpixel((0, 2))[3] > 0
    assert water.getpixel((1, 2))[3] > 0
    colors = {
        field.getpixel((1, 0))[:3],
        building.getpixel((1, 1))[:3],
        road.getpixel((0, 2))[:3],
        water.getpixel((1, 2))[:3],
    }
    assert len(colors) == 4
    assert building.getpixel((0, 0))[3] == 0


def _soft_overlap(mask: np.ndarray, pose: torch.Tensor, device: torch.device) -> float:
    tensor = torch.as_tensor(mask, dtype=torch.float32, device=device)[None, None]
    footprint = compute_soft_footprint(pose, 0.8, 0.8, mask.shape, 8.0)
    loss = compute_obstacle_soft_loss(tensor, footprint["grid"], footprint["weights"])
    return float(loss[0].item())
