from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from scipy.ndimage import zoom

from .io_utils import LOCAL_COORD_CONVENTION, ensure_2d_finite, save_array_product


def build_dem_product(
    dem_path: Path,
    output_path: Path | None = None,
    dem_input_resolution_m: float = 10.0,
    target_resolution_m: float = 1.0,
) -> tuple[np.ndarray, dict]:
    if not dem_path.exists():
        raise FileNotFoundError(dem_path)
    if dem_input_resolution_m <= 0 or target_resolution_m <= 0:
        raise ValueError("DEM resolutions must be positive")
    with rasterio.open(dem_path) as src:
        dem_raw = src.read(1).astype(np.float32)
    ensure_2d_finite("dem_raw", dem_raw)
    scale = dem_input_resolution_m / target_resolution_m
    if abs(scale - 1.0) > 1e-9:
        dem = zoom(dem_raw, zoom=scale, order=1).astype(np.float32)
    else:
        dem = dem_raw.astype(np.float32, copy=False)
    ensure_2d_finite("dem", dem)
    metadata = {
        "source_path": str(dem_path),
        "raw_shape": list(dem_raw.shape),
        "shape": list(dem.shape),
        "input_resolution_m": dem_input_resolution_m,
        "target_resolution_m": target_resolution_m,
        "interpolation": "bilinear",
        "local_coord_convention": LOCAL_COORD_CONVENTION,
    }
    if output_path is not None:
        save_array_product(output_path, dem, metadata)
    return dem, metadata

