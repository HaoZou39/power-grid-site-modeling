from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from pyproj import Transformer
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject
from shapely.geometry import LineString, shape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.project_config import load_project_config
from data_tools.io_utils import write_json
from data_tools.landuse_tool import build_landuse_product
from data_tools.traffic_tool import _iter_lines


def auto_satellite_path() -> Path | None:
    candidates = sorted(Path("data").glob("satellite_*epsg3857.tif"))
    return candidates[0] if candidates else None


def reference_grid_from_geotiff(path: Path, target_shape: tuple[int, int]):
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError(f"reference GeoTIFF has no CRS: {path}")
        bounds = src.bounds
        height, width = target_shape
        target_transform = from_bounds(bounds.left, bounds.bottom, bounds.right, bounds.top, width, height)
        metadata = {
            "reference_path": str(path),
            "reference_crs": str(src.crs),
            "reference_bounds": {
                "left": float(bounds.left),
                "right": float(bounds.right),
                "bottom": float(bounds.bottom),
                "top": float(bounds.top),
            },
            "reference_transform": list(src.transform)[:6],
            "reference_raw_shape": [src.height, src.width],
            "target_shape": [height, width],
            "target_transform": list(target_transform)[:6],
        }
        return src.crs, bounds, target_transform, metadata


def read_rgb_on_primary_grid(path: Path, target_shape: tuple[int, int]) -> tuple[np.ndarray, dict]:
    dst_crs, _, dst_transform, metadata = reference_grid_from_geotiff(path, target_shape)
    with rasterio.open(path) as src:
        height, width = target_shape
        image = np.zeros((height, width, 3), dtype=np.float32)
        source_indexes = (1, 2, 3) if src.count >= 3 else (1, 1, 1)
        for out_idx, src_idx in enumerate(source_indexes):
            reproject(
                source=rasterio.band(src, src_idx),
                destination=image[:, :, out_idx],
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
            )
    lo = np.nanpercentile(image, 2)
    hi = np.nanpercentile(image, 98)
    if hi <= lo:
        raise ValueError(f"cannot normalize satellite image {path}")
    return np.clip((image - lo) / (hi - lo), 0.0, 1.0), metadata


def read_dem_on_primary_grid(dem_path: Path, reference_geotiff_path: Path, target_shape: tuple[int, int]) -> tuple[np.ndarray, dict]:
    dst_crs, _, dst_transform, reference_metadata = reference_grid_from_geotiff(reference_geotiff_path, target_shape)
    dem = np.zeros(target_shape, dtype=np.float32)
    with rasterio.open(dem_path) as src:
        if src.crs is None:
            raise ValueError(f"DEM GeoTIFF has no CRS: {dem_path}")
        reproject(
            source=rasterio.band(src, 1),
            destination=dem,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )
    if not np.isfinite(dem).all():
        raise ValueError("DEM contains NaN or Inf")
    metadata = {
        "method": "dem_reprojected_to_satellite_reference_bounds_and_primary_grid",
        "dem_path": str(dem_path),
        "reference_grid": reference_metadata,
    }
    return dem, metadata


def build_geotiff_aligned_road_segments(
    osm_roads_path: Path,
    satellite_path: Path,
    target_shape: tuple[int, int],
    road_dp_tolerance_m: float,
) -> tuple[np.ndarray, dict]:
    raw = json.loads(osm_roads_path.read_text(encoding="utf-8"))
    with rasterio.open(satellite_path) as src:
        if src.crs is None:
            raise ValueError(f"satellite GeoTIFF has no CRS: {satellite_path}")
        crs = src.crs
        bounds = src.bounds
        transform = src.transform
        raw_shape = (src.height, src.width)

    height, width = target_shape
    x_scale = width / (bounds.right - bounds.left)
    y_scale = height / (bounds.top - bounds.bottom)
    tolerance_grid = road_dp_tolerance_m * 0.5 * (x_scale + y_scale)
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    segments: list[list[float]] = []
    for feature in raw.get("features", []):
        geom = shape(feature.get("geometry"))
        for line in _iter_lines(geom):
            coords = np.asarray(line.coords, dtype=np.float64)
            lon = coords[:, 0]
            lat = coords[:, 1]
            map_x, map_y = transformer.transform(lon, lat)
            local_x = (np.asarray(map_x) - bounds.left) * x_scale
            local_y = (bounds.top - np.asarray(map_y)) * y_scale
            local = np.column_stack([local_x, local_y])
            simple = LineString(local).simplify(tolerance_grid, preserve_topology=False)
            simple_coords = np.asarray(simple.coords, dtype=np.float64)
            for a, b in zip(simple_coords[:-1], simple_coords[1:]):
                if np.linalg.norm(b - a) > 1e-9:
                    segments.append([a[0], a[1], b[0], b[1]])

    if not segments:
        raise ValueError("no valid GeoTIFF-aligned OSM road segments found")

    metadata = {
        "method": "osm_epsg4326_to_geotiff_crs_then_bounds_to_target_grid",
        "satellite_crs": str(crs),
        "satellite_bounds": {
            "left": float(bounds.left),
            "right": float(bounds.right),
            "bottom": float(bounds.bottom),
            "top": float(bounds.top),
        },
        "satellite_transform": list(transform)[:6],
        "satellite_raw_shape": list(raw_shape),
        "target_shape": list(target_shape),
        "x_scale_grid_per_crs_unit": float(x_scale),
        "y_scale_grid_per_crs_unit": float(y_scale),
        "road_dp_tolerance_grid": float(tolerance_grid),
    }
    return np.asarray(segments, dtype=np.float32), metadata


def plot_roads(ax, road_segments: np.ndarray, color: str = "#00ffff", linewidth: float = 0.65) -> None:
    for x1, y1, x2, y2 in road_segments:
        ax.plot([float(x1), float(x2)], [float(y1), float(y2)], color=color, linewidth=linewidth, alpha=0.9, zorder=5)


def setup_axis(ax, shape_: tuple[int, int], title: str) -> None:
    h, w = shape_
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.set_aspect("equal")
    ax.set_title(title)
    ax.set_xlabel("x local (m)")
    ax.set_ylabel("y local (m)")


def dem_display_limits(dem: np.ndarray) -> tuple[float, float]:
    lo, hi = np.nanpercentile(dem, [2, 98])
    if hi <= lo:
        raise ValueError("cannot normalize DEM display range")
    return float(lo), float(hi)


def landuse_colormap() -> tuple[ListedColormap, list[Patch]]:
    colors = [
        "#7f7f7f",  # 0 other
        "#ffd92f",  # 1 field
        "#8c510a",  # 2 building
        "#e31a1c",  # 3 road
        "#1a9850",  # 4 mountain/natural
        "#2c7fb8",  # 5 water
    ]
    labels = [
        "0 other",
        "1 field",
        "2 building",
        "3 road",
        "4 mountain/natural",
        "5 water",
    ]
    return ListedColormap(colors), [Patch(facecolor=c, edgecolor="none", label=l) for c, l in zip(colors, labels)]


def save_satellite_obstacle_roads(out: Path, satellite: np.ndarray, obstacle_mask: np.ndarray, road_segments: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(satellite, origin="upper")
    ax.imshow(np.ma.masked_where(obstacle_mask <= 0, obstacle_mask), cmap="Reds", alpha=0.34, origin="upper")
    plot_roads(ax, road_segments)
    setup_axis(ax, obstacle_mask.shape, "Satellite + non-buildable mask + simplified OSM roads")
    fig.tight_layout()
    fig.savefig(out / "satellite_obstacle_osm_roads_overlay.png", dpi=220)
    plt.close(fig)


def save_satellite_landuse_mask_roads(out: Path, satellite: np.ndarray, landuse: np.ndarray, road_segments: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(9, 9))
    cmap, legend_handles = landuse_colormap()
    ax.imshow(satellite, origin="upper")
    ax.imshow(landuse, cmap=cmap, vmin=-0.5, vmax=5.5, alpha=0.52, origin="upper", interpolation="nearest")
    plot_roads(ax, road_segments)
    ax.legend(handles=legend_handles, loc="lower right", fontsize=7, framealpha=0.82)
    setup_axis(ax, landuse.shape, "Satellite + full landuse mask + simplified OSM roads")
    fig.tight_layout()
    fig.savefig(out / "satellite_landuse_mask_osm_roads_overlay.png", dpi=220)
    plt.close(fig)


def save_satellite_landuse_mask_roads_geotiff_bounds(
    out: Path,
    satellite: np.ndarray,
    landuse: np.ndarray,
    road_segments: np.ndarray,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 9))
    cmap, legend_handles = landuse_colormap()
    ax.imshow(satellite, origin="upper")
    ax.imshow(landuse, cmap=cmap, vmin=-0.5, vmax=5.5, alpha=0.52, origin="upper", interpolation="nearest")
    plot_roads(ax, road_segments, color="#00e5ff", linewidth=0.75)
    ax.legend(handles=legend_handles, loc="lower right", fontsize=7, framealpha=0.82)
    setup_axis(ax, landuse.shape, "Satellite + full landuse mask + OSM roads from GeoTIFF bounds")
    fig.tight_layout()
    fig.savefig(out / "satellite_landuse_mask_osm_roads_geotiff_bounds_overlay.png", dpi=220)
    plt.close(fig)


def save_satellite_roadclass_roads(out: Path, satellite: np.ndarray, landuse: np.ndarray, road_segments: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(satellite, origin="upper")
    ax.imshow(np.ma.masked_where(landuse != 3, landuse == 3), cmap="autumn", alpha=0.42, origin="upper")
    plot_roads(ax, road_segments)
    setup_axis(ax, landuse.shape, "Satellite + landuse road class + simplified OSM roads")
    fig.tight_layout()
    fig.savefig(out / "satellite_landuse_road_osm_roads_overlay.png", dpi=220)
    plt.close(fig)


def save_satellite_roadclass_roads_geotiff_bounds(
    out: Path,
    satellite: np.ndarray,
    landuse: np.ndarray,
    road_segments: np.ndarray,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(satellite, origin="upper")
    ax.imshow(np.ma.masked_where(landuse != 3, landuse == 3), cmap="autumn", alpha=0.42, origin="upper")
    plot_roads(ax, road_segments, color="#00e5ff", linewidth=0.75)
    setup_axis(ax, landuse.shape, "Satellite + landuse road class + OSM roads from GeoTIFF bounds")
    fig.tight_layout()
    fig.savefig(out / "satellite_landuse_road_osm_roads_geotiff_bounds_overlay.png", dpi=220)
    plt.close(fig)


def save_satellite_dem_overlay(out: Path, satellite: np.ndarray, dem: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(satellite, origin="upper")
    vmin, vmax = dem_display_limits(dem)
    dem_mask = np.ma.masked_invalid(dem)
    overlay = ax.imshow(dem_mask, cmap="terrain", alpha=0.68, origin="upper", vmin=vmin, vmax=vmax)
    fig.colorbar(overlay, ax=ax, fraction=0.035, pad=0.02, label="DEM elevation")
    setup_axis(ax, dem.shape, "Satellite + DEM overlay")
    fig.tight_layout()
    fig.savefig(out / "satellite_dem_overlay.png", dpi=220)
    plt.close(fig)


def save_satellite_dem_obstacle_roads(
    out: Path,
    satellite: np.ndarray,
    dem: np.ndarray,
    obstacle_mask: np.ndarray,
    road_segments: np.ndarray,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(satellite, origin="upper")
    vmin, vmax = dem_display_limits(dem)
    overlay = ax.imshow(dem, cmap="terrain", alpha=0.52, origin="upper", vmin=vmin, vmax=vmax)
    ax.imshow(np.ma.masked_where(obstacle_mask <= 0, obstacle_mask), cmap="Reds", alpha=0.36, origin="upper")
    plot_roads(ax, road_segments)
    fig.colorbar(overlay, ax=ax, fraction=0.035, pad=0.02, label="DEM elevation")
    setup_axis(ax, obstacle_mask.shape, "Satellite + DEM + non-buildable mask + simplified OSM roads")
    fig.tight_layout()
    fig.savefig(out / "satellite_dem_obstacle_osm_roads_overlay.png", dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw satellite/segmentation/DEM/OSM-road alignment diagnostics.")
    parser.add_argument("--config", default="config/default_config.json")
    parser.add_argument("--output-dir", default="outputs/road_alignment_diagnostic")
    parser.add_argument("--satellite-image", default=None, help="Optional satellite RGB/GeoTIFF image path.")
    args = parser.parse_args()

    config = load_project_config(args.config)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    satellite_path = Path(args.satellite_image) if args.satellite_image else auto_satellite_path()
    if satellite_path is None:
        raise FileNotFoundError("No satellite image found. Pass --satellite-image path/to/image.tif")

    landuse, obstacle_mask, landuse_meta = build_landuse_product(
        config.data.landuse_path,
        config.data.obstacle_classes,
        expected_shape=None,
        output_landuse_path=None,
        output_obstacle_path=None,
        landuse_input_resolution_m=config.data.landuse_input_resolution_m,
        target_resolution_m=config.data.target_resolution_m,
    )
    satellite, satellite_grid_meta = read_rgb_on_primary_grid(satellite_path, landuse.shape)
    dem, dem_grid_meta = read_dem_on_primary_grid(
        config.data.dem_path,
        satellite_path,
        landuse.shape,
    )
    road_segments, geotiff_road_meta = build_geotiff_aligned_road_segments(
        config.data.osm_roads_path,
        satellite_path,
        landuse.shape,
        config.data.road_dp_tolerance_m,
    )

    save_satellite_obstacle_roads(out, satellite, obstacle_mask, road_segments)
    save_satellite_landuse_mask_roads(out, satellite, landuse, road_segments)
    save_satellite_landuse_mask_roads_geotiff_bounds(out, satellite, landuse, road_segments)
    save_satellite_roadclass_roads(out, satellite, landuse, road_segments)
    save_satellite_roadclass_roads_geotiff_bounds(out, satellite, landuse, road_segments)
    save_satellite_dem_overlay(out, satellite, dem)
    save_satellite_dem_obstacle_roads(out, satellite, dem, obstacle_mask, road_segments)

    write_json(
        out / "road_alignment_diagnostic_summary.json",
        {
            "satellite_image": str(satellite_path),
            "landuse_source": landuse_meta["source_path"],
            "dem_path": str(config.data.dem_path),
            "osm_roads_path": str(config.data.osm_roads_path),
            "landuse_shape": list(landuse.shape),
            "satellite_raw_shape": satellite_grid_meta["reference_raw_shape"],
            "satellite_plot_shape": list(satellite.shape[:2]),
            "n_geotiff_aligned_road_segments": int(len(road_segments)),
            "primary_grid_alignment": {
                "space_basis": "landuse_obstacle_primary_grid",
                "primary_grid_shape": list(landuse.shape),
                "satellite_grid": satellite_grid_meta,
                "dem_grid": dem_grid_meta,
            },
            "geotiff_road_alignment": geotiff_road_meta,
            "outputs": [
                "satellite_obstacle_osm_roads_overlay.png",
                "satellite_landuse_mask_osm_roads_overlay.png",
                "satellite_landuse_mask_osm_roads_geotiff_bounds_overlay.png",
                "satellite_landuse_road_osm_roads_overlay.png",
                "satellite_landuse_road_osm_roads_geotiff_bounds_overlay.png",
                "satellite_dem_overlay.png",
                "satellite_dem_obstacle_osm_roads_overlay.png",
            ],
        },
    )
    print(f"road alignment diagnostic outputs: {out}")


if __name__ == "__main__":
    main()
