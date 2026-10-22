#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the four site-data files, metadata, and a machine-readable QA report."""
from __future__ import annotations

import json
import os
import platform
import shutil
from datetime import datetime, timezone
from typing import Optional, Sequence

import numpy as np

from geo_utils import bounds_contain, file_signature, sha256_file, transform_bounds


def write_landuse_csv(mask: np.ndarray, path: str) -> np.ndarray:
    arr = np.asarray(mask)
    if arr.ndim != 2:
        raise ValueError(f"landuse mask must be 2D, got shape {arr.shape}")
    rounded = np.rint(arr)
    if not np.isfinite(arr).all() or not np.allclose(arr, rounded, rtol=0.0, atol=1e-3):
        raise ValueError("landuse classes must be integers; do not bilinearly resample class ids")
    out = np.rint(arr).astype(np.int32)
    bad = sorted(set(np.unique(out).tolist()) - set(range(6)))
    if bad:
        raise ValueError(f"landuse contains values outside 0..5: {bad}")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    np.savetxt(path, out, fmt="%d", delimiter=",")
    return out


def layout(output_dir: str) -> dict:
    """Workspace folders. The official bundle directory is created only on publish."""
    root = os.path.abspath(output_dir)
    cache = os.path.join(root, ".cache")
    paths = {
        "root": root,
        "bundle": os.path.join(root, "bundle"),
        "previews": os.path.join(root, "previews"),
        "cache": cache,
        "intermediates": cache,
    }
    os.makedirs(cache, exist_ok=True)
    os.makedirs(paths["previews"], exist_ok=True)
    return paths


def manifest_path(output_dir: str) -> str:
    return os.path.join(layout(output_dir)["cache"], "stage_manifest.json")


def canon_params(params: dict) -> dict:
    return json.loads(json.dumps(params, sort_keys=True))


def load_manifest(output_dir: str) -> dict:
    path = manifest_path(output_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def record_stage(output_dir: str, stage: str, params: dict, files: Sequence[str]) -> None:
    path = manifest_path(output_dir)
    manifest = load_manifest(output_dir)
    manifest[stage] = {
        "status": "passed",
        "params": canon_params(params),
        "files": [os.path.abspath(item) for item in files],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


def stage_is_reusable(manifest: dict, stage: str, params: dict, files: Sequence[str]) -> tuple:
    entry = manifest.get(stage)
    if not entry:
        return False, f"no cache entry for {stage}"
    if entry.get("status") != "passed":
        return False, f"cached {stage} did not pass"
    if canon_params(entry.get("params") or {}) != canon_params(params):
        return False, f"cached {stage} parameters do not match this run"
    for item in files:
        if not os.path.isfile(item):
            return False, f"cached {stage} is missing {item}"
    return True, "cache accepted"


def _check(checks: list, errors: list, warnings: list, name: str, ok: bool, detail: str, warn: bool = False) -> None:
    if ok:
        checks.append({"name": name, "status": "passed", "detail": detail})
        return
    status = "warning" if warn else "failed"
    checks.append({"name": name, "status": status, "detail": detail})
    (warnings if warn else errors).append(f"{name}: {detail}")


def _class_counts(mask: np.ndarray) -> dict:
    values, counts = np.unique(mask, return_counts=True)
    return {str(int(v)): int(c) for v, c in zip(values, counts)}


def _software() -> dict:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("numpy", "rasterio", "pyproj", "PIL", "scipy", "matplotlib", "torch"):
        try:
            module = __import__(name if name != "PIL" else "PIL")
            versions[name] = getattr(module, "__version__", "unknown")
        except Exception:
            versions[name] = None
    return versions


def _copy(src: str, dst: str) -> None:
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _bundle_names(site_dir: str) -> set:
    bundle = os.path.join(site_dir, "bundle")
    if not os.path.isdir(bundle):
        return set()
    return {name for name in os.listdir(bundle) if not name.startswith(".")}


def release_staged_bundle(staging_dir: str, bundle_dir: str, expected_names: Sequence[str]) -> None:
    """Replace ``bundle/`` only when staging has exactly the four official files."""
    present = sorted(name for name in os.listdir(staging_dir) if not name.startswith("."))
    expected = sorted(expected_names)
    if present != expected:
        raise RuntimeError(
            "Refusing to publish an incomplete bundle. "
            f"staging={present} expected={expected}"
        )
    incoming = bundle_dir + ".incoming"
    backup = bundle_dir + ".previous"
    if os.path.isdir(incoming):
        shutil.rmtree(incoming)
    shutil.copytree(staging_dir, incoming)
    moved = False
    if os.path.isdir(bundle_dir):
        if os.path.isdir(backup):
            shutil.rmtree(backup)
        os.rename(bundle_dir, backup)
        moved = True
    try:
        os.rename(incoming, bundle_dir)
    except Exception:
        if moved and not os.path.isdir(bundle_dir) and os.path.isdir(backup):
            os.rename(backup, bundle_dir)
        raise
    if os.path.isdir(backup):
        shutil.rmtree(backup)


def export_bundle(
    output_dir: str,
    satellite_path: str,
    landuse_source,
    osm_geojson: str,
    dem_path: str,
    run_params: dict,
    osm_summary: Optional[dict] = None,
    dem_summary: Optional[dict] = None,
    model: Optional[str] = None,
    site_paths: Optional[dict] = None,
    pipeline_started_at: Optional[str] = None,
) -> dict:
    """Validate four products in staging and publish them only if QA passes.

    ``landuse_source`` is either a CSV path or a 2D class array.
    """
    from naming import bundle_filenames

    if not site_paths:
        raise ValueError("site_paths from naming.build_site_paths is required")
    site_id = site_paths["site_id"]
    names = bundle_filenames(site_id)
    staging = site_paths["staging_dir"]
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)
    bundle_sat = os.path.join(staging, names["satellite"])
    bundle_csv = os.path.join(staging, names["landuse"])
    bundle_osm = os.path.join(staging, names["osm_roads"])
    bundle_dem = os.path.join(staging, names["dem"])
    checks, errors, warnings = [], [], []

    import rasterio

    ref = None
    if os.path.isfile(satellite_path):
        _copy(satellite_path, bundle_sat)
        with rasterio.open(bundle_sat) as src:
            ref = {
                "crs": None if src.crs is None else str(src.crs),
                "bounds": [float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top)],
                "transform": [float(v) for v in src.transform][:6],
                "shape": [int(src.height), int(src.width)],
                "count": int(src.count),
            }
        crs_ok = ref["crs"] in {"EPSG:3857"}
        _check(checks, errors, warnings, "satellite_crs", crs_ok, f"CRS={ref['crs']}")
    else:
        _check(checks, errors, warnings, "satellite_crs", False, f"missing {satellite_path}")

    landuse = None
    try:
        if isinstance(landuse_source, str):
            if not os.path.isfile(landuse_source):
                raise FileNotFoundError(landuse_source)
            if landuse_source.endswith(".csv"):
                landuse = write_landuse_csv(np.loadtxt(landuse_source, delimiter=","), bundle_csv)
            else:
                landuse = write_landuse_csv(np.load(landuse_source), bundle_csv)
        else:
            landuse = write_landuse_csv(np.asarray(landuse_source), bundle_csv)
        expected = (int(run_params.get("target_height") or landuse.shape[0]), int(run_params.get("target_width") or landuse.shape[1]))
        shape_ok = tuple(landuse.shape) == expected
        _check(
            checks, errors, warnings, "landuse_codes",
            shape_ok and set(np.unique(landuse).tolist()).issubset(set(range(6))),
            f"shape {tuple(landuse.shape)} expected {expected}; classes {_class_counts(landuse)}",
        )
    except Exception as exc:
        _check(checks, errors, warnings, "landuse_codes", False, str(exc))

    osm_report = osm_summary or {}
    if os.path.isfile(osm_geojson):
        _copy(osm_geojson, bundle_osm)
        try:
            with open(bundle_osm, "r", encoding="utf-8") as handle:
                collection = json.load(handle)
            features = collection.get("features") or []
            bad_geom = [
                (feature.get("geometry") or {}).get("type")
                for feature in features
                if (feature.get("geometry") or {}).get("type") not in {"LineString", "MultiLineString"}
            ]
            _check(
                checks, errors, warnings, "osm_geometry",
                collection.get("type") == "FeatureCollection" and not bad_geom and len(features) > 0,
                f"features={len(features)} unexpected_geometry={bad_geom[:5]}",
            )
        except Exception as exc:
            _check(checks, errors, warnings, "osm_geometry", False, str(exc))
    else:
        _check(checks, errors, warnings, "osm_geometry", False, f"missing {osm_geojson}")

    target = (osm_report.get("target_bbox_projected") or [None])
    extraction = osm_report.get("extraction_bbox_projected")
    if extraction and ref is not None:
        contains = bounds_contain(tuple(extraction), tuple(ref["bounds"]), tol=1.0)
        _check(checks, errors, warnings, "osm_buffer_contains_target", contains, f"extraction={extraction} target={ref['bounds']}")
    elif extraction and target and target[0] is not None:
        contains = bounds_contain(tuple(extraction), tuple(target), tol=1.0)
        _check(checks, errors, warnings, "osm_buffer_contains_target", contains, "checked against recorded target bbox")
    else:
        _check(checks, errors, warnings, "osm_buffer_contains_target", False, "OSM extent was not recorded", warn=False)

    connectivity = osm_report.get("connectivity") or {}
    if connectivity:
        isolated = int(connectivity.get("isolated_target_component_count") or 0)
        ratio = float(connectivity.get("largest_component_projected_length_ratio") or 0)
        detail = (
            f"components={connectivity.get('component_count')} "
            f"largest_ratio={ratio:.3f} isolated_in_target={isolated}. "
            "Buffer roads do not mean every path outside the study boundary is usable."
        )
        _check(checks, errors, warnings, "osm_connectivity", isolated == 0 and ratio >= 0.8, detail, warn=True)
    else:
        _check(checks, errors, warnings, "osm_connectivity", False, "connectivity was not computed", warn=True)

    if os.path.isfile(dem_path):
        _copy(dem_path, bundle_dem)
        try:
            with rasterio.open(bundle_dem) as src:
                if src.crs is None:
                    raise ValueError("DEM has no CRS")
                dem_bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
                covers = True
                if ref is not None and ref["crs"]:
                    ref_in_dem = transform_bounds(ref["crs"], str(src.crs), tuple(ref["bounds"]))
                    covers = bounds_contain(dem_bounds, ref_in_dem, tol=max(abs(src.res[0]), abs(src.res[1])) * 2)
                detail = f"CRS={src.crs} bounds={list(dem_bounds)} nodata={src.nodata}"
                if dem_summary:
                    detail += (
                        f" elev={dem_summary.get('elevation_min')}..{dem_summary.get('elevation_max')} "
                        f"model={dem_summary.get('elevation_model')}"
                    )
                _check(checks, errors, warnings, "dem_coverage", covers and src.crs is not None, detail)
        except Exception as exc:
            _check(checks, errors, warnings, "dem_coverage", False, str(exc))
    else:
        _check(checks, errors, warnings, "dem_coverage", False, f"missing {dem_path}")

    aligned = ref is not None and landuse is not None and os.path.isfile(bundle_osm) and os.path.isfile(bundle_dem)
    _check(
        checks, errors, warnings, "layer_alignment",
        aligned,
        "Satellite, landuse grid, OSM and DEM are present and tied to the satellite bounds.",
    )
    if osm_report.get("warning"):
        warnings.append(str(osm_report["warning"]))

    staged = {
        names["satellite"]: bundle_sat,
        names["landuse"]: bundle_csv,
        names["osm_roads"]: bundle_osm,
        names["dem"]: bundle_dem,
    }
    present = sorted(name for name, path in staged.items() if os.path.isfile(path))
    expected = sorted(names.values())
    names_ok = present == expected and all(name.startswith(site_id + "_") for name in present)
    _check(
        checks, errors, warnings, "bundle_names",
        names_ok,
        f"staging={present} expected={expected}",
    )
    hashed = {}
    for name, path in staged.items():
        if os.path.isfile(path):
            hashed[name] = {"bytes": os.path.getsize(path), "sha256": sha256_file(path)}

    overall = "passed" if not errors else "failed"
    site_dir = site_paths["site_dir"]
    file_map = {
        "reference_geotiff_path": f"bundle/{names['satellite']}",
        "landuse_path": f"bundle/{names['landuse']}",
        "dem_path": f"bundle/{names['dem']}",
        "osm_roads_path": f"bundle/{names['osm_roads']}",
    }
    qa = {
        "overall_status": overall,
        "site_id": site_id,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "road_buffer_access_note": (
            "Roads outside the study polygon are retained so approach topology is not cut "
            "on the boundary. That does not mean the downstream model can use every off-boundary detour."
        ),
    }
    center = run_params.get("center") or {}
    metadata = {
        "schema_version": "1.0",
        "site_id": site_id,
        "site_name": run_params.get("site_name"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_started_at": pipeline_started_at,
        "center": {
            "lat": center.get("lat", run_params.get("lat")),
            "lon": center.get("lon", run_params.get("lon")),
            "crs": "EPSG:4326",
        },
        "parameters": {
            "radius_km": run_params.get("radius_km"),
            "zoom": run_params.get("zoom"),
            "target_height": run_params.get("target_height"),
            "target_width": run_params.get("target_width"),
            "road_buffer_m": run_params.get("road_buffer_m"),
            "radius_km_meaning": (
                "Half-side of the requested square in Web Mercator metres "
                "(radius_km * 1000), not a geodesic radius."
            ),
            "road_buffer_meaning": (
                "Extra OSM extent measured in the satellite CRS. For EPSG:3857 these are "
                "projected metres, not geodesic ground distance."
            ),
        },
        "files": file_map,
        "file_hashes": hashed,
        "reference_geotiff": ref,
        "bounds_note": "Use reference_geotiff.bounds. Do not reconstruct the extent from the site_id radius.",
        "landuse": None
        if landuse is None
        else {
            "shape": [int(landuse.shape[0]), int(landuse.shape[1])],
            "class_counts": _class_counts(landuse),
            "model": model,
            "encoding": "integer 0..5, no header, row 0 is north, nearest-neighbor resize only",
        },
        "osm": {
            "summary": {key: value for key, value in osm_report.items() if key != "features"},
            "source_signature": file_signature(run_params["osm_pbf"]) if run_params.get("osm_pbf") and os.path.isfile(run_params["osm_pbf"]) else None,
        },
        "dem": dem_summary,
        "software": _software(),
        "bundle_release": "rejected",
    }
    published = False
    if overall == "passed":
        release_staged_bundle(staging, site_paths["bundle_dir"], list(names.values()))
        metadata["bundle_release"] = "accepted"
        published = True
        with open(site_paths["metadata"], "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
        downstream = {
            "data": {
                "reference_geotiff_path": os.path.abspath(site_paths["satellite"]),
                "landuse_path": os.path.abspath(site_paths["landuse"]),
                "dem_path": os.path.abspath(site_paths["dem"]),
                "osm_roads_path": os.path.abspath(site_paths["osm_roads"]),
            }
        }
        with open(site_paths["downstream_config"], "w", encoding="utf-8") as handle:
            json.dump(downstream, handle, ensure_ascii=False, indent=2)
    else:
        print("Bundle was not published. Any previous successful bundle was left in place.")
    with open(site_paths["qa_report"], "w", encoding="utf-8") as handle:
        json.dump(qa, handle, ensure_ascii=False, indent=2)
    print(f"QA {overall}: {site_paths['qa_report']}")
    if errors:
        for item in errors:
            print(f"  ERROR {item}")
    for item in warnings:
        print(f"  WARNING {item}")
    return {
        "qa_report": site_paths["qa_report"],
        "metadata": site_paths["metadata"] if published else None,
        "overall_status": overall,
        "published": published,
        "staging_dir": staging,
        "bundle": {name: os.path.join(site_paths["bundle_dir"], name) for name in names.values()} if published else {},
    }
