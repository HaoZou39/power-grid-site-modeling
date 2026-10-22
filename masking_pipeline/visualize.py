#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Spatial previews that share the satellite reference extent."""
from __future__ import annotations

import os

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from geo_utils import transform_xy
from render import build_palette, mask_to_rgb


def _read_satellite(path: str, max_side: int = 900):
    with rasterio.open(path) as src:
        scale = min(1.0, max_side / max(src.width, src.height))
        height = max(1, int(round(src.height * scale)))
        width = max(1, int(round(src.width * scale)))
        rgb = src.read(out_shape=(3, height, width), resampling=Resampling.bilinear)
        bounds = src.bounds
        crs = src.crs
    image = np.transpose(rgb, (1, 2, 0))
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    return image, bounds, crs


def draw_alignment(
    satellite_path: str,
    landuse_csv: str,
    osm_geojson: str,
    dem_path: str,
    output_png: str,
) -> str:
    import json
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    image, bounds, crs = _read_satellite(satellite_path)
    left, bottom, right, top = bounds.left, bounds.bottom, bounds.right, bounds.top
    extent = (left, right, bottom, top)
    landuse = np.loadtxt(landuse_csv, delimiter=",")
    land_rgb = mask_to_rgb(np.rint(landuse).astype(np.int32), build_palette())

    with open(osm_geojson, "r", encoding="utf-8") as handle:
        roads = json.load(handle)
    lines = []
    for feature in roads.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "LineString":
            parts = [geom["coordinates"]]
        elif geom.get("type") == "MultiLineString":
            parts = geom["coordinates"]
        else:
            continue
        for part in parts:
            arr = np.asarray(part, dtype=np.float64)
            xs, ys = transform_xy("EPSG:4326", str(crs), arr[:, 0].tolist(), arr[:, 1].tolist())
            lines.append((xs, ys))

    with rasterio.open(dem_path) as src, rasterio.open(satellite_path) as ref:
        preview_h = min(ref.height, 600)
        preview_w = min(ref.width, 600)
        dem = np.full((preview_h, preview_w), np.nan, dtype=np.float32)
        dst_transform = rasterio.transform.from_bounds(left, bottom, right, top, preview_w, preview_h)
        reproject(
            source=rasterio.band(src, 1),
            destination=dem,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=dst_transform,
            dst_crs=ref.crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    os.makedirs(os.path.dirname(os.path.abspath(output_png)) or ".", exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(12, 12))
    panels = (
        (axes[0, 0], "Satellite", image, None),
        (axes[0, 1], "Land use (6 classes)", land_rgb, None),
    )
    for ax, title, picture, _ in panels:
        ax.imshow(picture, extent=extent, origin="upper")
        ax.set_title(title)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(left, right)
        ax.set_ylim(bottom, top)

    ax = axes[1, 0]
    ax.imshow(image, extent=extent, origin="upper")
    for xs, ys in lines:
        ax.plot(xs, ys, color="#ff2d2d", linewidth=0.8)
    ax.add_patch(Rectangle((left, bottom), right - left, top - bottom, fill=False, edgecolor="#1f77b4", linewidth=1.5))
    ax.set_title("Satellite + OSM roads (target box)")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)

    ax = axes[1, 1]
    shown = ax.imshow(dem, extent=extent, origin="upper", cmap="terrain")
    if np.isfinite(dem).any():
        yy = np.linspace(top, bottom, dem.shape[0])
        xx = np.linspace(left, right, dem.shape[1])
        ax.contour(xx, yy, dem, levels=8, colors="k", linewidths=0.35, alpha=0.7)
    ax.add_patch(Rectangle((left, bottom), right - left, top - bottom, fill=False, edgecolor="#1f77b4", linewidth=1.5))
    ax.set_title("DEM on the satellite extent (display resample)")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)
    fig.colorbar(shown, ax=ax, fraction=0.046, pad=0.04)

    for ax in axes.ravel():
        ax.tick_params(labelsize=7)
    fig.suptitle(f"Alignment check ({crs})", fontsize=13)
    fig.tight_layout()
    fig.savefig(output_png, dpi=130)
    plt.close(fig)
    print(f"Wrote alignment check: {output_png}")
    return os.path.abspath(output_png)
