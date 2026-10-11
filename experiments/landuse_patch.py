"""Mark the connected land-use patch around a click. This does not run a segmentation model."""

from __future__ import annotations

from collections import deque

import numpy as np

DEFAULT_MAX_CELLS = 8000


def connected_class_ring(
    landuse: np.ndarray,
    x: float,
    y: float,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> dict[str, object]:
    """Return the outer ring of the 4-connected same-class patch that contains the click."""

    if landuse.ndim != 2 or landuse.size == 0:
        raise ValueError("landuse must be a non-empty 2D array")
    if max_cells < 1:
        raise ValueError("max_cells must be positive")
    height, width = landuse.shape
    if not (np.isfinite(x) and np.isfinite(y)):
        raise ValueError("click coordinates must be finite")
    if x < 0 or y < 0 or x >= width or y >= height:
        raise ValueError("click is outside the land-use grid")
    start_col = int(np.floor(x))
    start_row = int(np.floor(y))
    class_id = int(landuse[start_row, start_col])
    cells = _flood(landuse, start_row, start_col, class_id, max_cells)
    mask = np.zeros((height, width), dtype=np.uint8)
    rows, cols = zip(*cells)
    mask[rows, cols] = 1
    return {
        "class_id": class_id,
        "cell_count": len(cells),
        "points": _outer_ring(mask),
    }


def _flood(
    landuse: np.ndarray,
    start_row: int,
    start_col: int,
    class_id: int,
    max_cells: int,
) -> list[tuple[int, int]]:
    height, width = landuse.shape
    seen = np.zeros((height, width), dtype=bool)
    seen[start_row, start_col] = True
    queue: deque[tuple[int, int]] = deque([(start_row, start_col)])
    cells: list[tuple[int, int]] = []
    while queue:
        row, col = queue.popleft()
        cells.append((row, col))
        if len(cells) > max_cells:
            raise ValueError(f"connected patch exceeds {max_cells} cells")
        for next_row, next_col in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            if next_row < 0 or next_col < 0 or next_row >= height or next_col >= width:
                continue
            if seen[next_row, next_col] or int(landuse[next_row, next_col]) != class_id:
                continue
            seen[next_row, next_col] = True
            queue.append((next_row, next_col))
    return cells


def _outer_ring(mask: np.ndarray) -> list[tuple[float, float]]:
    from rasterio.features import shapes
    from rasterio.transform import Affine

    rings: list[tuple[float, float]] = []
    for geometry, value in shapes(mask, mask=mask.astype(bool), transform=Affine(1, 0, 0, 0, 1, 0)):
        if int(value) != 1:
            continue
        ring = [(float(x_coord), float(y_coord)) for x_coord, y_coord in geometry["coordinates"][0]]
        if len(ring) > len(rings):
            rings = ring
    if len(rings) < 4:
        raise ValueError("connected patch did not produce a polygon")
    return rings
