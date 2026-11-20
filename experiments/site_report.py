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

from experiments.constraint_mask import policy_from_form, polygons_from_form
from experiments.site_context import access_connector_mask, access_constraint_mask, walkable_access_cells
from experiments.haul_field_cache import (
    HaulFieldCacheResult,
    clear_haul_field_reuse,
    compatible_haul_field,
    get_or_build_haul_field,
    haul_memory_identity,
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


def _site_report_field(directory, origin, obstacle_mask, constraint_form, access_elevation_weight, timings=None):
    # 场景锁只在读场景文件时持有：缓存命中不碰锁，距离场在锁外读取或构建。
    if constraint_form is not None:
        # 禁区只禁止建站，进站道路可以穿过，所以不进入距离场和它的缓存键。
        # 禁区和海拔上限只改建筑占地，不改变进站距离场。
        constraint_form = {
            key: value for key, value in constraint_form.items() if key not in {"exclusion_zones", "max_elevation_m"}
        }
    return _snapshot_site_report_field(directory, origin, obstacle_mask, constraint_form, access_elevation_weight, timings)


def _snapshot_site_report_field(
    directory: Path,
    origin: tuple[float, float] | None,
    obstacle_mask: np.ndarray | None,
    constraint_form: dict[str, object] | None,
    access_elevation_weight: float,
    timings: dict[str, Any] | None = None,
) -> HaulField:
    if obstacle_mask is not None:
        field_started = perf_counter()
        dem, walkable, segments, connector_blocked, segment_kinds, _signature = _report_inputs(directory, None, obstacle_mask)
        build_started = perf_counter()
        field = build_haul_field(
            dem,
            walkable,
            segments,
            origin,
            diagonal=True,
            access_elevation_weight=access_elevation_weight,
            connector_blocked=connector_blocked,
            segment_kinds=segment_kinds,
        )
        if timings is not None:
            timings["field_cache"] = "bypass"
            timings["field_build_seconds"] = perf_counter() - build_started
            timings["field_seconds"] = perf_counter() - field_started
        return field
    if constraint_form is not None:
        reused = compatible_haul_field(haul_memory_identity(
            directory,
            constraint_form,
            origin,
            access_elevation_weight,
            uses_landuse=True,
            diagonal=True,
        ))
        if reused is not None:
            if timings is not None:
                timings["field_cache"] = "memory_reuse"
                timings["field_seconds"] = 0.0
                timings["field_build_seconds"] = 0.0
            return reused
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
    dem, walkable, segments, connector_blocked, segment_kinds, signature = _report_inputs(
        directory, None if not constraints_json else json.loads(constraints_json))
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
        segment_kinds=segment_kinds,
        source_signature=signature,
    )


def _report_inputs(directory, constraint_form, obstacle_mask=None):
    from experiments.scene_lock import scene_write_lock
    from experiments.protected_farmland import load_mask, burn_farmland
    from experiments.haul_field_cache import scene_source_signature
    with scene_write_lock(directory.name, directory.parent, blocking=True):
        dem = np.load(directory / "dem_1m.npy")
        segments = np.load(directory / "road_segments_local.npy")
        kinds = np.load(directory / "road_segment_kind.npy")
        landuse = np.load(directory / "landuse_1m.npy") if constraint_form is not None else None
        hard = np.load(directory / "obstacle_mask_1m.npy") if constraint_form is None and obstacle_mask is None else obstacle_mask
        farmland = load_mask(directory, dem.shape)
        signature = scene_source_signature(directory, uses_landuse=constraint_form is not None)
    if constraint_form is not None:
        if landuse.shape != dem.shape:
            raise ValueError("obstacle mask must match the DEM shape")
        hard = access_constraint_mask(landuse, policy_from_form(constraint_form),
                                      polygons_from_form(constraint_form, "feasible_zones"), farmland)
    else:
        if hard.shape != dem.shape:
            raise ValueError("obstacle mask must match the DEM shape")
        hard, _ = burn_farmland(hard, hard, farmland)
    blocked = access_connector_mask(farmland)
    return dem, walkable_access_cells(hard, blocked), segments, blocked, kinds, signature


def clear_site_report_cache() -> None:
    clear_haul_field_reuse()
    with _SITE_REPORT_CACHE_LOCK:
        _cached_site_report_field.cache_clear()


def site_report_cache_info():
    with _SITE_REPORT_CACHE_LOCK:
        return _cached_site_report_field.cache_info()


def site_report_hard_mask(scene_dir: str | Path, constraint_form: dict[str, object]) -> np.ndarray:
    """The access-road mask a search walks on. Exclusion zones and landuse 3 are left out."""

    directory = Path(scene_dir)
    landuse_path = directory / "landuse_1m.npy"
    if not landuse_path.is_file():
        raise FileNotFoundError(f"scene {directory.name} is missing landuse_1m.npy")
    landuse = np.load(landuse_path)
    from experiments.protected_farmland import load_mask

    return access_constraint_mask(landuse, policy_from_form(constraint_form),
                                  polygons_from_form(constraint_form, "feasible_zones"),
                                  load_mask(directory, landuse.shape))


def build_footprint_terrain(
    scene_dir: str | Path,
    x: float,
    y: float,
    theta: float,
    rect_w_m: float,
    rect_h_m: float,
) -> dict[str, object]:
    directory = Path(scene_dir)
    from experiments.scene_lock import scene_write_lock
    with scene_write_lock(directory.name, directory.parent, blocking=True):
        dem = np.load(directory / "dem_1m.npy")
        landuse = np.load(directory / "landuse_1m.npy")
    return footprint_terrain(dem, landuse, (x, y, theta), rect_w_m, rect_h_m)
