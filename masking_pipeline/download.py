#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download XYZ satellite tiles and save a georeferenced GeoTIFF for line-routing tasks.

Key improvements over a plain PNG mosaic:
1. Saves GeoTIFF with CRS and affine transform.
2. Works in native Web Mercator (EPSG:3857), matching XYZ tiles.
3. Optionally crops to the exact requested metric bbox around the center point.
4. Optionally exports a WGS84 GeoTIFF for easier GIS inspection.
5. Saves metadata JSON for downstream line-selection / cost-map building.

Default provider: ESRI World Imagery
    https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}

Example:
python download_satellite_geotiff.py \
  --center-lat 27.408944 \
  --center-lon 120.537999 \
  --radius-km 2 \
  --zoom 18 \
  --output-dir outputs_geotiff \
  --also-save-wgs84
"""
from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests
from PIL import Image

try:
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    HAS_RASTERIO = True
except Exception:
    HAS_RASTERIO = False

# Optional, but convenient for tile enumeration
try:
    import mercantile
    HAS_MERCANTILE = True
except Exception:
    HAS_MERCANTILE = False

WEB_MERCATOR_HALF_WORLD = 20037508.342789244
TILE_SIZE = 256


@dataclass
class TileDownloadResult:
    ix: int
    iy: int
    ok: bool
    error: Optional[str] = None


@dataclass
class OutputMetadata:
    center_lat: float
    center_lon: float
    radius_km: float
    zoom: int
    provider: str
    requested_bbox_lonlat: List[float]
    requested_bbox_3857: List[float]
    tile_range_xyz: Dict[str, int]
    full_tile_extent_3857: List[float]
    cropped_extent_3857: List[float]
    cropped_extent_lonlat: List[float]
    pixel_size_m: float
    width: int
    height: int
    crs: str
    output_geotiff: str
    output_preview_png: str
    output_metadata_json: str
    output_geotiff_wgs84: Optional[str] = None
    tiles_requested: int = 0
    tiles_succeeded: int = 0
    failed_tiles: Optional[List[Dict]] = None
    coverage_complete: bool = True


def enforce_tile_coverage(requested: int, succeeded: int, failed: List[Dict], allow_incomplete: bool) -> None:
    """Refuse a mosaic that still contains placeholder pixels for failed tiles."""
    if requested <= 0:
        raise RuntimeError("No satellite tiles were requested.")
    if succeeded <= 0:
        raise RuntimeError("Failed to download all tiles; zero valid tiles received.")
    if failed and not allow_incomplete:
        sample = "; ".join(
            f"z{item.get('z')}/{item.get('x')}/{item.get('y')}: {item.get('error')}"
            for item in failed[:8]
        )
        raise RuntimeError(
            f"Incomplete satellite coverage: {len(failed)}/{requested} tiles failed. "
            "Refusing to build a GeoTIFF that still contains placeholder pixels. "
            f"{sample}"
        )


def lonlat_to_webmercator(lon: float, lat: float) -> Tuple[float, float]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = WEB_MERCATOR_HALF_WORLD * lon / 180.0
    y = WEB_MERCATOR_HALF_WORLD * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)) / math.pi
    return x, y



def webmercator_to_lonlat(x: float, y: float) -> Tuple[float, float]:
    lon = (x / WEB_MERCATOR_HALF_WORLD) * 180.0
    lat = math.degrees(2.0 * math.atan(math.exp((y / WEB_MERCATOR_HALF_WORLD) * math.pi)) - math.pi / 2.0)
    return lon, lat



def tile_xy_from_lonlat(lon: float, lat: float, zoom: int) -> Tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(max(min(lat, 85.05112878), -85.05112878))
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y



def tile_bounds_3857(x: int, y: int, z: int) -> Tuple[float, float, float, float]:
    """Return tile bounds in EPSG:3857 as (left, bottom, right, top)."""
    n = 2 ** z
    tile_span = 2 * WEB_MERCATOR_HALF_WORLD / n
    left = -WEB_MERCATOR_HALF_WORLD + x * tile_span
    right = left + tile_span
    top = WEB_MERCATOR_HALF_WORLD - y * tile_span
    bottom = top - tile_span
    return left, bottom, right, top



def tiles_for_bbox(west: float, south: float, east: float, north: float, zoom: int) -> Tuple[int, int, int, int]:
    if HAS_MERCANTILE:
        tiles = list(mercantile.tiles(west, south, east, north, zoom))
        if not tiles:
            raise RuntimeError("No tiles found for the requested bbox.")
        xs = [t.x for t in tiles]
        ys = [t.y for t in tiles]
        return min(xs), max(xs), min(ys), max(ys)

    x0, y1 = tile_xy_from_lonlat(west, south, zoom)
    x1, y0 = tile_xy_from_lonlat(east, north, zoom)
    return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download XYZ imagery and save GeoTIFF.")
    parser.add_argument("--center-lat", type=float, required=True, help="Center latitude in decimal degrees.")
    parser.add_argument("--center-lon", type=float, required=True, help="Center longitude in decimal degrees.")
    parser.add_argument("--radius-km", type=float, default=0.9, help="Half-size of square bbox in km.")
    parser.add_argument("--zoom", type=int, default=18, help="XYZ zoom level.")
    parser.add_argument(
        "--provider",
        type=str,
        default="esri_world_imagery",
        choices=["esri_world_imagery"],
        help="Tile provider preset.",
    )
    parser.add_argument(
        "--url-template",
        type=str,
        default="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        help="XYZ URL template. Must contain {z}, {x}, {y}.",
    )
    parser.add_argument("--output-dir", type=str, default="outputs_geotiff_GY_0409", help="Output directory.")
    parser.add_argument("--max-workers", type=int, default=8, help="Concurrent download workers.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-tile HTTP timeout in seconds.")
    parser.add_argument("--crop-to-request", action="store_true", help="Crop output to requested metric bbox.")
    parser.add_argument("--also-save-wgs84", action="store_true", help="Also save a WGS84 GeoTIFF copy.")
    parser.add_argument("--save-preview", action="store_true", help="Also save a PNG preview.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    return parser.parse_args()



def make_session() -> requests.Session:
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=3)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "GeoTIFFTileDownloader/1.0 (research)"})
    return session



def download_one_tile(
    session: requests.Session,
    url_template: str,
    z: int,
    x: int,
    y: int,
    ix: int,
    iy: int,
    timeout: float,
) -> Tuple[TileDownloadResult, Optional[np.ndarray]]:
    url = url_template.format(z=z, x=x, y=y)
    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        arr = np.asarray(img, dtype=np.uint8)
        return TileDownloadResult(ix=ix, iy=iy, ok=True), arr
    except Exception as e:
        return TileDownloadResult(ix=ix, iy=iy, ok=False, error=str(e)), None



def save_geotiff(path: str, rgb: np.ndarray, transform, crs: str) -> None:
    if not HAS_RASTERIO:
        raise RuntimeError("rasterio is required to save GeoTIFF. Please install rasterio.")

    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"Expected RGB array [H, W, 3], got shape={rgb.shape}")

    h, w, _ = rgb.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=3,
        dtype=np.uint8,
        crs=crs,
        transform=transform,
        tiled=True,
        compress="deflate",
        predictor=2,
        interleave="pixel",
        blockxsize=256,
        blockysize=256,
        BIGTIFF="IF_SAFER",
    ) as dst:
        for b in range(3):
            dst.write(rgb[:, :, b], b + 1)



def reproject_to_wgs84(src_path: str, dst_path: str) -> None:
    if not HAS_RASTERIO:
        raise RuntimeError("rasterio is required to reproject GeoTIFF.")

    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, "EPSG:4326", src.width, src.height, *src.bounds
        )
        kwargs = src.meta.copy()
        kwargs.update({
            "crs": "EPSG:4326",
            "transform": transform,
            "width": width,
            "height": height,
            "compress": "deflate",
            "predictor": 2,
        })
        with rasterio.open(dst_path, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs="EPSG:4326",
                    resampling=Resampling.bilinear,
                )



def download_satellite_geotiff(
    center_lat: float,
    center_lon: float,
    radius_km: float = 0.9,
    zoom: int = 18,
    output_dir: str = "outputs",
    provider: str = "esri_world_imagery",
    url_template: str = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    max_workers: int = 8,
    timeout: float = 20.0,
    crop_to_request: bool = True,
    also_save_wgs84: bool = False,
    save_preview: bool = True,
    overwrite: bool = True,
    allow_incomplete: bool = False,
) -> OutputMetadata:
    """Download XYZ satellite tiles around (center_lat, center_lon) and save GeoTIFF."""
    if not HAS_RASTERIO:
        raise RuntimeError("rasterio is required. Please install it first: pip install rasterio")

    os.makedirs(output_dir, exist_ok=True)

    center_x, center_y = lonlat_to_webmercator(center_lon, center_lat)
    radius_m = radius_km * 1000.0
    req_left = center_x - radius_m
    req_right = center_x + radius_m
    req_bottom = center_y - radius_m
    req_top = center_y + radius_m

    req_west, req_south = webmercator_to_lonlat(req_left, req_bottom)
    req_east, req_north = webmercator_to_lonlat(req_right, req_top)

    x_min, x_max, y_min, y_max = tiles_for_bbox(req_west, req_south, req_east, req_north, zoom)
    nx = x_max - x_min + 1
    ny = y_max - y_min + 1

    first_left, _, _, first_top = tile_bounds_3857(x_min, y_min, zoom)
    _, last_bottom, last_right, _ = tile_bounds_3857(x_max, y_max, zoom)
    full_left, full_bottom, full_right, full_top = first_left, last_bottom, last_right, first_top

    n = 2 ** zoom
    tile_span_m = 2 * WEB_MERCATOR_HALF_WORLD / n
    px_size = tile_span_m / TILE_SIZE

    full_h = ny * TILE_SIZE
    full_w = nx * TILE_SIZE
    mosaic = np.full((full_h, full_w, 3), 128, dtype=np.uint8)

    print(f"Requested bbox lon/lat: [{req_west:.6f}, {req_south:.6f}, {req_east:.6f}, {req_north:.6f}]")
    print(f"Tile range z={zoom}: x=[{x_min},{x_max}], y=[{y_min},{y_max}], count={nx * ny}")
    print(f"Full mosaic size: {full_w} x {full_h} px, pixel size ≈ {px_size:.4f} m")

    tasks: List[Tuple[int, int, int, int]] = []
    for iy in range(ny):
        for ix in range(nx):
            tasks.append((x_min + ix, y_min + iy, ix, iy))

    ok = 0
    failed: List[Dict] = []
    session = make_session()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(download_one_tile, session, url_template, zoom, x, y, ix, iy, timeout): (x, y, ix, iy)
            for (x, y, ix, iy) in tasks
        }
        for i, fut in enumerate(as_completed(futures), start=1):
            x, y, _ix, _iy = futures[fut]
            result, arr = fut.result()
            if result.ok and arr is not None:
                r0 = result.iy * TILE_SIZE
                c0 = result.ix * TILE_SIZE
                mosaic[r0:r0 + TILE_SIZE, c0:c0 + TILE_SIZE] = arr
                ok += 1
            else:
                failed.append({"z": zoom, "x": int(x), "y": int(y), "error": result.error})
            if i % 50 == 0 or i == len(tasks):
                print(f"  downloaded {i}/{len(tasks)} tiles, success={ok}, failed={len(failed)}")

    if failed and not allow_incomplete:
        failure_path = os.path.join(output_dir, "tile_failures.json")
        with open(failure_path, "w", encoding="utf-8") as handle:
            json.dump({"requested": len(tasks), "succeeded": ok, "failed_tiles": failed}, handle, indent=2)
        print(f"Wrote tile failure report: {failure_path}")
    enforce_tile_coverage(len(tasks), ok, failed, allow_incomplete)

    if crop_to_request:
        col0 = max(0, int(math.floor((req_left - full_left) / px_size)))
        col1 = min(full_w, int(math.ceil((req_right - full_left) / px_size)))
        row0 = max(0, int(math.floor((full_top - req_top) / px_size)))
        row1 = min(full_h, int(math.ceil((full_top - req_bottom) / px_size)))
    else:
        row0, row1, col0, col1 = 0, full_h, 0, full_w

    cropped = mosaic[row0:row1, col0:col1].copy()
    crop_left = full_left + col0 * px_size
    crop_top = full_top - row0 * px_size
    crop_right = full_left + col1 * px_size
    crop_bottom = full_top - row1 * px_size
    crop_transform = from_origin(crop_left, crop_top, px_size, px_size)

    crop_west, crop_south = webmercator_to_lonlat(crop_left, crop_bottom)
    crop_east, crop_north = webmercator_to_lonlat(crop_right, crop_top)

    stem = (
        f"satellite_{center_lat:.6f}_{center_lon:.6f}_r{radius_km:.2f}km_z{zoom}"
        f"_{'crop' if crop_to_request else 'full'}"
    )
    tif_path = os.path.join(output_dir, stem + "_epsg3857.tif")
    png_path = os.path.join(output_dir, stem + "_preview.png")
    json_path = os.path.join(output_dir, stem + "_meta.json")
    tif_wgs84_path = os.path.join(output_dir, stem + "_epsg4326.tif") if also_save_wgs84 else None

    for p in [tif_path, png_path, json_path, tif_wgs84_path]:
        if p and os.path.exists(p) and not overwrite:
            raise FileExistsError(f"Output already exists: {p}. Use overwrite=True to replace it.")

    save_geotiff(tif_path, cropped, crop_transform, "EPSG:3857")
    if save_preview:
        Image.fromarray(cropped).save(png_path)
    else:
        png_path = ""

    if also_save_wgs84 and tif_wgs84_path is not None:
        reproject_to_wgs84(tif_path, tif_wgs84_path)

    meta = OutputMetadata(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_km=radius_km,
        zoom=zoom,
        provider=provider,
        requested_bbox_lonlat=[req_west, req_south, req_east, req_north],
        requested_bbox_3857=[req_left, req_bottom, req_right, req_top],
        tile_range_xyz={"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max},
        full_tile_extent_3857=[full_left, full_bottom, full_right, full_top],
        cropped_extent_3857=[crop_left, crop_bottom, crop_right, crop_top],
        cropped_extent_lonlat=[crop_west, crop_south, crop_east, crop_north],
        pixel_size_m=px_size,
        width=cropped.shape[1],
        height=cropped.shape[0],
        crs="EPSG:3857",
        output_geotiff=tif_path,
        output_preview_png=png_path,
        output_metadata_json=json_path,
        output_geotiff_wgs84=tif_wgs84_path,
        tiles_requested=len(tasks),
        tiles_succeeded=ok,
        failed_tiles=failed,
        coverage_complete=not failed,
    )
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(asdict(meta), f, ensure_ascii=False, indent=2)

    print("\nDone.")
    print(f"GeoTIFF (EPSG:3857): {tif_path}")
    if tif_wgs84_path:
        print(f"GeoTIFF (EPSG:4326): {tif_wgs84_path}")
    if png_path:
        print(f"Preview PNG: {png_path}")
    print(f"Metadata JSON: {json_path}")
    print(f"Crop extent lon/lat: [{crop_west:.6f}, {crop_south:.6f}, {crop_east:.6f}, {crop_north:.6f}]")
    print(f"Output size: {cropped.shape[1]} x {cropped.shape[0]} px")
    print(f"Approx pixel size: {px_size:.4f} m")
    return meta


def main() -> None:
    args = parse_args()
    download_satellite_geotiff(
        center_lat=args.center_lat,
        center_lon=args.center_lon,
        radius_km=args.radius_km,
        zoom=args.zoom,
        output_dir=args.output_dir,
        provider=args.provider,
        url_template=args.url_template,
        max_workers=args.max_workers,
        timeout=args.timeout,
        crop_to_request=args.crop_to_request,
        also_save_wgs84=args.also_save_wgs84,
        save_preview=args.save_preview,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
