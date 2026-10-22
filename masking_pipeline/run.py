#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPS coordinates to the four site-data files used by power-grid-site-modeling.

Stages: download, segment, downsample, osm, dem, export. ``all`` runs every
stage. ``osm`` and ``dem`` reuse an existing satellite GeoTIFF and do not run
Mask2Former. Official bundle files are published only after QA passes.

``radius_km`` is the half-side of a square in Web Mercator metres
(radius_km * 1000), not a geodesic radius.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Optional

try:
    from bundle import export_bundle, load_manifest, record_stage, stage_is_reusable, write_landuse_csv
    from dem import extract_dem
    from download import download_satellite_geotiff, lonlat_to_webmercator
    from downsample import downsample_routing_mask
    from geo_utils import file_signature
    from naming import (
        NamingError,
        assert_site_identity,
        build_site_id,
        build_site_paths,
        canonical_parameters,
        resolve_site_directory,
    )
    from osm import extract_osm_roads
    from render import build_palette, mask_to_rgb, save_legend_png
    from segment import run_segmentation
    from visualize import draw_alignment
except ImportError:
    from .bundle import export_bundle, load_manifest, record_stage, stage_is_reusable, write_landuse_csv
    from .dem import extract_dem
    from .download import download_satellite_geotiff, lonlat_to_webmercator
    from .downsample import downsample_routing_mask
    from .geo_utils import file_signature
    from .naming import (
        NamingError,
        assert_site_identity,
        build_site_id,
        build_site_paths,
        canonical_parameters,
        resolve_site_directory,
    )
    from .osm import extract_osm_roads
    from .render import build_palette, mask_to_rgb, save_legend_png
    from .segment import run_segmentation
    from .visualize import draw_alignment

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OSM_PBF = os.environ.get("MASKING_OSM_PBF") or os.path.join(
    SCRIPT_DIR, "data", "regional", "zhejiang-261020.osm.pbf"
)
DEFAULT_DEM = os.environ.get("MASKING_DEM_SOURCE") or os.path.join(SCRIPT_DIR, "data", "regional", "wenzhou.tif")
DEFAULT_OUTPUT_ROOT = os.environ.get("MASKING_OUTPUT_ROOT") or os.path.join(SCRIPT_DIR, "outputs")


def build_stem(lat: float, lon: float, radius_km: float, zoom: int, crop: bool = True) -> str:
    return (
        f"satellite_{lat:.6f}_{lon:.6f}_r{radius_km:.2f}km_z{zoom}"
        f"_{'crop' if crop else 'full'}"
    )


def default_output_dir(lat: float, lon: float, date: Optional[str] = None) -> str:
    """Legacy dated folder. Prefer ``--output-root``, which adds the site id."""
    date = date or datetime.now().strftime("%Y%m%d")
    return os.path.join(SCRIPT_DIR, f"outputs_lat{lat:.6f}_lon{lon:.6f}_{date}")


def render_fullres_class_map(coarse_npy: str, output_dir: str) -> dict:
    """Write full-resolution RGB class map + legend next to the coarse mask."""
    import numpy as np
    from pathlib import Path
    from PIL import Image

    npy_path = Path(coarse_npy)
    mask = np.load(str(npy_path), allow_pickle=True)
    if mask.ndim != 2:
        raise ValueError(f"Expected 2D mask, got shape {mask.shape}")
    rgb = mask_to_rgb(mask, build_palette())
    out_png = Path(output_dir) / f"{npy_path.stem}_class_map.png"
    leg_png = Path(output_dir) / f"{npy_path.stem}_class_map_legend.png"
    Image.fromarray(rgb, mode="RGB").save(out_png, compress_level=6)
    save_legend_png(leg_png)
    print(f"Wrote class map: {out_png}")
    print(f"Wrote legend:    {leg_png}")
    return {"class_map_png": str(out_png), "legend_png": str(leg_png)}


def _stage(name: str, fn):
    started = time.perf_counter()
    print(f"\n>>> [{name}] start")
    try:
        value = fn()
    except Exception:
        print(f">>> [{name}] FAILED after {time.perf_counter() - started:.1f}s")
        raise
    print(f">>> [{name}] done in {time.perf_counter() - started:.1f}s")
    return value


def _reuse(output_dir: str, resume: bool, stage: str, params: dict, files: list) -> bool:
    if not resume:
        return False
    ok, reason = stage_is_reusable(load_manifest(output_dir), stage, params, files)
    if ok:
        print(f"\n>>> [{stage}] reused existing output ({reason})")
        return True
    print(f"\n>>> [{stage}] cache rejected: {reason}")
    return False


def _require_complete_coverage(meta_json: str) -> None:
    if not os.path.isfile(meta_json):
        return
    with open(meta_json, "r", encoding="utf-8") as handle:
        meta = json.load(handle)
    if meta.get("coverage_complete") is False:
        raise RuntimeError(
            f"Satellite metadata says coverage is incomplete: {meta_json}. "
            "Refusing to segment placeholder imagery."
        )


def _satellite_matches(path: str, lat: float, lon: float, radius_km: float) -> bool:
    import rasterio

    with rasterio.open(path) as src:
        if src.crs is None or str(src.crs) != "EPSG:3857":
            return False
        cx, cy = lonlat_to_webmercator(lon, lat)
        bounds = src.bounds
        if abs((bounds.left + bounds.right) / 2.0 - cx) > 30.0:
            return False
        if abs((bounds.bottom + bounds.top) / 2.0 - cy) > 30.0:
            return False
        expected = radius_km * 2000.0
        if abs((bounds.right - bounds.left) - expected) > 40.0:
            return False
        if abs((bounds.top - bounds.bottom) - expected) > 40.0:
            return False
    return True


def _legacy_satellite_candidates(stem: str) -> list:
    return [
        os.path.join(SCRIPT_DIR, "outputs", "cangnan_test", "intermediates", f"{stem}_epsg3857.tif"),
        os.path.join(
            os.path.dirname(SCRIPT_DIR),
            "route_plan_v2",
            "image_process",
            "outputs_geotiff_GY_0409",
            f"{stem}_epsg3857.tif",
        ),
    ]


def _adopt_satellite(paths: dict, source: str, preview: Optional[str], note: str) -> None:
    os.makedirs(paths["cache_dir"], exist_ok=True)
    if os.path.abspath(source) != os.path.abspath(paths["cache_satellite"]):
        shutil.copy2(source, paths["cache_satellite"])
    if preview and os.path.isfile(preview):
        shutil.copy2(preview, paths["cache_satellite_preview"])
        shutil.copy2(preview, paths["satellite_preview"])
    with open(paths["cache_satellite_meta"], "w", encoding="utf-8") as handle:
        json.dump(
            {
                "coverage_complete": True,
                "reused_from": os.path.abspath(source),
                "note": note,
                "output_geotiff": paths["cache_satellite"],
            },
            handle,
            indent=2,
        )


def run_pipeline(
    lat: float,
    lon: float,
    radius_km: float = 0.9,
    zoom: int = 18,
    target_height: int = 1800,
    target_width: int = 1800,
    output_dir: Optional[str] = None,
    output_root: Optional[str] = None,
    site_name: Optional[str] = None,
    model: str = "mfaytin/mask2former-satellite",
    hf_endpoint: Optional[str] = "https://hf-mirror.com",
    step: str = "all",
    overwrite: bool = True,
    render_fullres: bool = True,
    osm_pbf: Optional[str] = None,
    dem_source: Optional[str] = None,
    road_buffer_m: float = 500,
    max_outside_m: float = 1500,
    resume: bool = False,
    allow_incomplete_tiles: bool = False,
    keep_intermediates: bool = False,
) -> dict:
    if step == "bundle":
        step = "export"
    params = canonical_parameters(
        lat, lon, radius_km, zoom, target_height, target_width, road_buffer_m, site_name
    )
    site_id = build_site_id(
        lat, lon, radius_km, zoom, target_height, target_width, road_buffer_m, site_name
    )
    site_dir, location_mode = resolve_site_directory(
        site_id,
        output_dir=output_dir,
        output_root=output_root,
        default_root=DEFAULT_OUTPUT_ROOT,
    )
    assert_site_identity(site_dir, site_id, params)
    paths = build_site_paths(site_id, site_dir=site_dir)
    os.makedirs(paths["cache_dir"], exist_ok=True)
    os.makedirs(paths["previews_dir"], exist_ok=True)
    osm_pbf = os.path.abspath(osm_pbf or DEFAULT_OSM_PBF)
    dem_source = os.path.abspath(dem_source or DEFAULT_DEM)
    run_every = step == "all"
    started_at = datetime.now(timezone.utc).isoformat()
    reused, computed = [], []
    results = {
        "site_id": site_id,
        "output_dir": site_dir,
        "location_mode": location_mode,
        "bundle_dir": paths["bundle_dir"],
        "previews_dir": paths["previews_dir"],
        "reused": reused,
        "computed": computed,
    }
    stem = build_stem(params["lat"], params["lon"], params["radius_km"], params["zoom"], crop=True)

    print("=" * 60)
    print("Site-data pipeline")
    print(f"  site_id:     {site_id}")
    print(f"  location:    {location_mode} {site_dir}")
    print(f"  lat/lon:     {params['lat_text']}, {params['lon_text']}")
    print(f"  radius_km:   {params['radius_text']}  (Web Mercator half-side {params['radius_km'] * 1000:.0f} m)")
    print(f"  zoom:        {params['zoom']}")
    print(f"  target grid: {params['target_height']} x {params['target_width']}")
    print(f"  step:        {step}")
    print(f"  osm_pbf:     {osm_pbf}")
    print(f"  dem_source:  {dem_source}")
    print(f"  road_buffer: {params['road_buffer_m']} m in the satellite CRS")
    print("=" * 60)

    download_params = {
        "site_id": site_id,
        "lat": params["lat"],
        "lon": params["lon"],
        "radius_km": params["radius_km"],
        "zoom": params["zoom"],
        "crop": True,
        "provider": "esri_world_imagery",
    }
    tif_path = paths["cache_satellite"]

    if run_every or step == "download":
        if _reuse(site_dir, resume, "download", download_params, [tif_path]):
            results["geotiff"] = tif_path
            reused.append("download")
        else:
            adopted = None
            for candidate in _legacy_satellite_candidates(stem):
                if os.path.isfile(candidate) and _satellite_matches(candidate, params["lat"], params["lon"], params["radius_km"]):
                    adopted = candidate
                    break
            if adopted:
                preview_candidates = [
                    adopted.replace("_epsg3857.tif", "_preview.png"),
                    os.path.join(os.path.dirname(os.path.dirname(adopted)), "previews", "satellite_preview.png"),
                    os.path.join(SCRIPT_DIR, "outputs", "cangnan_test", "previews", "satellite_preview.png"),
                ]
                preview = next((item for item in preview_candidates if os.path.isfile(item)), None)
                _adopt_satellite(paths, adopted, preview, "reused a satellite GeoTIFF whose CRS, center, and side match this request")
                record_stage(site_dir, "download", download_params, [tif_path])
                print(f"Reused satellite GeoTIFF: {adopted}")
                reused.append("satellite_geotiff")
                results["geotiff"] = tif_path
            else:
                def _download():
                    meta = download_satellite_geotiff(
                        center_lat=params["lat"],
                        center_lon=params["lon"],
                        radius_km=params["radius_km"],
                        zoom=params["zoom"],
                        output_dir=paths["cache_dir"],
                        crop_to_request=True,
                        save_preview=True,
                        overwrite=overwrite,
                        allow_incomplete=allow_incomplete_tiles,
                    )
                    if os.path.abspath(meta.output_geotiff) != os.path.abspath(tif_path):
                        shutil.copy2(meta.output_geotiff, tif_path)
                    if meta.output_preview_png and os.path.isfile(meta.output_preview_png):
                        shutil.copy2(meta.output_preview_png, paths["cache_satellite_preview"])
                        shutil.copy2(meta.output_preview_png, paths["satellite_preview"])
                    shutil.copy2(meta.output_metadata_json, paths["cache_satellite_meta"])
                    record_stage(site_dir, "download", download_params, [tif_path])
                    return meta
                _stage("download", _download)
                computed.append("download")
                results["geotiff"] = tif_path

    if not os.path.isfile(tif_path):
        if step in {"segment", "downsample", "osm", "dem", "export", "all"}:
            raise FileNotFoundError(
                f"Satellite reference GeoTIFF not found: {tif_path}. Run --step download first."
            )
    else:
        results["geotiff"] = tif_path
        if os.path.isfile(paths["cache_satellite_preview"]) and not os.path.isfile(paths["satellite_preview"]):
            shutil.copy2(paths["cache_satellite_preview"], paths["satellite_preview"])

    if run_every or step == "osm":
        osm_params = {
            **download_params,
            "road_buffer_m": params["road_buffer_m"],
            "max_outside_m": max_outside_m,
            "pbf": file_signature(osm_pbf),
            "reference": file_signature(tif_path),
        }
        if _reuse(site_dir, resume, "osm", osm_params, [paths["cache_osm"], paths["osm_preview"]]):
            results["osm_geojson"] = paths["cache_osm"]
            reused.append("osm")
        else:
            def _osm():
                summary = extract_osm_roads(
                    osm_pbf,
                    tif_path,
                    road_buffer_m=params["road_buffer_m"],
                    output_geojson_path=paths["cache_osm"],
                    preview_png_path=paths["osm_preview"],
                    max_outside_m=max_outside_m,
                )
                with open(paths["cache_osm_summary"], "w", encoding="utf-8") as handle:
                    json.dump(summary, handle, ensure_ascii=False, indent=2)
                record_stage(site_dir, "osm", osm_params, [paths["cache_osm"], paths["osm_preview"]])
                return summary
            results["osm_summary"] = _stage("osm", _osm)
            computed.append("osm")
            results["osm_geojson"] = paths["cache_osm"]
            results["osm_preview"] = paths["osm_preview"]

    if run_every or step == "dem":
        dem_params = {
            **download_params,
            "dem": file_signature(dem_source),
            "reference": file_signature(tif_path),
        }
        if _reuse(site_dir, resume, "dem", dem_params, [paths["cache_dem"], paths["dem_preview"]]):
            results["dem"] = paths["cache_dem"]
            reused.append("dem")
        else:
            def _dem():
                summary = extract_dem(
                    dem_source,
                    tif_path,
                    paths["cache_dem"],
                    preview_png_path=paths["dem_preview"],
                )
                with open(paths["cache_dem_summary"], "w", encoding="utf-8") as handle:
                    json.dump(summary, handle, ensure_ascii=False)
                record_stage(site_dir, "dem", dem_params, [paths["cache_dem"], paths["dem_preview"]])
                return summary
            results["dem_summary"] = _stage("dem", _dem)
            computed.append("dem")
            results["dem"] = paths["cache_dem"]
            results["dem_preview"] = paths["dem_preview"]

    if run_every or step == "segment":
        _require_complete_coverage(paths["cache_satellite_meta"])
        segment_params = {**download_params, "model": model, "reference": file_signature(tif_path)}
        if _reuse(site_dir, resume, "segment", segment_params, [paths["cache_coarse"]]):
            results["coarse_npy"] = paths["cache_coarse"]
            reused.append("segment")
        else:
            def _segment():
                seg = run_segmentation(
                    image=tif_path,
                    output_dir=paths["cache_dir"],
                    model=model,
                    hf_endpoint=hf_endpoint,
                )
                if os.path.abspath(seg["coarse_npy"]) != os.path.abspath(paths["cache_coarse"]):
                    shutil.copy2(seg["coarse_npy"], paths["cache_coarse"])
                if render_fullres:
                    render_fullres_class_map(paths["cache_coarse"], paths["cache_dir"])
                record_stage(site_dir, "segment", segment_params, [paths["cache_coarse"]])
                return seg
            results.update(_stage("segment", _segment))
            computed.append("segment")
            results["coarse_npy"] = paths["cache_coarse"]

    if run_every or step == "downsample":
        if not os.path.isfile(paths["cache_coarse"]):
            raise FileNotFoundError(f"Coarse mask not found: {paths['cache_coarse']}")
        down_params = {
            **download_params,
            "target_height": params["target_height"],
            "target_width": params["target_width"],
            "coarse": file_signature(paths["cache_coarse"]),
        }
        if _reuse(site_dir, resume, "downsample", down_params, [paths["cache_landuse_npy"], paths["cache_landuse_csv"]]):
            results["downsampled_npy"] = paths["cache_landuse_npy"]
            results["landuse_csv"] = paths["cache_landuse_csv"]
            reused.append("downsample")
        else:
            def _down():
                import numpy as np
                down = downsample_routing_mask(
                    coarse_npy=paths["cache_coarse"],
                    output_dir=paths["cache_dir"],
                    target_height=params["target_height"],
                    target_width=params["target_width"],
                    save_png=True,
                )
                shutil.copy2(down["downsampled_npy"], paths["cache_landuse_npy"])
                mask = np.load(paths["cache_landuse_npy"])
                write_landuse_csv(mask, paths["cache_landuse_csv"])
                if down.get("downsampled_png"):
                    shutil.copy2(down["downsampled_png"], paths["landuse_preview"])
                record_stage(site_dir, "downsample", down_params, [paths["cache_landuse_npy"], paths["cache_landuse_csv"]])
                down["landuse_csv"] = paths["cache_landuse_csv"]
                return down
            down = _stage("downsample", _down)
            computed.append("downsample")
            results.update(down)

    if run_every or step == "export":
        for required in (tif_path, paths["cache_landuse_csv"], paths["cache_osm"], paths["cache_dem"]):
            if not os.path.isfile(required):
                raise FileNotFoundError(f"Cannot publish the bundle; missing {required}")
        osm_summary = results.get("osm_summary")
        if osm_summary is None and os.path.isfile(paths["cache_osm_summary"]):
            with open(paths["cache_osm_summary"], "r", encoding="utf-8") as handle:
                osm_summary = json.load(handle)
        dem_summary = results.get("dem_summary")
        if dem_summary is None and os.path.isfile(paths["cache_dem_summary"]):
            with open(paths["cache_dem_summary"], "r", encoding="utf-8") as handle:
                dem_summary = json.load(handle)

        def _export():
            draw_alignment(
                tif_path,
                paths["cache_landuse_csv"],
                paths["cache_osm"],
                paths["cache_dem"],
                paths["alignment_preview"],
            )
            exported = export_bundle(
                site_dir,
                tif_path,
                paths["cache_landuse_csv"],
                paths["cache_osm"],
                paths["cache_dem"],
                run_params={
                    "site_name": params["site_name"],
                    "lat": params["lat"],
                    "lon": params["lon"],
                    "radius_km": params["radius_km"],
                    "zoom": params["zoom"],
                    "target_height": params["target_height"],
                    "target_width": params["target_width"],
                    "road_buffer_m": params["road_buffer_m"],
                    "max_outside_m": max_outside_m,
                    "model": model,
                    "osm_pbf": osm_pbf,
                    "dem_source": dem_source,
                    "step": step,
                    "center": {"lat": params["lat"], "lon": params["lon"]},
                },
                osm_summary=osm_summary,
                dem_summary=dem_summary,
                model=model,
                site_paths=paths,
                pipeline_started_at=started_at,
            )
            exported["alignment_check"] = paths["alignment_preview"]
            if exported["overall_status"] != "passed":
                raise RuntimeError("Bundle QA failed. See " + exported["qa_report"])
            if not keep_intermediates and os.path.isdir(paths["staging_dir"]):
                shutil.rmtree(paths["staging_dir"], ignore_errors=True)
            return exported
        results["export"] = _stage("export", _export)
        computed.append("export")

    print("\n=== done ===")
    print(f"  site_id          {site_id}")
    print(f"  reused           {', '.join(reused) or 'none'}")
    print(f"  computed         {', '.join(computed) or 'none'}")
    for key in ("geotiff", "osm_geojson", "osm_preview", "dem", "dem_preview", "coarse_npy", "landuse_csv"):
        if results.get(key):
            print(f"  {key:16s} {results[key]}")
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GPS coordinates to satellite, landuse, OSM roads, and DEM",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--site-name", type=str, default="site", help="ASCII scene name used in site_id")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius-km", type=float, default=0.9, help="Half-side of the square in Web Mercator km")
    parser.add_argument("--zoom", type=int, default=18)
    parser.add_argument("--target-height", type=int, default=1800)
    parser.add_argument("--target-width", type=int, default=1800)
    parser.add_argument("--output-root", type=str, default=None, help="Parent directory; the run writes <root>/<site_id>/")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Legacy exact output directory. Do not combine with --output-root.",
    )
    parser.add_argument("--model", type=str, default="mfaytin/mask2former-satellite")
    parser.add_argument("--hf-endpoint", type=str, default="https://hf-mirror.com")
    parser.add_argument(
        "--step",
        choices=["all", "download", "segment", "downsample", "osm", "dem", "export", "bundle"],
        default="all",
    )
    parser.add_argument("--osm-pbf", type=str, default=DEFAULT_OSM_PBF)
    parser.add_argument("--dem-source", type=str, default=DEFAULT_DEM)
    parser.add_argument("--road-buffer-m", type=float, default=500, help="Extra OSM extent in satellite CRS metres")
    parser.add_argument("--max-outside-m", type=float, default=1500)
    parser.add_argument("--resume", action="store_true", help="Reuse a stage only when its parameters and files match")
    parser.add_argument("--keep-intermediates", action="store_true", help="Keep the staging directory after a successful publish")
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--no-fullres-render", action="store_true")
    parser.add_argument("--allow-incomplete-tiles", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        run_pipeline(
            lat=args.lat,
            lon=args.lon,
            radius_km=args.radius_km,
            zoom=args.zoom,
            target_height=args.target_height,
            target_width=args.target_width,
            output_dir=args.output_dir,
            output_root=args.output_root,
            site_name=args.site_name,
            model=args.model,
            hf_endpoint=(args.hf_endpoint or "").strip() or None,
            step=args.step,
            overwrite=not args.no_overwrite,
            render_fullres=not args.no_fullres_render,
            osm_pbf=args.osm_pbf,
            dem_source=args.dem_source,
            road_buffer_m=args.road_buffer_m,
            max_outside_m=args.max_outside_m,
            resume=args.resume,
            allow_incomplete_tiles=args.allow_incomplete_tiles,
            keep_intermediates=args.keep_intermediates,
        )
    except NamingError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
