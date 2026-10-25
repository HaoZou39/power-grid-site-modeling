import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine

from data_tools.metric_grid import metric_grid
from data_tools.display_grid import display_grid, project_overlay_rgba


def test_metric_overlay_is_warped_to_mercator_at_the_same_world_position():
    frame = metric_grid(27.5, 120.2, 200)
    rgba = np.zeros((200, 200, 4), dtype=np.uint8)
    rgba[90:110, 90:110] = [220, 30, 10, 255]
    warped = project_overlay_rgba(rgba, frame)
    display = display_grid(frame)
    assert display["crs"] == "EPSG:3857"
    assert warped.shape == (display["height"], display["width"], 4)
    x, y = Affine(*frame["transform"]) * (100, 100)
    mx, my = Transformer.from_crs(frame["crs"], 3857, always_xy=True).transform(x, y)
    col, row = ~Affine(*display["transform"]) * (mx, my)
    assert list(warped[int(row), int(col)]) == [220, 30, 10, 255]
    assert (warped[..., 3] == 0).any()


def test_legacy_overlay_keeps_its_original_pixels_and_bounds():
    frame = {"crs": "EPSG:3857", "transform": [1, 0, 100, 0, -1, 200], "width": 3, "height": 2}
    rgba = np.arange(24, dtype=np.uint8).reshape(2, 3, 4)
    assert display_grid(frame) == frame
    np.testing.assert_array_equal(project_overlay_rgba(rgba, frame), rgba)
