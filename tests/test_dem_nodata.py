"""DEM resampling must not keep a finite NoData sentinel as elevation."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from data_tools.dem_tool import build_dem_product


def _grid(path: Path, values: np.ndarray, nodata: float | None) -> None:
    height, width = values.shape
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(0, height, 1, 1),
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(values.astype(np.float32), 1)


def test_marked_nodata_is_not_kept_as_elevation(tmp_path: Path) -> None:
    values = np.full((2, 2), -9999.0, dtype=np.float32)
    _grid(tmp_path / "dem.tif", values, -9999.0)
    _grid(tmp_path / "ref.tif", np.zeros_like(values), None)
    with pytest.raises(ValueError, match="NaN or Inf"):
        build_dem_product(tmp_path / "dem.tif", tmp_path / "ref.tif", (2, 2))


def test_dem_without_nodata_metadata_keeps_finite_elevations(tmp_path: Path) -> None:
    values = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    _grid(tmp_path / "dem.tif", values, None)
    _grid(tmp_path / "ref.tif", values, None)
    dem, _metadata = build_dem_product(tmp_path / "dem.tif", tmp_path / "ref.tif", (2, 2))
    np.testing.assert_allclose(dem, values)


def test_uncovered_dem_without_nodata_is_rejected_instead_of_filled_with_zero(tmp_path):
    _grid(tmp_path / "dem.tif", np.full((2, 2), 100), None)
    _grid(tmp_path / "ref.tif", np.zeros((4, 4)), None)
    with pytest.raises(ValueError, match="NaN or Inf"):
        build_dem_product(tmp_path / "dem.tif", tmp_path / "ref.tif", (4, 4))


def test_zero_is_a_valid_covered_elevation(tmp_path):
    _grid(tmp_path / "dem.tif", np.zeros((2, 2)), None)
    _grid(tmp_path / "ref.tif", np.zeros((2, 2)), None)
    dem, _ = build_dem_product(tmp_path / "dem.tif", tmp_path / "ref.tif", (2, 2))
    np.testing.assert_array_equal(dem, 0)
