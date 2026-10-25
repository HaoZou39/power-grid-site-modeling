"""Warp model-grid colour overlays into the map's Web Mercator image grid."""

import numpy as np
from rasterio.transform import Affine, array_bounds
from rasterio.warp import calculate_default_transform, reproject, Resampling


def supported_crs(crs: str) -> bool:
    if crs == "EPSG:3857":
        return True
    try:
        code = int(crs.removeprefix("EPSG:"))
    except (ValueError, AttributeError):
        return False
    return crs.startswith("EPSG:") and (32601 <= code <= 32660 or 32701 <= code <= 32760)


def display_grid(frame: dict) -> dict:
    if not supported_crs(frame["crs"]):
        raise ValueError("scene frame must use EPSG:3857 or WGS84 UTM")
    if frame["crs"] == "EPSG:3857":
        return {key: frame[key] for key in ("crs", "transform", "width", "height")}
    bounds = array_bounds(frame["height"], frame["width"], Affine(*frame["transform"]))
    transform, width, height = calculate_default_transform(
        frame["crs"], "EPSG:3857", frame["width"], frame["height"], *bounds)
    return {"crs": "EPSG:3857", "transform": list(transform)[:6], "width": width, "height": height}


def project_overlay_rgba(rgba: np.ndarray, frame: dict) -> np.ndarray:
    if rgba.shape != (frame["height"], frame["width"], 4) or rgba.dtype != np.uint8:
        raise ValueError("overlay must be uint8 RGBA aligned with the scene grid")
    if frame["crs"] == "EPSG:3857":
        return rgba
    target = display_grid(frame)
    destination = np.zeros((4, target["height"], target["width"]), dtype=np.uint8)
    reproject(np.moveaxis(rgba, -1, 0), destination,
              src_transform=Affine(*frame["transform"]), src_crs=frame["crs"],
              dst_transform=Affine(*target["transform"]), dst_crs=target["crs"],
              resampling=Resampling.nearest, src_alpha=4, dst_alpha=4)
    return np.moveaxis(destination, 0, -1)
