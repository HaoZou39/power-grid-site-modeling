"""Read-only construction report for one already chosen site. It does not run a search."""

from __future__ import annotations

import json
import logging
import threading
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from experiments.constraint_mask import compose_constraint_masks, policy_from_form, polygons_from_form
from experiments.haul_field_cache import (
    HaulFieldCacheResult,
    get_or_build_haul_field,
    scene_source_signature,
)
from modeling.access_path import DEFAULT_ACCESS_SLOPE_LIMIT_DEG, access_warning
from modeling.footprint_terrain import footprint_terrain
from modeling.haul_field import HaulField, build_haul_field, query_route
from modeling.slope import DEFAULT_SLOPE_LIMIT_DEG, footprint_max_slope_deg


_SITE_REPORT_FIELD_VERSION = "haul-field-elevation-dijkstra-v3-shared-disk"
_SITE_REPORT_CACHE_LOCK = threading.RLock()
_LOGGER = logging.getLogger("uvicorn.error")


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
    access_elevation_weight: float | None = None,
) -> dict[str, object]:
    from experiments.scene_store import ensure_scene_readable

    if access_elevation_weight is None:
        from config.project_config import load_project_config

        access_elevation_weight = float(
            (constraint_form or {}).get(
                "access_elevation_weight",
                load_project_config(
                    Path(__file__).resolve().parents[1] / "config" / "default_config.json"
                ).guided_search.access_elevation_weight,
            )
        )
    chosen_weight = float(access_elevation_weight)
    started = perf_counter()
    timings: dict[str, Any] = {
        "field_cache": "unknown",
        "field_seconds": 0.0,
        "field_build_seconds": 0.0,
        "slope_seconds": 0.0,
        "route_seconds": 0.0,
    }
    directory = Path(scene_dir)
    try:
        ensure_scene_readable(directory)
        if obstacle_mask is not None and constraint_form is not None:
            raise ValueError("obstacle_mask and constraint_form cannot both be provided")
        field = _site_report_field(
            directory,
            origin,
            obstacle_mask,
            constraint_form,
            chosen_weight,
            timings,
        )
        ensure_scene_readable(directory)
        slope_started = perf_counter()
        try:
            slope = footprint_max_slope_deg(field.dem, (x, y, theta), rect_w_m, rect_h_m)
        finally:
            timings["slope_seconds"] = perf_counter() - slope_started
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
        route_started = perf_counter()
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
        finally:
            timings["route_seconds"] = perf_counter() - route_started
        return report
    finally:
        _LOGGER.info(
            "site_report total_s=%.3f field_cache=%s field_s=%.3f build_s=%.3f slope_s=%.3f route_s=%.3f scene=%s",
            perf_counter() - started,
            timings["field_cache"],
            timings["field_seconds"],
            timings["field_build_seconds"],
            timings["slope_seconds"],
            timings["route_seconds"],
            directory.name,
        )


def _site_report_field(
    directory: Path,
    origin: tuple[float, float] | None,
    obstacle_mask: np.ndarray | None,
    constraint_form: dict[str, object] | None,
    access_elevation_weight: float,
    timings: dict[str, Any] | None = None,
) -> HaulField:
    if obstacle_mask is not None:
        field_started = perf_counter()
        dem = np.load(directory / "dem_1m.npy")
        segments = np.load(directory / "road_segments_local.npy")
        if obstacle_mask.shape != dem.shape:
            raise ValueError("obstacle mask must match the DEM shape")
        from experiments.protected_farmland import access_inputs, stamp_constraint_masks

        hard_mask, _soft = stamp_constraint_masks(directory, obstacle_mask, obstacle_mask)
        walkable, connector_blocked = access_inputs(directory, hard_mask)
        build_started = perf_counter()
        field = build_haul_field(
            dem,
            walkable,
            segments,
            origin,
            diagonal=True,
            access_elevation_weight=access_elevation_weight,
            connector_blocked=connector_blocked,
        )
        if timings is not None:
            timings["field_cache"] = "bypass"
            timings["field_build_seconds"] = perf_counter() - build_started
            timings["field_seconds"] = perf_counter() - field_started
        return field
    constraints_json = "" if constraint_form is None else json.dumps(
        constraint_form,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = _scene_signature(directory, constraint_form is not None)
    normalized_origin = None if origin is None else (float(origin[0]), float(origin[1]))
    with _SITE_REPORT_CACHE_LOCK:
        before = _cached_site_report_field.cache_info()
        result = _cached_site_report_field(
            str(directory.resolve()),
            signature,
            constraints_json,
            normalized_origin,
            access_elevation_weight,
            _SITE_REPORT_FIELD_VERSION,
        )
        after = _cached_site_report_field.cache_info()
        if timings is not None:
            timings["field_cache"] = "memory_hit" if after.hits > before.hits else result.status
            timings["field_seconds"] = 0.0 if after.hits > before.hits else result.elapsed_seconds
            timings["field_build_seconds"] = 0.0 if after.hits > before.hits else result.build_seconds
        return result.field


def _scene_signature(directory: Path, uses_landuse: bool) -> tuple[tuple[str, int, int], ...]:
    return scene_source_signature(directory, uses_landuse=uses_landuse)


@lru_cache(maxsize=1)
def _cached_site_report_field(
    directory_name: str,
    _signature: tuple[tuple[str, int, int], ...],
    constraints_json: str,
    origin: tuple[float, float] | None,
    access_elevation_weight: float,
    _version: str,
) -> HaulFieldCacheResult:
    directory = Path(directory_name)
    dem = np.load(directory / "dem_1m.npy")
    segments = np.load(directory / "road_segments_local.npy")
    if constraints_json:
        hard_mask = site_report_hard_mask(directory, json.loads(constraints_json))
    else:
        hard_mask = np.load(directory / "obstacle_mask_1m.npy")
    if hard_mask.shape != dem.shape:
        raise ValueError("obstacle mask must match the DEM shape")
    from experiments.protected_farmland import access_inputs

    walkable, connector_blocked = access_inputs(directory, hard_mask)
    return get_or_build_haul_field(
        directory,
        dem,
        walkable,
        segments,
        origin,
        None if not constraints_json else json.loads(constraints_json),
        uses_landuse=bool(constraints_json),
        access_elevation_weight=access_elevation_weight,
        connector_blocked=connector_blocked,
    )


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
    from experiments.protected_farmland import stamp_constraint_masks

    hard, _soft = compose_constraint_masks(
        landuse,
        polygons_from_form(constraint_form),
        policy_from_form(constraint_form),
        polygons_from_form(constraint_form, "feasible_zones"),
    )
    hard, _soft = stamp_constraint_masks(directory, hard, hard)
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
