#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CRS helpers shared by the site-data stages.

Transforms go through rasterio (PROJ). Lengths measured in EPSG:3857 are
projected metres, not geodesic ground distance.
"""
from __future__ import annotations

import hashlib
import math
from typing import Iterable, Sequence, Tuple

from pyproj import Transformer

EARTH_RADIUS_M = 6371008.8
Bounds = Tuple[float, float, float, float]  # left/west, bottom/south, right/east, top/north
_TRANSFORMERS: dict = {}


def _transformer(src_crs: str, dst_crs: str) -> Transformer:
    key = (str(src_crs), str(dst_crs))
    tool = _TRANSFORMERS.get(key)
    if tool is None:
        tool = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
        _TRANSFORMERS[key] = tool
    return tool


def transform_xy(src_crs: str, dst_crs: str, xs: Sequence[float], ys: Sequence[float]) -> Tuple[list, list]:
    if len(xs) == 0:
        return [], []
    out_x, out_y = _transformer(src_crs, dst_crs).transform(list(xs), list(ys))
    return [float(v) for v in out_x], [float(v) for v in out_y]


def transform_bounds(src_crs: str, dst_crs: str, bounds: Bounds, samples: int = 9) -> Bounds:
    """Axis-aligned bounds of a rectangle after a CRS transform.

    Edges are densified so a Web Mercator box is not under-estimated in
    geographic coordinates.
    """
    left, bottom, right, top = bounds
    if samples < 2:
        raise ValueError("samples must be >= 2")
    xs: list[float] = []
    ys: list[float] = []
    for i in range(samples):
        t = i / (samples - 1)
        xs.extend((left + (right - left) * t, left + (right - left) * t, left, right))
        ys.extend((bottom, top, bottom + (top - bottom) * t, bottom + (top - bottom) * t))
    ox, oy = transform_xy(src_crs, dst_crs, xs, ys)
    return min(ox), min(oy), max(ox), max(oy)


def bounds_center(bounds: Bounds) -> Tuple[float, float]:
    left, bottom, right, top = bounds
    return (left + right) / 2.0, (bottom + top) / 2.0


def buffer_bounds(bounds: Bounds, buffer_m: float) -> Bounds:
    """Expand an axis-aligned box by ``buffer_m`` in the same linear units."""
    if buffer_m < 0:
        raise ValueError("buffer_m must be >= 0")
    left, bottom, right, top = bounds
    return left - buffer_m, bottom - buffer_m, right + buffer_m, top + buffer_m


def bounds_contain(outer: Bounds, inner: Bounds, tol: float = 0.0) -> bool:
    return (
        inner[0] >= outer[0] - tol
        and inner[1] >= outer[1] - tol
        and inner[2] <= outer[2] + tol
        and inner[3] <= outer[3] + tol
    )


def distance_outside_bounds(x: float, y: float, bounds: Bounds) -> float:
    """Euclidean distance from a point to the box, in the box's own units."""
    left, bottom, right, top = bounds
    dx = 0.0 if left <= x <= right else (left - x if x < left else x - right)
    dy = 0.0 if bottom <= y <= top else (bottom - y if y < bottom else y - top)
    return math.hypot(dx, dy)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def polyline_length_haversine(coords: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        total += haversine_m(lon1, lat1, lon2, lat2)
    return total


def polyline_length_xy(xs: Sequence[float], ys: Sequence[float]) -> float:
    total = 0.0
    for i in range(len(xs) - 1):
        total += math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i])
    return total


def sha256_file(path: str, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def file_signature(path: str) -> dict:
    import os

    st = os.stat(path)
    return {
        "path": os.path.abspath(path),
        "size": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
    }


def point_in_bounds(x: float, y: float, bounds: Bounds) -> bool:
    left, bottom, right, top = bounds
    return left <= x <= right and bottom <= y <= top


def segment_intersects_bounds(x1: float, y1: float, x2: float, y2: float, bounds: Bounds) -> bool:
    """Liang-Barsky test of a segment against an axis-aligned rectangle."""
    left, bottom, right, top = bounds
    dx = x2 - x1
    dy = y2 - y1
    p = (-dx, dx, -dy, dy)
    q = (x1 - left, right - x1, y1 - bottom, top - y1)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return False
            continue
        t = qi / pi
        if pi < 0:
            if t > u2:
                return False
            if t > u1:
                u1 = t
        else:
            if t < u1:
                return False
            if t < u2:
                u2 = t
    return True


def iter_chunks(items: Iterable, size: int):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
