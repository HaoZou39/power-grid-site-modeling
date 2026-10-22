#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crop a regional DEM to the satellite reference extent.

Elevations stay in source units. This step does not resample to the land-use
grid and does not min-max normalize. A few source pixels of padding are kept
so a later bilinear resample has neighbors.
"""
from __future__ import annotations

import math
import os
from typing import Optional

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import array_bounds
from rasterio.windows import Window, from_bounds

from geo_utils import transform_xy


class DemCoverageError(RuntimeError):
    """The source DEM does not fully cover the target extent."""


def _edge_ring(bounds, samples: int = 17) -> list:
    left, bottom, right, top = bounds
    ring = []
    for i in range(samples):
        t = i / (samples - 1)
        ring.append((left + (right - left) * t, top))
    for i in range(1, samples):
        t = i / (samples - 1)
        ring.append((right, top + (bottom - top) * t))
    for i in range(1, samples):
        t = i / (samples - 1)
        ring.append((right + (left - right) * t, bottom))
    for i in range(1, samples - 1):
        t = i / (samples - 1)
        ring.append((left, bottom + (top - bottom) * t))
    ring.append(ring[0])
    return ring


def _target_polygon(ref_bounds, ref_crs: str, src_crs: str) -> dict:
    ring = _edge_ring(ref_bounds)
    xs, ys = transform_xy(ref_crs, src_crs, [p[0] for p in ring], [p[1] for p in ring])
    return {"type": "Polygon", "coordinates": [list(zip(xs, ys))]}


def _model_kind(tags: dict) -> str:
    text = " ".join(str(v) for v in tags.values()).lower()
    if "dtm" in text or "terrain" in text:
        return "DTM"
    if "dsm" in text or "surface" in text:
        return "DSM"
    return "unknown"


def describe_resolution(src, latitude: float) -> dict:
    res_x, res_y = float(src.res[0]), float(src.res[1])
    crs = src.crs
    info = {"pixel_size_x": res_x, "pixel_size_y": res_y, "crs_units": "unknown"}
    if crs is not None and crs.is_geographic:
        lat_m = 111132.0
        lon_m = 111320.0 * math.cos(math.radians(latitude))
        info.update(
            {
                "crs_units": "degrees",
                "ground_spacing_x_m": abs(res_x) * lon_m,
                "ground_spacing_y_m": abs(res_y) * lat_m,
                "note": (
                    "Source pixel size is kept. Approximate metre spacing is only a "
                    "local conversion and is not a 1 m surveyed grid."
                ),
            }
        )
    else:
        info.update(
            {
                "crs_units": "projected",
                "ground_spacing_x_m": abs(res_x),
                "ground_spacing_y_m": abs(res_y),
                "note": "Source pixel size is kept. Values are CRS units, not a resampled 1 m grid.",
            }
        )
    return info


def extract_dem(
    source_dem_path: str,
    reference_geotiff_path: str,
    output_dem_path: str,
    preview_png_path: Optional[str] = None,
    pad_pixels: int = 2,
) -> dict:
    if pad_pixels < 1:
        raise ValueError("pad_pixels must be >= 1 so bilinear resampling has a neighborhood")
    if not os.path.isfile(source_dem_path):
        raise FileNotFoundError(source_dem_path)
    if not os.path.isfile(reference_geotiff_path):
        raise FileNotFoundError(reference_geotiff_path)

    with rasterio.open(reference_geotiff_path) as ref:
        if ref.crs is None:
            raise ValueError(f"reference GeoTIFF has no CRS: {reference_geotiff_path}")
        ref_crs = ref.crs
        ref_bounds = (float(ref.bounds.left), float(ref.bounds.bottom), float(ref.bounds.right), float(ref.bounds.top))
        ref_info = {
            "path": os.path.abspath(reference_geotiff_path),
            "crs": str(ref_crs),
            "bounds": list(ref_bounds),
            "width": int(ref.width),
            "height": int(ref.height),
        }

    with rasterio.open(source_dem_path) as src:
        if src.crs is None:
            raise DemCoverageError(
                f"DEM has no CRS, so coverage cannot be checked: {source_dem_path}. "
                "The CRS is not guessed."
            )
        tags = {**src.tags(), **src.tags(1)}
        polygon = _target_polygon(ref_bounds, str(ref_crs), str(src.crs))
        lons = [p[0] for p in polygon["coordinates"][0]]
        lats = [p[1] for p in polygon["coordinates"][0]]
        center_lat = float(sum(lats) / len(lats))
        resolution = describe_resolution(src, center_lat)
        required = from_bounds(min(lons), min(lats), max(lons), max(lats), src.transform)
        if (
            required.col_off < -1e-6
            or required.row_off < -1e-6
            or required.col_off + required.width > src.width + 1e-6
            or required.row_off + required.height > src.height + 1e-6
        ):
            raise DemCoverageError(
                "Source DEM does not cover the satellite reference extent. "
                f"Required window col={required.col_off:.2f} row={required.row_off:.2f} "
                f"width={required.width:.2f} height={required.height:.2f}; "
                f"raster is {src.width} x {src.height}."
            )
        col0 = max(0, int(math.floor(required.col_off)) - pad_pixels)
        row0 = max(0, int(math.floor(required.row_off)) - pad_pixels)
        col1 = min(src.width, int(math.ceil(required.col_off + required.width)) + pad_pixels)
        row1 = min(src.height, int(math.ceil(required.row_off + required.height)) + pad_pixels)
        window = Window(col0, row0, col1 - col0, row1 - row0)
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        inside = geometry_mask(
            [polygon],
            out_shape=data.shape,
            transform=transform,
            all_touched=True,
            invert=True,
        )
        nodata = src.nodata
        if nodata is None:
            invalid = inside & ~np.isfinite(data)
        else:
            invalid = inside & (data == nodata)
        invalid_count = int(np.count_nonzero(invalid))
        inside_count = int(np.count_nonzero(inside))
        if inside_count == 0:
            raise DemCoverageError("Target polygon does not intersect any DEM pixel.")
        if invalid_count:
            raise DemCoverageError(
                f"DEM does not fully cover the target: {invalid_count} of {inside_count} "
                "touching pixels are NoData. The bundle is not released."
            )
        valid = data[inside]
        elev_min = float(np.min(valid))
        elev_max = float(np.max(valid))
        os.makedirs(os.path.dirname(os.path.abspath(output_dem_path)) or ".", exist_ok=True)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=int(data.shape[0]),
            width=int(data.shape[1]),
            transform=transform,
            compress="deflate",
            tiled=False,
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        with rasterio.open(output_dem_path, "w", **profile) as dst:
            dst.write(data, 1)
            dst.update_tags(
                SOURCE_DEM=os.path.abspath(source_dem_path),
                ELEVATION_MODEL=_model_kind(tags),
                ELEVATION_NORMALIZED="no",
                SOURCE_RESOLUTION_NOTE=resolution["note"],
            )
            if src.units and src.units[0]:
                dst.update_tags(ELEVATION_UNITS=str(src.units[0]))
        out_bounds = array_bounds(data.shape[0], data.shape[1], transform)
        summary = {
            "source_path": os.path.abspath(source_dem_path),
            "output_path": os.path.abspath(output_dem_path),
            "reference": ref_info,
            "source_crs": str(src.crs),
            "source_bounds": [float(v) for v in src.bounds],
            "source_shape": [int(src.height), int(src.width)],
            "source_nodata": None if nodata is None else float(nodata),
            "source_dtype": src.dtypes[0],
            "source_tags": tags,
            "elevation_model": _model_kind(tags),
            "elevation_units": (src.units[0] if src.units and src.units[0] else "unknown"),
            "resolution": resolution,
            "output_crs": str(src.crs),
            "output_bounds": [float(v) for v in out_bounds],
            "output_shape": [int(data.shape[0]), int(data.shape[1])],
            "output_transform": [float(v) for v in transform][:6],
            "pad_pixels": int(pad_pixels),
            "target_pixels": inside_count,
            "target_nodata_pixels": invalid_count,
            "elevation_min": elev_min,
            "elevation_max": elev_max,
            "normalized": False,
            "covers_target": True,
        }
    if preview_png_path:
        draw_dem_preview(output_dem_path, preview_png_path, summary)
        summary["preview_png"] = os.path.abspath(preview_png_path)
    print(
        f"Wrote DEM crop: {summary['output_path']} "
        f"elev {elev_min:.2f}..{elev_max:.2f} {summary['elevation_units']} "
        f"shape {summary['output_shape'][1]}x{summary['output_shape'][0]}"
    )
    return summary


def draw_dem_preview(dem_path: str, preview_png_path: str, summary: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with rasterio.open(dem_path) as src:
        arr = src.read(1).astype(np.float32)
        nodata = src.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        bounds = src.bounds
    os.makedirs(os.path.dirname(os.path.abspath(preview_png_path)) or ".", exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    image = ax.imshow(
        arr,
        cmap="terrain",
        origin="upper",
        extent=(bounds.left, bounds.right, bounds.bottom, bounds.top),
    )
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label=f"elevation ({summary.get('elevation_units', '')})")
    res = summary.get("resolution") or {}
    ax.set_title(
        "DEM crop (source values, not normalized)\n"
        f"min {summary.get('elevation_min'):.1f}  max {summary.get('elevation_max'):.1f}  "
        f"model {summary.get('elevation_model')}  "
        f"spacing ~ {res.get('ground_spacing_x_m', float('nan')):.1f} x "
        f"{res.get('ground_spacing_y_m', float('nan')):.1f} m"
    )
    ax.set_xlabel(str(summary.get("output_crs")))
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(preview_png_path, dpi=140)
    plt.close(fig)
    print(f"Wrote DEM preview: {preview_png_path}")
