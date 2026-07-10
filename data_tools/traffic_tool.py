from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import LineString, MultiLineString, shape

from .io_utils import LOCAL_COORD_CONVENTION, save_array_product, write_json


def _transformer(center_lon: float, center_lat: float) -> Transformer:
    crs_local = CRS.from_proj4(
        f"+proj=aeqd +lat_0={center_lat} +lon_0={center_lon} +datum=WGS84 +units=m +no_defs"
    )
    return Transformer.from_crs("EPSG:4326", crs_local, always_xy=True)


def _iter_lines(geom):
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        yield from geom.geoms


def _coords_to_local(coords, transformer: Transformer, half_side_m: float) -> np.ndarray:
    lon = np.array([c[0] for c in coords], dtype=np.float64)
    lat = np.array([c[1] for c in coords], dtype=np.float64)
    east, north = transformer.transform(lon, lat)
    return np.column_stack([east + half_side_m, half_side_m - north])


def build_road_product(
    osm_roads_path: Path,
    output_segments_path: Path | None,
    output_voronoi_path: Path | None,
    center_lon: float,
    center_lat: float,
    half_side_m: float,
    road_dp_tolerance_m: float,
    road_resolution_m: float = 1.0,
    chunk_points: int = 8192,
) -> tuple[np.ndarray, np.ndarray, dict]:
    if not osm_roads_path.exists():
        raise FileNotFoundError(osm_roads_path)
    if half_side_m <= 0 or road_resolution_m <= 0 or road_dp_tolerance_m < 0:
        raise ValueError("road half side/resolution/tolerance parameters are invalid")
    raw = json.loads(osm_roads_path.read_text(encoding="utf-8"))
    transformer = _transformer(center_lon, center_lat)
    segments: list[list[float]] = []
    for feature in raw.get("features", []):
        geom = shape(feature.get("geometry"))
        for line in _iter_lines(geom):
            local = _coords_to_local(line.coords, transformer, half_side_m)
            simple = LineString(local).simplify(road_dp_tolerance_m, preserve_topology=False)
            coords = np.asarray(simple.coords, dtype=np.float64)
            for a, b in zip(coords[:-1], coords[1:]):
                if np.linalg.norm(b - a) > 1e-9:
                    segments.append([a[0], a[1], b[0], b[1]])
    if not segments:
        raise ValueError("no valid road segments found")
    road_segments_local = np.asarray(segments, dtype=np.float32)
    side = int(round(2.0 * half_side_m / road_resolution_m))
    road_voronoi = _compute_segment_voronoi(road_segments_local, side, side, road_resolution_m, chunk_points)
    metadata = {
        "source_path": str(osm_roads_path),
        "center_lon": center_lon,
        "center_lat": center_lat,
        "half_side_m": half_side_m,
        "shape": [side, side],
        "road_resolution_m": road_resolution_m,
        "road_dp_tolerance_m": road_dp_tolerance_m,
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
