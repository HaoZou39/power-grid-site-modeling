"""The only application-level conversion between a scene grid and longitude/latitude.

CGCS2000 geographic degrees (EPSG:4490) are the same numbers as WGS84 (EPSG:4326).
No datum grid is applied. Local meters use the scene affine: origin at the upper
left, x to the right, y downward. The map uses the same rule in `SiteFrame`.
"""

from __future__ import annotations

import math

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

_GEOGRAPHIC_AS_WGS84 = {4326, 4490}


def _crs_key(crs) -> str:
    parsed = crs if isinstance(crs, CRS) else _parse_crs(crs)
    epsg = parsed.to_epsg()
    if epsg in _GEOGRAPHIC_AS_WGS84:
        return "EPSG:4326"
    if epsg is not None:
        return f"EPSG:{epsg}"
    return parsed.to_wkt()


def _parse_crs(crs) -> CRS:
    try:
        return CRS.from_user_input(crs)
    except CRSError:
        return CRS.from_wkt(crs.to_wkt())


def projection(source_crs, target_crs) -> Transformer:
    """Return the one axis-order-fixed transformer used outside `masking_pipeline`."""
    return Transformer.from_crs(_crs_key(source_crs), _crs_key(target_crs), always_xy=True)


def _affine(frame: dict) -> tuple[float, float, float, float, float, float]:
    transform = frame["transform"]
    if len(transform) != 6:
        raise ValueError("scene frame requires six finite affine values")
    values = tuple(float(value) for value in transform)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("scene frame requires six finite affine values")
    a, b, c, d, e, f = values
    return a, b, c, d, e, f


def local_to_projected(frame: dict, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = _affine(frame)
    return c + a * x + b * y, f + d * x + e * y


def projected_to_local(frame: dict, east: float, north: float) -> tuple[float, float]:
    a, b, c, d, e, f = _affine(frame)
    if abs(b) > 1e-8 or abs(d) > 1e-8 or a == 0 or e == 0:
        raise ValueError("scene frame must be an unrotated grid with non-zero scales")
    return (east - c) / a, (north - f) / e


def local_to_lonlat(frame: dict, x: float, y: float) -> tuple[float, float]:
    east, north = local_to_projected(frame, x, y)
    lon, lat = projection(frame["crs"], 4326).transform(east, north)
    return float(lon), float(lat)


def lonlat_to_local(frame: dict, lon: float, lat: float) -> tuple[float, float]:
    east, north = projection(4326, frame["crs"]).transform(lon, lat)
    return projected_to_local(frame, float(east), float(north))
