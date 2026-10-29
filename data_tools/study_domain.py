"""正北研究域：模型网格里能放下的最大正北地面正方形。

窗口以整张 `display_grid()` 的像素计，`[col, row, width, height]`。
环是局部米坐标，按左上、右上、右下、左下排列。
"""

from __future__ import annotations

import math

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import Affine

from .display_grid import display_grid
from .scene_coordinates import local_to_projected, projected_to_local, projection


def study_domain(frame: dict) -> dict:
    display = display_grid(frame)
    window = [0, 0, display["width"], display["height"]] if frame["crs"] == "EPSG:3857" else _inscribed_window(frame, display)
    col, row, width, height = window
    to_grid = projection("EPSG:3857", frame["crs"])
    ring = [
        list(projected_to_local(frame, *to_grid.transform(*local_to_projected(display, x, y))))
        for x, y in ((col, row), (col + width, row), (col + width, row + height), (col, row + height))
    ]
    return {"window": window, "ring": ring, "side_m": math.dist(ring[0], ring[1]) * abs(float(frame["transform"][0]))}


def crop_grid(grid: dict, window: list[int]) -> dict:
    a, b, c, d, e, f = grid["transform"]
    col, row, width, height = window
    return {"crs": grid["crs"], "transform": [a, b, c + a * col, d, e, f + e * row], "width": width, "height": height}


def outside_study_mask(ring: list[list[float]], shape: tuple[int, int]) -> np.ndarray:
    """True where the cell centre lies outside the study domain."""

    inside = rasterize([{"type": "Polygon", "coordinates": [[*map(tuple, ring), tuple(ring[0])]]}],
                       out_shape=shape, transform=Affine.identity(), fill=0, default_value=1, dtype=np.uint8)
    return inside == 0


def _inscribed_window(frame: dict, display: dict) -> list[int]:
    to_display = projection(frame["crs"], "EPSG:3857")
    to_grid = projection("EPSG:3857", frame["crs"])
    width, height = frame["width"], frame["height"]
    quad = np.array([
        projected_to_local(display, *to_display.transform(*local_to_projected(frame, x, y)))
        for x, y in ((0, 0), (width, 0), (width, height), (0, height))
    ])
    center = quad.mean(axis=0)
    # Web Mercator pixels are not square on the ellipsoid (about 0.5 % at 27.5 deg N).
    # Row half sizes are scaled so the domain is a ground square.
    ground = [to_grid.transform(*local_to_projected(display, *(center + offset))) for offset in ((0, 0), (1, 0), (0, 1))]
    aspect = math.dist(ground[0], ground[1]) / math.dist(ground[0], ground[2])
    half_x = math.inf
    for start, end in zip(quad, np.roll(quad, -1, axis=0)):
        normal = np.array([end[1] - start[1], start[0] - end[0]]) / math.dist(start, end)
        # A centred box fits an edge when distance >= half_x * |nx| + half_y * |ny|.
        half_x = min(half_x, abs(float(np.dot(center - start, normal))) / (abs(normal[0]) + aspect * abs(normal[1])))
    half_y = aspect * half_x
    col, row = math.ceil(center[0] - half_x), math.ceil(center[1] - half_y)
    cols, rows = math.floor(center[0] + half_x) - col, math.floor(center[1] + half_y) - row
    if cols <= 0 or rows <= 0:
        raise ValueError("scene grid is too small for a study domain")
    return [col, row, cols, rows]
