"""Scene files are loaded as-is. These tests do not rebuild rasters or start a search."""

from pathlib import Path

import numpy as np
import pytest
import torch

from experiments.scene_store import SCENE_ARRAYS, SCENE_METADATA, adopt_scene, list_scenes, load_scene


def _write_products(directory: Path) -> None:
    directory.mkdir(parents=True)
    np.save(directory / "dem_1m.npy", np.ones((2, 3), dtype=np.float32))
    np.save(directory / "obstacle_mask_1m.npy", np.zeros((2, 3), dtype=np.uint8))
    np.save(directory / "road_voronoi_1m.npy", np.zeros((2, 3), dtype=np.int64))
    np.save(directory / "road_segments_local.npy", np.zeros((1, 4), dtype=np.float32))
    np.save(directory / "demand_points.npy", np.array([[0.5, 0.5]], dtype=np.float32))
    (directory / SCENE_METADATA).write_text('{"demand": {"n_demand_points": 1}}', encoding="utf-8")


def test_load_scene_reads_saved_arrays_without_raw_inputs(tmp_path: Path) -> None:
    _write_products(tmp_path / "cangnan")
    context, metadata = load_scene("cangnan", torch.device("cpu"), tmp_path)
    assert context.dem.shape == (2, 3)
    assert context.demand_points.shape == (1, 2)
    assert context.dem_tensor.device.type == "cpu"
    assert metadata["scene_id"] == "cangnan"


def test_missing_scene_names_the_files_optimization_must_not_rebuild(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="dem_1m.npy"):
        load_scene("cangnan", torch.device("cpu"), tmp_path)


def test_adopt_scene_reuses_existing_products(tmp_path: Path) -> None:
    source = tmp_path / "built"
    _write_products(source)
    scene = adopt_scene(source, "cangnan", tmp_path / "scenes")
    listed = list_scenes(tmp_path / "scenes")
    assert scene.name == "cangnan"
    assert listed == [{"id": "cangnan", "title": "苍南 1800 m", "ready": True, "missing": []}]
    assert (scene / "dem_1m.npy").stat().st_ino == (source / "dem_1m.npy").stat().st_ino
    assert set(SCENE_ARRAYS).issubset({path.name for path in scene.iterdir()})
