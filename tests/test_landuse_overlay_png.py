"""Palette land-use PNGs must decode to the same RGBA as the previous encoder."""

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from rasterio.warp import reproject as rasterio_reproject

from backend.app.api.map_images import bounded_png
from data_tools.display_grid import display_grid, project_landuse_classes, project_overlay_rgba
from data_tools.metric_grid import metric_grid
from experiments.constraint_mask import CLASS_COLORS, rasterize_exclusions
from experiments.scene_store import OBSTACLE_OVERLAY, write_obstacle_overlay


def _decoded(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"))


def _reference_rgba(directory: Path, landuse: np.ndarray, frame: dict | None) -> None:
    combined = np.zeros(landuse.shape + (4,), dtype=np.uint8)
    for name, (class_id, color) in CLASS_COLORS.items():
        layer = np.zeros_like(combined)
        layer[landuse == class_id] = color
        painted = project_overlay_rgba(layer, frame) if frame is not None and frame["crs"] != "EPSG:3857" else layer
        Image.fromarray(painted, mode="RGBA").save(directory / f"landuse_{name}.png")
        combined = np.maximum(combined, layer)
    painted = project_overlay_rgba(combined, frame) if frame is not None and frame["crs"] != "EPSG:3857" else combined
    Image.fromarray(painted, mode="RGBA").save(directory / OBSTACLE_OVERLAY)


def _sample_landuse() -> np.ndarray:
    landuse = np.zeros((48, 64), dtype=np.int32)
    landuse[2:20, 2:24] = 1
    landuse[8:14, 8:16] = 4
    landuse[rasterize_exclusions([[(30.2, 4.4), (46.8, 8.1), (40.5, 22.7), (28.0, 18.2)]], landuse.shape) > 0] = 2
    landuse[24:27, 2:60] = 3
    landuse[30:44, 30:50] = 5
    landuse[40, 10] = 5
    landuse[0, 0] = 9
    return landuse


def _assert_same_pngs(actual: Path, reference: Path) -> None:
    names = [*(f"landuse_{name}.png" for name in CLASS_COLORS), OBSTACLE_OVERLAY]
    for name in names:
        assert np.array_equal(_decoded(actual / name), _decoded(reference / name)), name


def test_palette_png_matches_rgba_pixels_for_a_web_mercator_grid(tmp_path: Path) -> None:
    landuse = _sample_landuse()
    frame = {"crs": "EPSG:3857", "transform": [1.0, 0.0, 100.0, 0.0, -1.0, 200.0], "width": 64, "height": 48}
    _write_scene(tmp_path / "new", landuse, frame)
    _write_scene(tmp_path / "old", landuse, None)
    write_obstacle_overlay(tmp_path / "new")
    _reference_rgba(tmp_path / "old", landuse, frame)
    _assert_same_pngs(tmp_path / "new", tmp_path / "old")
    with Image.open(tmp_path / "new" / "landuse_water.png") as image:
        assert image.mode == "P"
    assert np.array_equal(_decoded(tmp_path / "new" / "landuse_field.png")[8, 8], (0, 0, 0, 0))
    assert np.array_equal(_decoded(tmp_path / "new" / "landuse_water.png")[40, 10], (36, 112, 214, 160))


def test_empty_and_solid_class_layers_stay_exact(tmp_path: Path) -> None:
    empty = np.zeros((12, 12), dtype=np.int32)
    empty[2:5, 2:5] = 4
    solid = np.full((12, 12), 5, dtype=np.int32)
    for name, landuse in (("empty", empty), ("solid", solid)):
        _write_scene(tmp_path / name / "new", landuse, None)
        _write_scene(tmp_path / name / "old", landuse, None)
        write_obstacle_overlay(tmp_path / name / "new")
        _reference_rgba(tmp_path / name / "old", landuse, None)
        _assert_same_pngs(tmp_path / name / "new", tmp_path / name / "old")


def test_utm_palette_matches_five_rgba_warps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    def counted(*args, **kwargs):
        calls["n"] += 1
        return rasterio_reproject(*args, **kwargs)
    monkeypatch.setattr("data_tools.display_grid.reproject", counted)
    for name, frame, landuse in _utm_samples():
        calls["n"] = 0
        _write_scene(tmp_path / name / "new", landuse, frame)
        _write_scene(tmp_path / name / "old", landuse, None)
        write_obstacle_overlay(tmp_path / name / "new")
        assert calls["n"] == 1, name
        _reference_rgba(tmp_path / name / "old", landuse, frame)
        _assert_same_pngs(tmp_path / name / "new", tmp_path / name / "old")
        with Image.open(tmp_path / name / "new" / "landuse_water.png") as image:
            assert image.mode == "P"
        display = display_grid(frame)
        assert _decoded(tmp_path / name / "new" / OBSTACLE_OVERLAY).shape == (display["height"], display["width"], 4)


def test_web_mercator_overlay_does_not_reproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("EPSG:3857 land-use overlay must not reproject")
    monkeypatch.setattr("data_tools.display_grid.reproject", forbidden)
    frame = {"crs": "EPSG:3857", "transform": [1.0, 0.0, 100.0, 0.0, -1.0, 200.0], "width": 64, "height": 48}
    _write_scene(tmp_path, _sample_landuse(), frame)
    write_obstacle_overlay(tmp_path)


def test_utm_palette_thumbnail_matches_rgba_thumbnail(tmp_path: Path) -> None:
    _, frame, landuse = _utm_samples()[0]
    _write_scene(tmp_path / "new", landuse, frame)
    _write_scene(tmp_path / "old", landuse, None)
    write_obstacle_overlay(tmp_path / "new")
    _reference_rgba(tmp_path / "old", landuse, frame)
    for name in (*(f"landuse_{item}.png" for item in CLASS_COLORS), OBSTACLE_OVERLAY):
        new = np.asarray(Image.open(BytesIO(bounded_png((tmp_path / "new" / name).read_bytes(), 20))).convert("RGBA"))
        old = np.asarray(Image.open(BytesIO(bounded_png((tmp_path / "old" / name).read_bytes(), 20))).convert("RGBA"))
        assert new.shape == old.shape
        assert np.array_equal(new, old), name


def test_class_projection_rejects_unknown_values_and_keeps_mercator_pixels() -> None:
    frame = metric_grid(27.5, 120.2, 32)
    illegal = np.zeros((32, 32), dtype=np.int32)
    illegal[0, 0] = 9
    with pytest.raises(ValueError, match="0, 1, 2, 3, 4, or 5"):
        project_landuse_classes(illegal, frame)
    unsupported = {"crs": "EPSG:4326", "transform": [1.0, 0.0, 0.0, 0.0, -1.0, 4.0], "width": 4, "height": 4}
    with pytest.raises(ValueError, match="WGS84 UTM"):
        project_landuse_classes(np.zeros((4, 4), dtype=np.uint8), unsupported)
    mercator = {"crs": "EPSG:3857", "transform": [1.0, 0.0, 0.0, 0.0, -1.0, 4.0], "width": 4, "height": 4}
    source = np.arange(16, dtype=np.int32).reshape(4, 4) % 6
    projected = project_landuse_classes(source, mercator)
    assert projected.dtype == np.uint8
    assert projected.shape == source.shape
    assert np.array_equal(projected, source)


def test_bounded_png_keeps_palette_and_rgba_thumbnails_equal(tmp_path: Path) -> None:
    landuse = _sample_landuse()
    _write_scene(tmp_path / "new", landuse, None)
    _write_scene(tmp_path / "old", landuse, None)
    write_obstacle_overlay(tmp_path / "new")
    _reference_rgba(tmp_path / "old", landuse, None)
    for name in (*(f"landuse_{item}.png" for item in CLASS_COLORS), OBSTACLE_OVERLAY):
        new = np.asarray(Image.open(BytesIO(bounded_png((tmp_path / "new" / name).read_bytes(), 20))).convert("RGBA"))
        old = np.asarray(Image.open(BytesIO(bounded_png((tmp_path / "old" / name).read_bytes(), 20))).convert("RGBA"))
        assert new.shape == old.shape
        assert np.array_equal(new, old), name


def test_missing_landuse_still_paints_the_red_obstacle_mask(tmp_path: Path) -> None:
    mask = np.zeros((6, 5), dtype=np.uint8)
    mask[1:3, 2:4] = 1
    np.save(tmp_path / "obstacle_mask_1m.npy", mask)
    write_obstacle_overlay(tmp_path)
    decoded = _decoded(tmp_path / OBSTACLE_OVERLAY)
    assert np.array_equal(decoded[2, 3], (255, 70, 84, 130))
    assert np.array_equal(decoded[0, 0], (0, 0, 0, 0))
    assert not (tmp_path / "landuse_water.png").exists()


def _rich_landuse(side: int) -> np.ndarray:
    landuse = np.zeros((side, side), dtype=np.int32)
    landuse[1:side // 2, 1:side // 3] = 1
    landuse[3:7, 3:8] = 4
    landuse[rasterize_exclusions([[(side * 0.45, side * 0.2), (side * 0.85, side * 0.35), (side * 0.6, side * 0.7)]], landuse.shape) > 0] = 2
    landuse[side // 2:side // 2 + 2, 1:side - 1] = 3
    landuse[side - 6:side - 2, side // 2:side - 2] = 5
    landuse[0, 0] = 1
    landuse[0, side - 1] = 5
    landuse[side - 1, 0] = 2
    landuse[side - 1, side - 1] = 3
    landuse[side // 2, side // 2] = 5
    landuse[2, side // 2] = 1
    return landuse


def _utm_samples():
    samples = [
        ("wenzhou", metric_grid(27.5, 120.2, 32), _rich_landuse(32)),
        ("shifted", metric_grid(27.55, 120.45, 48), _rich_landuse(48)),
        ("south", metric_grid(-33.8, 151.2, 32), _rich_landuse(32)),
        ("europe", metric_grid(48.8, 2.3, 40), _rich_landuse(40)),
        ("nanxi", metric_grid(28.2, 120.8, 32), _rich_landuse(32)),
    ]
    stretched = metric_grid(27.5, 120.21, 32)
    stretched = {**stretched, "transform": [1.15, 0.0, stretched["transform"][2] + 0.37, 0.0, -0.87, stretched["transform"][5] - 0.2]}
    samples.append(("noninteger", stretched, _rich_landuse(32)))
    empty = np.zeros((32, 32), dtype=np.int32)
    empty[2:8, 2:8] = 4
    samples.append(("empty", metric_grid(27.5, 120.2, 32), empty))
    samples.append(("solid", metric_grid(28.2, 120.8, 32), np.full((32, 32), 5, dtype=np.int32)))
    return samples


def _write_scene(directory: Path, landuse: np.ndarray, frame: dict | None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "landuse_1m.npy", landuse)
    if frame is None:
        return
    payload = {
        "dem": {
            "reference_crs": frame["crs"],
            "target_transform": frame["transform"],
            "shape": [int(landuse.shape[0]), int(landuse.shape[1])],
        }
    }
    import json
    (directory / "data_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
