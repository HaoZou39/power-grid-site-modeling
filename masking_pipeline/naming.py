#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One place for site ids, file names, and output directories."""
from __future__ import annotations

import json
import os
import re
from typing import Optional

_SITE_NAME = re.compile(r"^[0-9A-Za-z\u4e00-\u9fff][0-9A-Za-z\u4e00-\u9fff_-]{0,40}$")


class NamingError(ValueError):
    """A site id would be ambiguous or illegal."""


def validate_site_name(site_name: Optional[str]) -> str:
    if site_name is None or str(site_name).strip() == "":
        return "site"
    name = str(site_name).strip()
    if not _SITE_NAME.fullmatch(name):
        raise NamingError(
            f"site_name {site_name!r} must be Chinese or ASCII letters, digits, underscore, or hyphen"
        )
    return name


def _fixed(value: float, decimals: int, label: str) -> str:
    number = float(value)
    text = f"{number:.{decimals}f}"
    if abs(float(text) - number) > 10 ** (-(decimals + 2)):
        raise NamingError(
            f"{label}={value} has more precision than the {decimals} digits stored in site_id "
            f"(it would be written as {text}). Pass a value that already matches that precision "
            "so two different scenes cannot collapse to one directory."
        )
    return text


def _whole_number(value, label: str) -> int:
    number = float(value)
    if abs(number - round(number)) > 1e-9:
        raise NamingError(f"{label}={value} must be a whole number")
    parsed = int(round(number))
    if parsed < 0:
        raise NamingError(f"{label} must be >= 0")
    return parsed


def canonical_parameters(
    lat: float,
    lon: float,
    radius_km: float,
    zoom: int,
    target_height: int,
    target_width: int,
    road_buffer_m: float,
    site_name: Optional[str] = None,
) -> dict:
    name = validate_site_name(site_name)
    height = _whole_number(target_height, "target_height")
    width = _whole_number(target_width, "target_width")
    if height < 1 or width < 1:
        raise NamingError("target_height and target_width must be >= 1")
    zoom_i = _whole_number(zoom, "zoom")
    if zoom_i < 1:
        raise NamingError("zoom must be >= 1")
    buffer_m = _whole_number(road_buffer_m, "road_buffer_m")
    return {
        "site_name": name,
        "lat": float(_fixed(lat, 6, "lat")),
        "lon": float(_fixed(lon, 6, "lon")),
        "lat_text": _fixed(lat, 6, "lat"),
        "lon_text": _fixed(lon, 6, "lon"),
        "radius_km": float(_fixed(radius_km, 3, "radius_km")),
        "radius_text": _fixed(radius_km, 3, "radius_km"),
        "zoom": zoom_i,
        "target_height": height,
        "target_width": width,
        "road_buffer_m": buffer_m,
    }


def build_site_id(
    lat: float,
    lon: float,
    radius_km: float,
    zoom: int,
    target_height: int,
    target_width: int,
    road_buffer_m: float,
    site_name: Optional[str] = None,
) -> str:
    params = canonical_parameters(
        lat, lon, radius_km, zoom, target_height, target_width, road_buffer_m, site_name
    )
    return (
        f"lat{params['lat_text']}_lon{params['lon_text']}"
        f"_r{params['radius_text']}km_z{params['zoom']}"
        f"_g{params['target_height']}x{params['target_width']}_rb{params['road_buffer_m']}m"
    )


def bundle_filenames(site_id: str) -> dict:
    return {
        "satellite": f"{site_id}_satellite_epsg3857.tif",
        "landuse": f"{site_id}_landuse.csv",
        "dem": f"{site_id}_dem.tif",
        "osm_roads": f"{site_id}_osm_roads_wgs84.geojson",
    }


def preview_filenames(site_id: str) -> dict:
    return {
        "satellite_preview": f"{site_id}_satellite_preview.png",
        "landuse_preview": f"{site_id}_landuse_preview.png",
        "dem_preview": f"{site_id}_dem_preview.png",
        "osm_preview": f"{site_id}_osm_roads_preview.png",
        "alignment_preview": f"{site_id}_alignment_check.png",
    }


def resolve_site_directory(
    site_id: str,
    output_dir: Optional[str] = None,
    output_root: Optional[str] = None,
    default_root: Optional[str] = None,
) -> tuple:
    """Return ``(site_dir, mode)``.

    ``--output-dir`` is the legacy exact directory. ``--output-root`` creates
    ``<root>/<site_id>``. Passing both is rejected.
    """
    if output_dir and output_root:
        raise NamingError("Use either --output-dir (legacy) or --output-root, not both.")
    if output_dir:
        return os.path.abspath(output_dir), "legacy_output_dir"
    root = os.path.abspath(output_root or default_root or os.path.join(os.getcwd(), "outputs"))
    return os.path.join(root, site_id), "site_id_directory"


def build_site_paths(site_id: str, output_root: Optional[str] = None, site_dir: Optional[str] = None) -> dict:
    root = os.path.abspath(site_dir or os.path.join(output_root or "outputs", site_id))
    bundle = os.path.join(root, "bundle")
    previews = os.path.join(root, "previews")
    cache = os.path.join(root, ".cache")
    names = bundle_filenames(site_id)
    pictures = preview_filenames(site_id)
    paths = {
        "site_id": site_id,
        "site_dir": root,
        "bundle_dir": bundle,
        "previews_dir": previews,
        "cache_dir": cache,
        "satellite": os.path.join(bundle, names["satellite"]),
        "landuse": os.path.join(bundle, names["landuse"]),
        "dem": os.path.join(bundle, names["dem"]),
        "osm_roads": os.path.join(bundle, names["osm_roads"]),
        "satellite_preview": os.path.join(previews, pictures["satellite_preview"]),
        "landuse_preview": os.path.join(previews, pictures["landuse_preview"]),
        "dem_preview": os.path.join(previews, pictures["dem_preview"]),
        "osm_preview": os.path.join(previews, pictures["osm_preview"]),
        "alignment_preview": os.path.join(previews, pictures["alignment_preview"]),
        "metadata": os.path.join(root, "metadata.json"),
        "qa_report": os.path.join(root, "qa_report.json"),
        "downstream_config": os.path.join(root, "downstream_config.json"),
        "manifest": os.path.join(cache, "stage_manifest.json"),
        "cache_satellite": os.path.join(cache, "satellite_epsg3857.tif"),
        "cache_satellite_preview": os.path.join(cache, "satellite_preview.png"),
        "cache_satellite_meta": os.path.join(cache, "satellite_meta.json"),
        "cache_coarse": os.path.join(cache, "routing_coarse_mask.npy"),
        "cache_landuse_npy": os.path.join(cache, "landuse_downsampled.npy"),
        "cache_landuse_csv": os.path.join(cache, "landuse.csv"),
        "cache_landuse_preview": os.path.join(cache, "landuse_preview.png"),
        "cache_osm": os.path.join(cache, "osm_roads.geojson"),
        "cache_osm_summary": os.path.join(cache, "osm_summary.json"),
        "cache_dem": os.path.join(cache, "dem.tif"),
        "cache_dem_summary": os.path.join(cache, "dem_summary.json"),
        "staging_dir": os.path.join(cache, "staging"),
    }
    return paths


def assert_site_identity(site_dir: str, site_id: str, parameters: dict) -> None:
    """Refuse to overwrite a directory whose saved parameters are different."""
    meta_path = os.path.join(site_dir, "metadata.json")
    if not os.path.isfile(meta_path):
        return
    with open(meta_path, "r", encoding="utf-8") as handle:
        saved = json.load(handle)
    saved_id = saved.get("site_id")
    saved_params = saved.get("parameters") or {}
    current = {
        "radius_km": parameters["radius_km"],
        "zoom": parameters["zoom"],
        "target_height": parameters["target_height"],
        "target_width": parameters["target_width"],
        "road_buffer_m": parameters["road_buffer_m"],
    }
    center = saved.get("center") or {}
    same = (
        saved_id == site_id
        and saved.get("site_name") == parameters["site_name"]
        and center.get("lat") == parameters["lat"]
        and center.get("lon") == parameters["lon"]
        and saved_params == current
    )
    if not same:
        raise NamingError(
            f"{meta_path} already belongs to site_id={saved_id!r} with different parameters. "
            "Refusing to overwrite it with "
            f"{site_id}."
        )
