"""Bounded in-process cache for the construction-feasibility PNG.

The mask still comes from ``compose_constraint_masks``, farmland burning, and the
same 1 m distance comparison as ``compose_building_hard_mask``. Large grids skip
the distance-field cache. Their setback is the same Euclidean disk, painted from
the source boundary instead of a full distance field, and only the PNG is kept.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from config.project_config import load_default_config
from experiments.constraint_mask import compose_hard_mask, polygons_from_form, policy_from_form
from experiments.protected_farmland import farmland_file_signature, load_mask
from experiments.scene_store import scene_directory, scenes_root
from modeling.context import (
    mask_within_distance,
    highway_building_buffer,
    rasterize_osm_centerlines,
    require_road_setback_m,
    require_water_setback_m,
    road_setback_distance,
    road_setback_source,
    water_setback_distance,
    water_setback_source,
)

try:
    from numba import njit
except ImportError:  # pragma: no cover - the documented environment includes numba
    njit = None

_LOGGER = logging.getLogger("uvicorn.error")
_PNG_MAX_ENTRIES = 2
_PNG_MAX_BYTES = 96 * 1024 * 1024
_BASE_MAX_ENTRIES = 1
# Two float64 distance fields of this size are about 64 MB. Larger scenes recompute.
_BASE_MAX_CELLS = 4_000_000
# Boundary cells times disk area. Above this the full distance field is cheaper.
_PAINT_BUDGET = 500_000_000
_ALLOWED = (45, 184, 138, 38)
_BLOCKED = (235, 98, 109, 89)
_DISKS: dict[float, tuple[np.ndarray, np.ndarray]] = {}

if njit is not None:

    @njit(cache=True)
    def _paint_disk(ys, xs, out, di, dj):
        """Stamp a 1 m Euclidean disk onto each boundary cell. Writes only True."""

        height, width = out.shape
        offsets = di.shape[0]
        for index in range(ys.shape[0]):
            row = ys[index]
            col = xs[index]
            for offset in range(offsets):
                ii = row + di[offset]
                jj = col + dj[offset]
                if ii < 0 or jj < 0 or ii >= height or jj >= width:
                    continue
                out[ii, jj] = True

else:  # pragma: no cover
    _paint_disk = None


def cells_within_setback(
    source: np.ndarray | None,
    setback_m: float,
    shape: tuple[int, int],
) -> np.ndarray:
    """Cells with 1 m EDT distance ``<= setback_m``.

    A full distance field is unnecessary for a short radius: dilating the
    8-connected boundary by that disk, then keeping the source, matches
    ``distance_transform_edt(~source) <= setback_m``.
    """

    if source is None:
        return np.zeros(shape, dtype=bool)
    blocked = np.asarray(source, dtype=bool)
    if blocked.shape != shape:
        raise ValueError(f"setback source shape {blocked.shape} does not match {shape}")
    if setback_m <= 0 or not blocked.any():
        return blocked
    if _paint_disk is None:
        return _edt_within(blocked, setback_m)
    di, dj = _disk_offsets(float(setback_m))
    from scipy.ndimage import binary_erosion

    # Outside the grid is not a source, so border cells stay on the boundary.
    eroded = binary_erosion(blocked, structure=np.ones((3, 3), dtype=bool), border_value=0)
    boundary = np.logical_and(blocked, np.logical_not(eroded))
    if int(boundary.sum()) * int(di.shape[0]) > _PAINT_BUDGET:
        return _edt_within(blocked, setback_m)
    out = blocked.copy()
    rows, cols = np.nonzero(boundary)
    _paint_disk(rows, cols, out, di, dj)
    return out


def _edt_within(source: np.ndarray, setback_m: float) -> np.ndarray:
    from scipy.ndimage import distance_transform_edt

    return distance_transform_edt(~source, sampling=(1.0, 1.0)) <= setback_m


def _disk_offsets(radius: float) -> tuple[np.ndarray, np.ndarray]:
    cached = _DISKS.get(radius)
    if cached is not None:
        return cached
    limit = int(np.ceil(radius))
    ys, xs = np.ogrid[-limit : limit + 1, -limit : limit + 1]
    keep = (ys.astype(np.int64) * ys + xs.astype(np.int64) * xs) <= radius * radius
    row, col = np.nonzero(keep)
    offsets = ((row - limit).astype(np.int16), (col - limit).astype(np.int16))
    _DISKS[radius] = offsets
    return offsets


_LOCK = threading.Lock()
_PNG: OrderedDict[tuple[Any, ...], tuple[bytes, int, int]] = OrderedDict()
_PNG_INFLIGHT: dict[tuple[Any, ...], dict[str, Any]] = {}
_BASE: OrderedDict[tuple[Any, ...], "SceneBase"] = OrderedDict()
_BASE_INFLIGHT: dict[tuple[Any, ...], dict[str, Any]] = {}


@dataclass
class SceneBase:
    landuse: np.ndarray
    osm: np.ndarray
    highway: np.ndarray
    farmland: np.ndarray | None
    road_distance: np.ndarray | None
    water_distance: np.ndarray | None
    cacheable: bool
    load_s: float
    road_raster_s: float
    road_edt_s: float
    water_edt_s: float


def render_construction_feasibility_png(
    scene_name: str,
    form: dict[str, Any],
    root: str | Path | None = None,
) -> bytes:
    scene_dir = scene_directory(scenes_root(root), scene_name)
    landuse_path = scene_dir / "landuse_1m.npy"
    segments_path = scene_dir / "road_segments_local.npy"
    if not landuse_path.is_file():
        raise FileNotFoundError(f"场景 {scene_name} 缺少 landuse_1m.npy")
    if not segments_path.is_file():
        raise FileNotFoundError(f"场景 {scene_name} 缺少 road_segments_local.npy")
    policy = policy_from_form(form)
    exclusions = polygons_from_form(form)
    feasible = polygons_from_form(form, "feasible_zones")
    road_setback = require_road_setback_m(form.get("road_setback_m", load_default_config().modeling.road_setback_m))
    water_setback = require_water_setback_m(form.get("water_setback_m", load_default_config().modeling.water_setback_m))
    highway_setback = require_road_setback_m(form.get("highway_setback_m", load_default_config().modeling.highway_setback_m))
    signature = _scene_signature(scene_dir, highway_setback)
    key = (signature, _form_token(form, policy, exclusions, feasible, road_setback, water_setback))
    started = perf_counter()
    kind, cached, slot = _claim_png(key)
    if kind == "hit":
        assert cached is not None
        _log(scene_name, cached[1], cached[2], "hit", "hit", 0, 0, 0, 0, 0, 0, perf_counter() - started)
        return cached[0]
    if kind == "wait":
        assert slot is not None
        slot["event"].wait()
        if slot["error"] is not None:
            raise slot["error"]
        content = slot["content"]
        height, width = slot["shape"]
        _log(scene_name, height, width, "hit", "hit", 0, 0, 0, 0, 0, 0, perf_counter() - started)
        return content
    assert slot is not None
    try:
        content, height, width, status, base_status, timings = _render(
            scene_dir,
            signature,
            policy,
            exclusions,
            feasible,
            road_setback,
            water_setback,
            highway_setback,
        )
        with _LOCK:
            _remember_png(key, content, height, width)
            slot["content"] = content
            slot["shape"] = (height, width)
        _log(scene_name, height, width, status, base_status, *timings, perf_counter() - started)
        return content
    except Exception as exc:
        slot["error"] = exc
        raise
    finally:
        with _LOCK:
            _PNG_INFLIGHT.pop(key, None)
        slot["event"].set()


def _render(
    scene_dir: Path,
    signature: tuple[Any, ...],
    policy: Any,
    exclusions: list[list[tuple[float, float]]],
    feasible: list[list[tuple[float, float]]],
    road_setback: float,
    water_setback: float,
    highway_setback: float,
) -> tuple[bytes, int, int, str, str, tuple[float, float, float, float, float, float]]:
    base, base_status = _scene_base(scene_dir, signature, highway_setback)
    started = perf_counter()
    blocked = compose_hard_mask(base.landuse, exclusions, policy, feasible)
    if base.farmland is not None:
        blocked |= np.asarray(base.farmland, dtype=bool)
    constraint_s = perf_counter() - started
    shape = base.landuse.shape
    if base.cacheable:
        road_buffer = mask_within_distance(base.road_distance, road_setback, shape)
        water_buffer = mask_within_distance(base.water_distance, water_setback, shape)
        road_paint_s = water_paint_s = 0.0
    else:
        started = perf_counter()
        road_buffer = cells_within_setback(
            road_setback_source(base.landuse, base.osm), road_setback, shape
        )
        road_paint_s = perf_counter() - started
        started = perf_counter()
        water_buffer = cells_within_setback(
            water_setback_source(base.landuse), water_setback, shape
        )
        water_paint_s = perf_counter() - started
    blocked |= road_buffer
    blocked |= water_buffer
    blocked |= base.highway
    started = perf_counter()
    content = _encode_png(blocked)
    png_s = perf_counter() - started
    if base_status == "hit":
        load_s = road_raster_s = road_edt_s = water_edt_s = 0.0
        status = "miss"
    else:
        load_s = base.load_s
        road_raster_s = base.road_raster_s
        road_edt_s = base.road_edt_s + road_paint_s
        water_edt_s = base.water_edt_s + water_paint_s
        status = "bypass" if base_status == "bypass" else "miss"
    return content, int(shape[0]), int(shape[1]), status, base_status, (
        load_s, constraint_s, road_raster_s, road_edt_s, water_edt_s, png_s,
    )


def _scene_base(scene_dir: Path, signature: tuple[Any, ...], highway_setback: float) -> tuple[SceneBase, str]:
    kind, cached, slot = _claim_base(signature)
    if kind == "hit":
        assert cached is not None
        return cached, "hit"
    if kind == "wait":
        assert slot is not None
        slot["event"].wait()
        if slot["error"] is not None:
            raise slot["error"]
        return slot["base"], "hit"
    assert slot is not None
    try:
        base = _load_scene_base(scene_dir, highway_setback)
        with _LOCK:
            if base.cacheable:
                _remember_base(signature, base)
            slot["base"] = base
        return base, "stored" if base.cacheable else "bypass"
    except Exception as exc:
        slot["error"] = exc
        raise
    finally:
        with _LOCK:
            _BASE_INFLIGHT.pop(signature, None)
        slot["event"].set()


def _load_scene_base(scene_dir: Path, highway_setback: float) -> SceneBase:
    started = perf_counter()
    landuse = np.load(scene_dir / "landuse_1m.npy")
    segments = np.load(scene_dir / "road_segments_local.npy")
    kinds = np.load(scene_dir / "road_segment_kind.npy")
    load_s = perf_counter() - started
    if landuse.ndim != 2 or landuse.size == 0:
        raise ValueError(f"landuse must be a non-empty 2D array, got {landuse.shape}")
    started = perf_counter()
    osm = rasterize_osm_centerlines(segments[kinds == 0], landuse.shape)
    from config.project_config import load_default_config
    highway = highway_building_buffer(segments, kinds, landuse.shape, highway_setback)
    road_raster_s = perf_counter() - started
    farmland = load_mask(scene_dir, landuse.shape)
    cells = int(landuse.shape[0]) * int(landuse.shape[1])
    cacheable = cells <= _BASE_MAX_CELLS
    if cacheable:
        started = perf_counter()
        road_distance = road_setback_distance(landuse, osm)
        road_edt_s = perf_counter() - started
        started = perf_counter()
        water_distance = water_setback_distance(landuse)
        water_edt_s = perf_counter() - started
    else:
        road_distance = water_distance = None
        road_edt_s = water_edt_s = 0.0
    return SceneBase(
        landuse=landuse,
        osm=osm,
        highway=highway,
        farmland=farmland,
        road_distance=road_distance,
        water_distance=water_distance,
        cacheable=cacheable,
        load_s=load_s,
        road_raster_s=road_raster_s,
        road_edt_s=road_edt_s,
        water_edt_s=water_edt_s,
    )


def _encode_png(building_mask: np.ndarray) -> bytes:
    from io import BytesIO

    from PIL import Image

    # Two colors only. A palette PNG keeps the same RGBA values and encodes faster.
    index = np.zeros(building_mask.shape, dtype=np.uint8)
    index[np.asarray(building_mask) > 0] = 1
    image = Image.fromarray(index, mode="P")
    image.putpalette([*_ALLOWED[:3], *_BLOCKED[:3]])
    output = BytesIO()
    image.save(
        output,
        format="PNG",
        compress_level=1,
        transparency=bytes((_ALLOWED[3], _BLOCKED[3])),
    )
    return output.getvalue()


def _scene_signature(scene_dir: Path, highway_setback: float) -> tuple[Any, ...]:
    from config.project_config import load_default_config
    return (
        str(scene_dir.resolve()),
        _file_stat(scene_dir / "landuse_1m.npy"),
        _file_stat(scene_dir / "road_segments_local.npy"),
        farmland_file_signature(scene_dir),
        _file_stat(scene_dir / "road_segment_kind.npy"),
        highway_setback,
    )


def _file_stat(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _form_token(
    form: dict[str, Any],
    policy: Any,
    exclusions: list[list[tuple[float, float]]],
    feasible: list[list[tuple[float, float]]],
    road_setback: float,
    water_setback: float,
) -> str:
    raw_cost = form.get("field_cost", None)
    try:
        field_cost: Any = None if raw_cost is None else float(raw_cost)
    except (TypeError, ValueError):
        field_cost = str(raw_cost)
    payload = {
        "mountain_policy": form.get("mountain_policy"),
        "field_policy": form.get("field_policy"),
        "field_cost": field_cost,
        "hard_classes": list(policy.hard_classes),
        "costly": [[class_id, cost] for class_id, cost in policy.costly],
        "exclusion_zones": exclusions,
        "feasible_zones": feasible,
        "road_setback_m": road_setback,
        "water_setback_m": water_setback,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _claim_png(
    key: tuple[Any, ...],
) -> tuple[str, tuple[bytes, int, int] | None, dict[str, Any] | None]:
    with _LOCK:
        cached = _PNG.get(key)
        if cached is not None:
            _PNG.move_to_end(key)
            return "hit", cached, None
        slot = _PNG_INFLIGHT.get(key)
        if slot is not None:
            return "wait", None, slot
        slot = {"event": threading.Event(), "content": None, "shape": (0, 0), "error": None}
        _PNG_INFLIGHT[key] = slot
        return "owner", None, slot


def _claim_base(
    key: tuple[Any, ...],
) -> tuple[str, SceneBase | None, dict[str, Any] | None]:
    with _LOCK:
        cached = _BASE.get(key)
        if cached is not None:
            _BASE.move_to_end(key)
            return "hit", cached, None
        slot = _BASE_INFLIGHT.get(key)
        if slot is not None:
            return "wait", None, slot
        slot = {"event": threading.Event(), "base": None, "error": None}
        _BASE_INFLIGHT[key] = slot
        return "owner", None, slot


def _remember_png(key: tuple[Any, ...], content: bytes, height: int, width: int) -> None:
    _PNG[key] = (content, height, width)
    _PNG.move_to_end(key)
    while len(_PNG) > _PNG_MAX_ENTRIES or (len(_PNG) > 1 and _png_bytes() > _PNG_MAX_BYTES):
        _PNG.popitem(last=False)


def _remember_base(key: tuple[Any, ...], base: SceneBase) -> None:
    _BASE[key] = base
    _BASE.move_to_end(key)
    while len(_BASE) > _BASE_MAX_ENTRIES:
        _BASE.popitem(last=False)


def _png_bytes() -> int:
    return sum(len(item[0]) for item in _PNG.values())


def _log(
    scene_name: str,
    height: int,
    width: int,
    cache_status: str,
    base_status: str,
    load_s: float,
    constraint_s: float,
    road_raster_s: float,
    road_edt_s: float,
    water_edt_s: float,
    png_s: float,
    total_s: float,
) -> None:
    _LOGGER.info(
        "construction_feasibility scene=%s grid=%sx%s cache_status=%s base=%s "
        "load_ms=%.1f constraint_ms=%.1f road_raster_ms=%.1f road_edt_ms=%.1f "
        "water_edt_ms=%.1f png_ms=%.1f total_ms=%.1f",
        scene_name,
        height,
        width,
        cache_status,
        base_status,
        load_s * 1000.0,
        constraint_s * 1000.0,
        road_raster_s * 1000.0,
        road_edt_s * 1000.0,
        water_edt_s * 1000.0,
        png_s * 1000.0,
        total_s * 1000.0,
    )
