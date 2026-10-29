"""Metric modeling grids; source imagery may retain its Web Mercator frame."""

from __future__ import annotations

import hashlib
import json
import math

from rasterio.transform import array_bounds, Affine
from rasterio.warp import transform_bounds

from .scene_coordinates import projection


def metric_grid(lat: float, lon: float, side_length_m: int) -> dict:
    if not all(math.isfinite(v) for v in (lat, lon, side_length_m)):
        raise ValueError("metric grid coordinates and side must be finite")
    if not -80 <= lat <= 84 or not -180 <= lon <= 180:
        raise ValueError("UTM grid requires lat in [-80, 84] and lon in [-180, 180]")
    side = int(side_length_m)
    if side != side_length_m or side < 2 or side > 10000 or side % 2:
        raise ValueError("metric side_length_m must be an even integer from 2 to 10000")
    zone = min(60, int((lon + 180) // 6) + 1)
    crs = f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"
    x, y = projection(4326, crs).transform(lon, lat)
    return {"crs": crs, "transform": [1., 0., x - side / 2, 0., -1., y + side / 2],
            "width": side, "height": side, "units": "utm_grid_m"}


def frame_id(frame: dict) -> str:
    identity = {name: frame[name] for name in ("crs", "transform", "width", "height")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def download_radius_km(lat: float, lon: float, frame: dict) -> float:
    bounds = array_bounds(frame["height"], frame["width"], Affine(*frame["transform"]))
    left, bottom, right, top = transform_bounds(frame["crs"], "EPSG:3857", *bounds, densify_pts=21)
    cx, cy = projection(4326, 3857).transform(lon, lat)
    if not all(math.isfinite(value) for value in (left, bottom, right, top)) or right < left:
        raise ValueError("metric target cannot be represented by one Web Mercator download square")
    if right - left > 20_000_000:
        raise ValueError("metric target crosses the Web Mercator antimeridian seam")
    half_side = max(abs(left - cx), abs(right - cx), abs(bottom - cy), abs(top - cy))
    return math.ceil(half_side) / 1000
