"""Read-only construction report for one already chosen site. It does not run a search."""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from experiments.constraint_mask import compose_constraint_masks, policy_from_form, polygons_from_form
from modeling.access_path import DEFAULT_ACCESS_SLOPE_LIMIT_DEG, access_warning
from modeling.footprint_terrain import footprint_terrain
from modeling.haul_field import HaulField, build_haul_field, query_route
from modeling.slope import DEFAULT_SLOPE_LIMIT_DEG, footprint_max_slope_deg


_SITE_REPORT_FIELD_VERSION = "haul-field-route-v1"
_SITE_REPORT_CACHE_LOCK = threading.RLock()


def build_site_report(
    scene_dir: str | Path,
    x: float,
    y: float,
    theta: float,
    rect_w_m: float,
    rect_h_m: float,
    origin: tuple[float, float] | None = None,
    slope_limit_deg: float = DEFAULT_SLOPE_LIMIT_DEG,
    access_slope_limit_deg: float = DEFAULT_ACCESS_SLOPE_LIMIT_DEG,
    obstacle_mask: np.ndarray | None = None,
    allow_unreachable: bool = False,
    constraint_form: dict[str, object] | None = None,
) -> dict[str, object]:
    from experiments.scene_store import ensure_scene_readable

    directory = Path(scene_dir)
    ensure_scene_readable(directory)
    if obstacle_mask is not None and constraint_form is not None:
        raise ValueError("obstacle_mask and constraint_form cannot both be provided")
    field = _site_report_field(directory, origin, obstacle_mask, constraint_form)
    ensure_scene_readable(directory)
    slope = footprint_max_slope_deg(field.dem, (x, y, theta), rect_w_m, rect_h_m)
    report: dict[str, object] = {
        "footprint_slope_deg": slope,
        "slope_limit_deg": slope_limit_deg,
        "access_rise_m": None,
        "access_slope_deg": None,
        "access_warning": False,
        "road_haul_m": None,
        "offroad_haul_m": None,
        "haul_rise_m": None,
        "haul_path": None,
    }
    try:
        route = query_route(field, (x, y))
        report.update({
            "access_rise_m": route["haul_rise_m"],
            "access_slope_deg": route["access_slope_deg"],
            "access_warning": access_warning(float(route["access_slope_deg"]), access_slope_limit_deg),
            "road_haul_m": route.get("road_haul_m"),
            "offroad_haul_m": route["offroad_haul_m"],
            "haul_rise_m": route["haul_rise_m"],
            "haul_path": route["points"],
        })
    except ValueError as exc:
        if not allow_unreachable:
            raise
        report["access_error"] = str(exc)
    return report


def _site_report_field(
    directory: Path,
    origin: tuple[float, float] | None,
    obstacle_mask: np.ndarray | None,
    constraint_form: dict[str, object] | None,
) -> HaulField:
    if obstacle_mask is not None:
        dem = np.load(directory / "dem_1m.npy")
        segments = np.load(directory / "road_segments_local.npy")
        if obstacle_mask.shape != dem.shape:
            raise ValueError("obstacle mask must match the DEM shape")
        return build_haul_field(dem, obstacle_mask == 0, segments, origin)
    constraints_json = "" if constraint_form is None else json.dumps(
        constraint_form,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = _scene_signature(directory, constraint_form is not None)
    normalized_origin = None if origin is None else (float(origin[0]), float(origin[1]))
    with _SITE_REPORT_CACHE_LOCK:
        return _cached_site_report_field(
            str(directory.resolve()),
            signature,
            constraints_json,
            normalized_origin,
            _SITE_REPORT_FIELD_VERSION,
        )


def _scene_signature(directory: Path, uses_landuse: bool) -> tuple[tuple[str, int, int], ...]:
    mask_name = "landuse_1m.npy" if uses_landuse else "obstacle_mask_1m.npy"
    signature = []
    for name in ("dem_1m.npy", "road_segments_local.npy", mask_name):
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(f"scene {directory.name} is missing {name}")
        stat = path.stat()
        signature.append((name, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


@lru_cache(maxsize=1)
def _cached_site_report_field(
    directory_name: str,
    _signature: tuple[tuple[str, int, int], ...],
    constraints_json: str,
    origin: tuple[float, float] | None,
    _version: str,
) -> HaulField:
    directory = Path(directory_name)
    dem = np.load(directory / "dem_1m.npy")
    segments = np.load(directory / "road_segments_local.npy")
    if constraints_json:
        hard_mask = site_report_hard_mask(directory, json.loads(constraints_json))
    else:
        hard_mask = np.load(directory / "obstacle_mask_1m.npy")
    if hard_mask.shape != dem.shape:
        raise ValueError("obstacle mask must match the DEM shape")
    return build_haul_field(dem, hard_mask == 0, segments, origin)


def clear_site_report_cache() -> None:
    with _SITE_REPORT_CACHE_LOCK:
        _cached_site_report_field.cache_clear()


def site_report_cache_info():
    with _SITE_REPORT_CACHE_LOCK:
        return _cached_site_report_field.cache_info()


def site_report_hard_mask(scene_dir: str | Path, constraint_form: dict[str, object]) -> np.ndarray:
    """Compose the report mask with the same policy and polygon helpers as a search."""

    directory = Path(scene_dir)
    landuse_path = directory / "landuse_1m.npy"
    if not landuse_path.is_file():
        raise FileNotFoundError(f"scene {directory.name} is missing landuse_1m.npy")
    landuse = np.load(landuse_path)
    hard, _soft = compose_constraint_masks(
        landuse,
        polygons_from_form(constraint_form),
        policy_from_form(constraint_form),
        polygons_from_form(constraint_form, "feasible_zones"),
    )
    return hard


def build_footprint_terrain(
    scene_dir: str | Path,
    x: float,
    y: float,
    theta: float,
    rect_w_m: float,
    rect_h_m: float,
) -> dict[str, object]:
    directory = Path(scene_dir)
    dem = np.load(directory / "dem_1m.npy")
    landuse = np.load(directory / "landuse_1m.npy")
    return footprint_terrain(dem, landuse, (x, y, theta), rect_w_m, rect_h_m)
