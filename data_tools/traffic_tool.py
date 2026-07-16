from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, shape

from .io_utils import LOCAL_COORD_CONVENTION, save_array_product, write_json


def _iter_lines(geom):
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        yield from geom.geoms


def build_road_product(
    osm_roads_path: Path,
    output_segments_path: Path | None,
    output_voronoi_path: Path | None,
    reference_geotiff_path: Path,
    target_shape: tuple[int, int],
    road_dp_tolerance_m: float,
    road_resolution_m: float = 1.0,
    chunk_points: int = 8192,
) -> tuple[np.ndarray, np.ndarray, dict]:
    osm_roads_path = Path(osm_roads_path)
    reference_geotiff_path = Path(reference_geotiff_path)
    if not osm_roads_path.exists():
        raise FileNotFoundError(osm_roads_path)
    if not reference_geotiff_path.exists():
        raise FileNotFoundError(reference_geotiff_path)
    if len(target_shape) != 2:
        raise ValueError("target_shape must have length 2")
    height, width = (int(target_shape[0]), int(target_shape[1]))
    if height <= 0 or width <= 0 or road_resolution_m <= 0 or road_dp_tolerance_m < 0:
        raise ValueError("road target shape/resolution/tolerance parameters are invalid")

    with rasterio.open(reference_geotiff_path) as ref:
        if ref.crs is None:
            raise ValueError(f"reference GeoTIFF has no CRS: {reference_geotiff_path}")
        ref_crs = ref.crs
        ref_bounds = ref.bounds
        ref_transform = ref.transform
        ref_raw_shape = (ref.height, ref.width)

    x_scale = width / (ref_bounds.right - ref_bounds.left)
    y_scale = height / (ref_bounds.top - ref_bounds.bottom)
    if x_scale <= 0 or y_scale <= 0:
        raise ValueError("reference GeoTIFF bounds are invalid")
    simplify_tolerance_grid = road_dp_tolerance_m * 0.5 * (x_scale + y_scale)

    raw = json.loads(osm_roads_path.read_text(encoding="utf-8"))
    transformer = Transformer.from_crs("EPSG:4326", ref_crs, always_xy=True)
    segments: list[list[float]] = []
    for feature in raw.get("features", []):
        geom = shape(feature.get("geometry"))
        for line in _iter_lines(geom):
            coords = np.asarray(line.coords, dtype=np.float64)
            lon = coords[:, 0]
            lat = coords[:, 1]
            ref_x, ref_y = transformer.transform(lon, lat)
            local_x = (np.asarray(ref_x) - ref_bounds.left) * x_scale
            local_y = (ref_bounds.top - np.asarray(ref_y)) * y_scale
            local = np.column_stack([local_x, local_y])
            simple = LineString(local).simplify(simplify_tolerance_grid, preserve_topology=False)
            coords = np.asarray(simple.coords, dtype=np.float64)
            for a, b in zip(coords[:-1], coords[1:]):
                if np.linalg.norm(b - a) > 1e-9:
                    segments.append([a[0], a[1], b[0], b[1]])
    if not segments:
        raise ValueError("no valid road segments found")
    road_segments_local = np.asarray(segments, dtype=np.float32)
    road_voronoi = _compute_segment_voronoi(road_segments_local, height, width, road_resolution_m, chunk_points)
    metadata = {
        "source_path": str(osm_roads_path),
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
        "shape": [height, width],
        "road_resolution_m": road_resolution_m,
        "road_dp_tolerance_m": road_dp_tolerance_m,
        "road_dp_tolerance_grid": float(simplify_tolerance_grid),
        "x_scale_grid_per_crs_unit": float(x_scale),
        "y_scale_grid_per_crs_unit": float(y_scale),
        "n_segments": int(len(road_segments_local)),
        "local_coord_convention": LOCAL_COORD_CONVENTION,
    }
    if output_segments_path is not None:
        output_segments_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_segments_path, road_segments_local)
        write_json(output_segments_path.with_suffix(".json"), metadata)
    if output_voronoi_path is not None:
        save_array_product(output_voronoi_path, road_voronoi, metadata)
    return road_segments_local, road_voronoi, metadata


def _compute_segment_voronoi(
    segments: np.ndarray,
    height: int,
    width: int,
    resolution_m: float,
    chunk_points: int,
) -> np.ndarray:
    if segments.ndim != 2 or segments.shape[1] != 4:
        raise ValueError("segments must have shape [N_seg, 4]")
    seg = segments.astype(np.float32)
    a = seg[:, 0:2]
    b = seg[:, 2:4]
    ab = b - a
    denom = np.sum(ab * ab, axis=1)
    if np.any(denom <= 0):
        raise ValueError("road segments contain zero-length segment")
    xs = (np.arange(width, dtype=np.float32) + 0.5) * resolution_m
    ys = (np.arange(height, dtype=np.float32) + 0.5) * resolution_m
    grid_x, grid_y = np.meshgrid(xs, ys)
    points = np.column_stack([grid_x.ravel(), grid_y.ravel()]).astype(np.float32)
    labels = np.empty(points.shape[0], dtype=np.int64)
    for start in range(0, points.shape[0], chunk_points):
        p = points[start : start + chunk_points]
        ap = p[:, None, :] - a[None, :, :]
        t = np.sum(ap * ab[None, :, :], axis=2) / denom[None, :]
        t = np.clip(t, 0.0, 1.0)
        proj = a[None, :, :] + t[:, :, None] * ab[None, :, :]
        diff = p[:, None, :] - proj
        dist2 = np.sum(diff * diff, axis=2)
        labels[start : start + len(p)] = np.argmin(dist2, axis=1)
    return labels.reshape(height, width)
