from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject

from .io_utils import LOCAL_COORD_CONVENTION, ensure_2d_finite, save_array_product


def build_dem_product(
    dem_path: Path,
    reference_geotiff_path: Path,
    primary_grid_shape: tuple[int, int],
    output_path: Path | None = None,
    target_resolution_m: float = 1.0,
) -> tuple[np.ndarray, dict]:
    dem_path = Path(dem_path)
    reference_geotiff_path = Path(reference_geotiff_path)
    if not dem_path.exists():
        raise FileNotFoundError(dem_path)
    if not reference_geotiff_path.exists():
        raise FileNotFoundError(reference_geotiff_path)
    if len(primary_grid_shape) != 2:
        raise ValueError("primary_grid_shape must have length 2")
    height, width = (int(primary_grid_shape[0]), int(primary_grid_shape[1]))
    if height <= 0 or width <= 0 or target_resolution_m <= 0:
        raise ValueError("DEM target shape/resolution parameters are invalid")

    with rasterio.open(reference_geotiff_path) as ref:
        if ref.crs is None:
            raise ValueError(f"reference GeoTIFF has no CRS: {reference_geotiff_path}")
        ref_bounds = ref.bounds
        ref_crs = ref.crs
        ref_transform = ref.transform
        ref_raw_shape = (ref.height, ref.width)
        target_transform = from_bounds(ref_bounds.left, ref_bounds.bottom, ref_bounds.right, ref_bounds.top, width, height)

    dem = np.empty((height, width), dtype=np.float32)
    with rasterio.open(dem_path) as src:
        if src.crs is None:
            raise ValueError(f"DEM GeoTIFF has no CRS: {dem_path}")
        reproject(
            source=rasterio.band(src, 1),
            destination=dem,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=target_transform,
            dst_crs=ref_crs,
            resampling=Resampling.bilinear,
        )
        dem_crs = src.crs
        dem_transform = src.transform
        dem_raw_shape = (src.height, src.width)

    ensure_2d_finite("dem", dem)
    metadata = {
        "source_path": str(dem_path),
        "source_crs": str(dem_crs),
        "source_transform": list(dem_transform)[:6],
        "raw_shape": list(dem_raw_shape),
        "reference_geotiff_path": str(reference_geotiff_path),
        "reference_crs": str(ref_crs),
        "reference_bounds": {
            "left": float(ref_bounds.left),
            "right": float(ref_bounds.right),
            "bottom": float(ref_bounds.bottom),
            "top": float(ref_bounds.top),
        },
        "reference_transform": list(ref_transform)[:6],
        "reference_raw_shape": list(ref_raw_shape),
        "target_transform": list(target_transform)[:6],
        "shape": list(dem.shape),
        "target_resolution_m": target_resolution_m,
        "resampling": "bilinear",
        "local_coord_convention": LOCAL_COORD_CONVENTION,
    }
    if output_path is not None:
        save_array_product(output_path, dem, metadata)
    return dem, metadata
