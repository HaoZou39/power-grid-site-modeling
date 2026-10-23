"""Safe cross-process cache for the scene-level haul distance field."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from modeling.construction_cost import ApproachGrid
from modeling.haul_field import HaulField, bind_haul_origin, build_haul_field
from modeling.logistics_cost import RoadNetwork, RoadOriginRoutes


_LOGGER = logging.getLogger("uvicorn.error")
_CACHE_VERSION = "haul-field-elevation-dijkstra-v3-origin-binding"
_CACHE_DIRECTORY = ".haul_field_cache"
_MAX_ENTRIES = 4
_MAX_BYTES = 1024 * 1024 * 1024

_ARRAY_DTYPES = {
    "offroad_m": np.dtype(np.float64),
    "access_rise_m": np.dtype(np.float64),
    "reachable": np.dtype(bool),
    "road_cells": np.dtype(bool),
    "predecessor": np.dtype(np.int8),
    "gate_owner": np.dtype(np.int32),
    "gate_cells": np.dtype(np.int32),
    "gate_contacts": np.dtype(np.float64),
    "gate_contact_edges": np.dtype(np.int32),
    "gate_reachable": np.dtype(bool),
    "gate_road_m": np.dtype(np.float64),
    "gate_offroad_m": np.dtype(np.float64),
    "gate_rise_m": np.dtype(np.float64),
}

_ORDER_DTYPES = {"access_order": np.dtype(np.int32)}


@dataclass(frozen=True)
class HaulFieldCacheResult:
    field: HaulField
    status: str
    key: str
    elapsed_seconds: float
    build_seconds: float


def _form_diagonal(form: dict[str, Any] | None) -> bool:
    return bool((form or {}).get("diagonal_access", False))


def canonical_haul_constraints(form: dict[str, Any] | None, *, uses_landuse: bool) -> str:
    """Return only inputs that can affect the hard mask or its cache identity."""

    if not uses_landuse:
        payload: dict[str, Any] = {"mask_source": "obstacle_mask_1m.npy"}
    else:
        source = form or {}
        field_cost = source.get("field_cost")
        payload = {
            "mask_source": "landuse_1m.npy",
            "mountain_policy": str(source.get("mountain_policy") or "allowed"),
            "field_policy": str(source.get("field_policy") or "allowed"),
            # The soft cost does not alter this field today, but remains part of the
            # identity so a report can never cross optimization configurations.
            "field_cost": float(0.5 if field_cost is None else field_cost),
            "exclusion_zones": source.get("exclusion_zones") or [],
            "feasible_zones": source.get("feasible_zones") or [],
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def scene_source_signature(directory: Path, *, uses_landuse: bool) -> tuple[tuple[str, int, int], ...]:
    mask_name = "landuse_1m.npy" if uses_landuse else "obstacle_mask_1m.npy"
    signature = []
    for name in ("dem_1m.npy", "road_segments_local.npy", mask_name):
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(f"scene {directory.name} is missing {name}")
        stat = path.stat()
        signature.append((name, stat.st_mtime_ns, stat.st_size))
    from experiments.protected_farmland import farmland_file_signature

    farmland = farmland_file_signature(directory)
    if farmland is not None:
        signature.append(farmland)
    return tuple(signature)


def get_or_build_haul_field(
    scene_dir: str | Path,
    dem: np.ndarray,
    buildable: np.ndarray,
    segments: np.ndarray,
    origin: tuple[float, float] | None,
    constraint_form: dict[str, Any] | None,
    *,
    uses_landuse: bool,
    diagonal: bool | None = None,
    access_elevation_weight: float = 1.0,
    connector_blocked: np.ndarray | None = None,
) -> HaulFieldCacheResult:
    """Load a compatible field from shared scene storage, or build and publish it."""

    started = perf_counter()
    directory = Path(scene_dir).resolve()
    normalized_origin = None if origin is None else (float(origin[0]), float(origin[1]))
    chosen_diagonal = _form_diagonal(constraint_form) if diagonal is None else bool(diagonal)
    if not math.isfinite(access_elevation_weight) or access_elevation_weight < 0:
        raise ValueError("access_elevation_weight must be finite and non-negative")
    network = RoadNetwork(segments)
    routes = None if normalized_origin is None else network.routes_from(normalized_origin)
    signature = scene_source_signature(directory, uses_landuse=uses_landuse)
    constraints_json = canonical_haul_constraints(constraint_form, uses_landuse=uses_landuse)
    key = _cache_key(
        directory,
        signature,
        constraints_json,
        normalized_origin,
        dem,
        buildable,
        segments,
        diagonal=chosen_diagonal,
        access_elevation_weight=access_elevation_weight,
        network=network,
        routes=routes,
        connector_blocked=connector_blocked,
    )
    root = directory / _CACHE_DIRECTORY
    target = root / key
    if target.is_dir():
        try:
            field = _load_field(
                target,
                key,
                dem,
                buildable,
                segments,
                normalized_origin,
                access_elevation_weight,
                routes=routes,
            )
            try:
                os.utime(target, None)
            except OSError:
                pass
            elapsed = perf_counter() - started
            _LOGGER.info("haul_field_cache status=disk_hit key=%s elapsed_s=%.3f", key[:12], elapsed)
            return HaulFieldCacheResult(field, "disk_hit", key, elapsed, 0.0)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _LOGGER.warning("haul_field_cache status=invalid key=%s reason=%s", key[:12], exc)
            _discard_cache_entry(root, target)

    build_started = perf_counter()
    field = build_haul_field(
        dem,
        buildable,
        segments,
        normalized_origin,
        diagonal=chosen_diagonal,
        access_elevation_weight=access_elevation_weight,
        connector_blocked=connector_blocked,
    )
    build_seconds = perf_counter() - build_started
    try:
        _write_field(root, target, key, field)
        _prune_cache(root, protected=target)
    except (OSError, ValueError) as exc:
        _LOGGER.warning("haul_field_cache status=write_failed key=%s reason=%s", key[:12], exc)
    elapsed = perf_counter() - started
    _LOGGER.info(
        "haul_field_cache status=built key=%s elapsed_s=%.3f build_s=%.3f",
        key[:12],
        elapsed,
        build_seconds,
    )
    return HaulFieldCacheResult(field, "built", key, elapsed, build_seconds)


def _cache_key(
    directory: Path,
    signature: tuple[tuple[str, int, int], ...],
    constraints_json: str,
    origin: tuple[float, float] | None,
    dem: np.ndarray,
    buildable: np.ndarray,
    segments: np.ndarray,
    diagonal: bool = False,
    access_elevation_weight: float = 1.0,
    *,
    network: RoadNetwork | None = None,
    routes: RoadOriginRoutes | None = None,
    connector_blocked: np.ndarray | None = None,
) -> str:
    network = network if network is not None else RoadNetwork(segments)
    projection = None if origin is None else (routes.origin_projection if routes is not None else network.project(origin))
    component = None if projection is None or network.component_count == 1 else network.component(projection)
    payload = {
        "version": _CACHE_VERSION,
        "scene": str(directory),
        "source_signature": signature,
        "constraints": constraints_json,
        "road_component": component,
        "dem": _array_identity(dem),
        "buildable": _array_identity(buildable),
        "segments": _array_identity(segments),
        "access_elevation_weight": float(access_elevation_weight),
    }
    if diagonal:
        payload["diagonal"] = True
    if connector_blocked is not None:
        payload["connector_blocked"] = _array_identity(np.asarray(connector_blocked, dtype=bool))
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _array_identity(value: np.ndarray) -> dict[str, Any]:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(memoryview(array).cast("B"))
    return {"shape": list(array.shape), "dtype": array.dtype.str, "sha256": digest.hexdigest()}


def _write_field(root: Path, target: Path, key: str, field: HaulField) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        return
    temporary = Path(tempfile.mkdtemp(prefix=f".{key[:12]}-", dir=root))
    try:
        arrays = {name: getattr(field, name) for name in {**_ARRAY_DTYPES, **_ORDER_DTYPES}}
        if any(value is None for value in arrays.values()):
            raise ValueError("haul field is missing route reconstruction arrays")
        for name, value in arrays.items():
            np.save(temporary / f"{name}.npy", np.asarray(value), allow_pickle=False)
        if field.road_m is not None:
            np.save(temporary / "road_m.npy", field.road_m, allow_pickle=False)
        manifest = {
            "version": _CACHE_VERSION,
            "key": key,
            "shape": list(field.dem.shape),
            "has_road_m": field.road_m is not None,
            "origin": field.origin,
            "diagonal": field.diagonal,
            "gate_count": int(field.gate_count),
            "reachable_gate_count": int(field.reachable_gate_count),
            "unreachable_gate_count": int(field.unreachable_gate_count),
            "access_elevation_weight": float(field.access_elevation_weight),
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        try:
            temporary.rename(target)
        except FileExistsError:
            pass
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _load_field(
    target: Path,
    key: str,
    dem: np.ndarray,
    buildable: np.ndarray,
    segments: np.ndarray,
    origin: tuple[float, float] | None,
    access_elevation_weight: float,
    *,
    routes: RoadOriginRoutes | None = None,
) -> HaulField:
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != _CACHE_VERSION or manifest.get("key") != key:
        raise ValueError("incompatible haul field cache manifest")
    if float(manifest["access_elevation_weight"]) != access_elevation_weight:
        raise ValueError("cached haul field uses a different access elevation weight")
    shape = tuple(int(value) for value in manifest["shape"])
    if shape != dem.shape or buildable.shape != dem.shape:
        raise ValueError("cached haul field shape does not match the scene")
    arrays: dict[str, np.ndarray] = {}
    for name, dtype in {**_ARRAY_DTYPES, **_ORDER_DTYPES}.items():
        value = np.load(target / f"{name}.npy", allow_pickle=False)
        if value.dtype != dtype:
            raise ValueError(f"cached {name} has dtype {value.dtype}, expected {dtype}")
        arrays[name] = value
    for name in ("offroad_m", "access_rise_m", "reachable", "road_cells", "predecessor", "gate_owner"):
        if arrays[name].shape != shape:
            raise ValueError(f"cached {name} has the wrong shape")
    gate_count = int(manifest["gate_count"])
    if arrays["gate_cells"].shape != (gate_count, 2) or arrays["gate_contacts"].shape != (gate_count, 2):
        raise ValueError("cached gate coordinates have the wrong shape")
    for name in ("gate_contact_edges", "gate_reachable", "gate_road_m", "gate_offroad_m", "gate_rise_m"):
        if arrays[name].shape != (gate_count,):
            raise ValueError(f"cached {name} has the wrong shape")
    has_road_m = bool(manifest["has_road_m"])
    road_m = np.load(target / "road_m.npy", allow_pickle=False) if has_road_m else None
    if road_m is not None and (road_m.dtype != np.float64 or road_m.shape != shape):
        raise ValueError("cached road_m has the wrong dtype or shape")
    stored_origin = None if manifest["origin"] is None else tuple(float(value) for value in manifest["origin"])
    if has_road_m != (stored_origin is not None):
        raise ValueError("cached haul field origin mode does not match")

    _check_access_order(arrays, shape, bool(manifest["diagonal"]))
    road_cells = frozenset((int(row), int(col)) for row, col in np.argwhere(arrays["road_cells"]))
    gates = frozenset((int(row), int(col)) for row, col in arrays["gate_cells"])
    geometry = ApproachGrid(road_cells=road_cells, gates=gates, shape=shape, buildable=buildable)
    if routes is None and origin is not None:
        routes = RoadNetwork(segments).routes_from(origin)
    field = HaulField(
        dem=dem,
        buildable=buildable,
        segments=segments,
        origin=stored_origin,
        offroad_m=arrays["offroad_m"],
        access_rise_m=arrays["access_rise_m"],
        road_m=road_m,
        reachable=arrays["reachable"],
        road_cells=arrays["road_cells"],
        geometry=geometry,
        access_elevation_weight=access_elevation_weight,
        road_routes=routes,
        gate_count=gate_count,
        reachable_gate_count=int(manifest["reachable_gate_count"]),
        unreachable_gate_count=int(manifest["unreachable_gate_count"]),
        predecessor=arrays["predecessor"],
        gate_owner=arrays["gate_owner"],
        gate_cells=arrays["gate_cells"],
        gate_contacts=arrays["gate_contacts"],
        gate_contact_edges=arrays["gate_contact_edges"],
        gate_reachable=arrays["gate_reachable"],
        gate_road_m=arrays["gate_road_m"],
        gate_offroad_m=arrays["gate_offroad_m"],
        gate_rise_m=arrays["gate_rise_m"],
        diagonal=bool(manifest["diagonal"]),
        access_order=arrays["access_order"],
    )
    return bind_haul_origin(field, routes)


def _check_access_order(arrays: dict[str, np.ndarray], shape: tuple[int, ...], diagonal: bool) -> None:
    order = arrays["access_order"]
    reachable = arrays["reachable"].ravel()
    if order.ndim != 1 or len(order) != np.count_nonzero(reachable) or np.any(order < 0) or np.any(order >= reachable.size):
        raise ValueError("cached settlement order has the wrong shape or range")
    rank = np.full(reachable.size, -1, dtype=np.int32)
    rank[order] = np.arange(len(order), dtype=np.int32)
    if not np.array_equal(rank >= 0, reachable):
        raise ValueError("cached settlement order does not cover reachable cells exactly")
    owner = arrays["gate_owner"].ravel()
    if np.any(owner[order] < 0) or np.any(owner[order] >= len(arrays["gate_cells"])):
        raise ValueError("cached gate ownership is invalid")
    codes = arrays["predecessor"].ravel()[order]
    if np.any(codes < 1) or np.any(codes > (9 if diagonal else 5)):
        raise ValueError("cached predecessor codes are invalid")
    roots = order[codes == 1]
    gate_cells = arrays["gate_cells"][owner[roots]]
    if np.any(roots != gate_cells[:, 0] * shape[1] + gate_cells[:, 1]) or not np.all(arrays["gate_reachable"][owner[order]]):
        raise ValueError("cached roots do not match reachable gates")
    cells, codes = order[codes != 1], codes[codes != 1]
    dr = np.asarray([0, 0, -1, 1, 0, 0, -1, -1, 1, 1])[codes]
    dc = np.asarray([0, 0, 0, 0, -1, 1, -1, 1, -1, 1])[codes]
    rows, cols = cells // shape[1] + dr, cells % shape[1] + dc
    if np.any(rows < 0) or np.any(rows >= shape[0]) or np.any(cols < 0) or np.any(cols >= shape[1]):
        raise ValueError("cached predecessors leave the grid")
    parents = rows * shape[1] + cols
    if np.any(rank[parents] < 0) or np.any(rank[parents] >= rank[cells]) or np.any(owner[parents] != owner[cells]):
        raise ValueError("cached settlement order does not follow predecessors")


def _discard_cache_entry(root: Path, target: Path) -> None:
    try:
        if target.parent.resolve() == root.resolve() and target.is_dir():
            shutil.rmtree(target)
    except OSError:
        _LOGGER.warning("haul_field_cache could not remove invalid entry %s", target.name)


def _prune_cache(root: Path, *, protected: Path) -> None:
    entries = [
        path for path in root.iterdir()
        if path.is_dir() and len(path.name) == 64 and (path / "manifest.json").is_file()
    ]
    entries.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    kept_bytes = 0
    kept_count = 0
    for entry in entries:
        size = sum(path.stat().st_size for path in entry.iterdir() if path.is_file())
        keep = entry == protected or (kept_count < _MAX_ENTRIES and kept_bytes + size <= _MAX_BYTES)
        if keep:
            kept_count += 1
            kept_bytes += size
            continue
        _discard_cache_entry(root, entry)
