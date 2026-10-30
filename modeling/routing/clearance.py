"""One distance field per scene mask. Pixel (row, col) is the center (col+0.5, row+0.5)."""

import numpy as np
from scipy.ndimage import distance_transform_edt


def center_distance(mask: np.ndarray) -> np.ndarray:
    """Distance from each pixel center to the nearest True pixel center, in cell units."""
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2 or mask.shape[0] < 1 or mask.shape[1] < 1:
        raise ValueError("clearance mask must be a non-empty 2D array")
    if not mask.any():
        return np.full(mask.shape, np.inf, dtype=np.float32)
    return distance_transform_edt(~mask).astype(np.float32)


def zone_mask(zones, shape: tuple[int, int]) -> np.ndarray:
    """Cells touched by forbidden polygons. A segment missing every marked cell misses the polygons."""
    height, width = shape
    if height < 1 or width < 1:
        raise ValueError("zone mask shape must be positive")
    mask = np.zeros((height, width), dtype=bool)
    if not zones:
        return mask
    from rasterio.features import rasterize
    from rasterio.transform import Affine
    burned = rasterize(
        [(zone, 1) for zone in zones],
        out_shape=(height, width),
        transform=Affine(1, 0, 0, 0, 1, 0),
        all_touched=True,
        fill=0,
        dtype="uint8",
    )
    return burned.astype(bool)
