"""Clicking a land-use cell selects only the connected patch of that class."""

from pathlib import Path

import numpy as np
import pytest

from experiments.constraint_mask import compose_constraint_masks, default_policy
from experiments.landuse_patch import connected_class_ring


def _sample_grid() -> np.ndarray:
    landuse = np.zeros((5, 5), dtype=np.int32)
    landuse[1:3, 1:3] = 1
    landuse[1, 4] = 2
    landuse[3, 4] = 1
    return landuse


def test_click_selects_only_the_connected_same_class() -> None:
    landuse = _sample_grid()
    patch = connected_class_ring(landuse, 1.2, 1.2)
    assert patch["class_id"] == 1
    assert patch["cell_count"] == 4
    hard, _soft = compose_constraint_masks(landuse, [patch["points"]], default_policy())
    assert hard[1, 1] == 1 and hard[1, 2] == 1 and hard[2, 1] == 1 and hard[2, 2] == 1
    assert hard[1, 4] == 1  # building is already hard by class, not by this patch
    assert hard[3, 4] == 1  # the other field is hard by class too
    drawn_only, _soft_only = compose_constraint_masks(np.zeros_like(landuse), [patch["points"]], default_policy())
    assert drawn_only[1:3, 1:3].min() == 1
    assert drawn_only[3, 4] == 0
    assert drawn_only[1, 4] == 0


def test_click_outside_the_grid_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        connected_class_ring(_sample_grid(), 9, 1)


def test_oversized_patch_is_rejected() -> None:
    landuse = np.ones((4, 4), dtype=np.int32)
    with pytest.raises(ValueError, match="exceeds"):
        connected_class_ring(landuse, 0.5, 0.5, max_cells=3)


def test_patch_lookup_does_not_rewrite_the_scene_file(tmp_path: Path) -> None:
    landuse = _sample_grid()
    path = tmp_path / "landuse_1m.npy"
    np.save(path, landuse)
    before = path.read_bytes()
    connected_class_ring(np.load(path), 1.2, 1.2)
    assert path.read_bytes() == before
