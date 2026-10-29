import math
from io import BytesIO

import numpy as np
import pytest
from PIL import Image
from pyproj import Transformer

from backend.app.api.map_images import study_domain_png
from data_tools.display_grid import display_grid
from data_tools.metric_grid import metric_grid
from data_tools.scene_coordinates import local_to_lonlat
from data_tools.study_domain import crop_grid, outside_study_mask, study_domain
from modeling.context import merge_building_hard_mask


def test_utm_study_domain_is_a_true_north_ground_square_inside_the_grid():
    frame = metric_grid(27.5, 120.2, 1800)
    domain = study_domain(frame)
    ring = domain["ring"]
    assert all(0 <= x <= 1800 and 0 <= y <= 1800 for x, y in ring)
    lonlat = [local_to_lonlat(frame, x, y) for x, y in ring]
    # The top and bottom edges follow one parallel; the left and right edges follow one meridian.
    assert abs(lonlat[0][1] - lonlat[1][1]) < 1e-9 and abs(lonlat[3][1] - lonlat[2][1]) < 1e-9
    assert abs(lonlat[0][0] - lonlat[3][0]) < 1e-9 and abs(lonlat[1][0] - lonlat[2][0]) < 1e-9
    # 120.2 E is 2.8 deg west of the zone 51 central meridian, about 1.3 deg of convergence.
    tilt = math.degrees(math.atan2(ring[1][1] - ring[0][1], ring[1][0] - ring[0][0]))
    assert 1.2 < tilt < 1.4
    assert abs(math.dist(ring[0], ring[1]) - math.dist(ring[0], ring[3])) < 2.0
    assert 1750 < domain["side_m"] < 1770


def test_mercator_scene_keeps_the_full_grid():
    frame = {"crs": "EPSG:3857", "transform": [1, 0, 100, 0, -1, 200], "width": 30, "height": 20}
    domain = study_domain(frame)
    assert domain["window"] == [0, 0, 30, 20]
    assert domain["ring"] == [[0, 0], [30, 0], [30, 20], [0, 20]]
    assert not outside_study_mask(domain["ring"], (20, 30)).any()


def test_outside_cells_only_join_the_building_mask():
    frame = metric_grid(27.5, 120.2, 200)
    outside = outside_study_mask(study_domain(frame)["ring"], (200, 200))
    assert outside[0, 0] and outside[0, 199] and not outside[100, 100]
    zeros = np.zeros((200, 200), dtype=np.float32)
    empty = np.zeros((200, 200), dtype=bool)
    building = merge_building_hard_mask(zeros, empty, empty, None, outside)
    np.testing.assert_array_equal(building > 0, outside)


def test_display_png_is_cropped_to_the_study_window():
    frame = metric_grid(27.5, 120.2, 200)
    domain = study_domain(frame)
    full = display_grid(frame)
    rgba = np.zeros((full["height"], full["width"], 4), dtype=np.uint8)
    col, row, width, height = domain["window"]
    rgba[row, col] = [1, 2, 3, 255]
    buffer = BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG")
    cropped = Image.open(BytesIO(study_domain_png(buffer.getvalue(), {**frame, "study_domain": domain})))
    assert cropped.size == (width, height)
    assert cropped.getpixel((0, 0)) == (1, 2, 3, 255)
    window = crop_grid(full, domain["window"])
    lon, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform(window["transform"][2], window["transform"][5])
    assert np.allclose((lon, lat), local_to_lonlat(frame, *domain["ring"][0]), atol=1e-9)
    with pytest.raises(ValueError, match="display grid"):
        study_domain_png(buffer.getvalue(), {**frame, "width": 300, "height": 300, "study_domain": domain})
