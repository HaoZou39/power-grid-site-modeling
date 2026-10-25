import numpy as np
import pytest
from pyproj import Geod, Transformer

from data_tools.metric_grid import metric_grid, download_radius_km, frame_id


@pytest.mark.parametrize("lat,lon", [(27.501662, 120.194639), (28.246101, 120.2), (-33.9, 151.2), (1, 5.999)])
def test_metric_pixels_match_ground_distance_within_research_tolerance(lat, lon):
    grid = metric_grid(lat, lon, 1800)
    assert grid["transform"][0] == 1 and grid["transform"][4] == -1
    assert grid["width"] == grid["height"] == 1800
    inverse = Transformer.from_crs(grid["crs"], 4326, always_xy=True)
    geod = Geod(ellps="WGS84")
    x0, y0 = grid["transform"][2], grid["transform"][5]
    for x, y in ((0, 0), (900, 900), (1800, 1800), (0, 1800), (1800, 0)):
        left = inverse.transform(x0 + x, y0 - y)
        right = inverse.transform(x0 + x + 77, y0 - y)
        assert abs(geod.inv(*left, *right)[2] / 77 - 1) < .002
    assert frame_id(grid) == frame_id(metric_grid(lat, lon, 1800))
    changed = metric_grid(lat, lon, 1802)
    assert frame_id(grid) != frame_id(changed)


def test_download_square_contains_all_metric_target_corners():
    grid = metric_grid(27.501662, 120.194639, 1800)
    radius = download_radius_km(27.501662, 120.194639, grid)
    assert radius > .9
    to_mercator = Transformer.from_crs(grid["crs"], 3857, always_xy=True)
    cx, cy = Transformer.from_crs(4326, 3857, always_xy=True).transform(120.194639, 27.501662)
    for x, y in ((0, 0), (1800, 0), (1800, 1800), (0, 1800)):
        px, py = to_mercator.transform(grid["transform"][2] + x, grid["transform"][5] - y)
        assert abs(px - cx) <= radius * 1000
        assert abs(py - cy) <= radius * 1000


@pytest.mark.parametrize("lat,lon,side", [(85, 0, 4), (-81, 0, 4), (0, 181, 4), (np.nan, 0, 4), (0, 0, 3)])
def test_invalid_metric_grid_requests_fail_explicitly(lat, lon, side):
    with pytest.raises(ValueError):
        metric_grid(lat, lon, side)


def test_antimeridian_download_fails_before_requesting_a_world_sized_image():
    grid = metric_grid(0, 180, 1800)
    with pytest.raises(ValueError, match="antimeridian"):
        download_radius_km(0, 180, grid)
