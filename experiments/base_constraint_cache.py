"""Process-local boolean masks for setbacks that do not depend on drawn zones.

A hit returns the stored read-only array. The float64 distance field is not kept.
Callers that cannot prove the arrays came from a file snapshot must compute directly.
"""

from __future__ import annotations

import threading
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

_VERSION = "base-constraint-bool-v1"
# One 9000×9000 scene stores four bool masks, about 309 MiB. A second large scene evicts the older one.
_MAX_BYTES = 400 * 1024 * 1024
_MAX_ENTRIES = 16


@dataclass(frozen=True)
class FileStamp:
    """Size and nanosecond mtime of one source file. This is not a content hash."""

    path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class SceneBufferSources:
    """Identity of the land-use grid and road files loaded with the arrays."""

    landuse: FileStamp
    segments: FileStamp
    kinds: FileStamp
    shape: tuple[int, int]


def stamp_file(path: str | Path) -> FileStamp | None:
    file = Path(path)
    if not file.is_file():
        return None
    stat = file.stat()
    return FileStamp(str(file.resolve()), stat.st_size, stat.st_mtime_ns)


def scene_buffer_sources(scene_dir: str | Path, shape: tuple[int, int]) -> SceneBufferSources | None:
    directory = Path(scene_dir)
    landuse = stamp_file(directory / "landuse_1m.npy")
    segments = stamp_file(directory / "road_segments_local.npy")
    kinds = stamp_file(directory / "road_segment_kind.npy")
    if landuse is None or segments is None or kinds is None or len(shape) != 2:
        return None
    return SceneBufferSources(landuse, segments, kinds, (int(shape[0]), int(shape[1])))


class _Flight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: np.ndarray | None = None
        self.error: BaseException | None = None


class BaseConstraintCache:
    """LRU of read-only bool masks. The lock covers the map only, not the distance transform."""

    def __init__(self, max_bytes: int = _MAX_BYTES, max_entries: int = _MAX_ENTRIES) -> None:
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._items: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self._inflight: dict[tuple, _Flight] = {}
        self.hits = 0
        self.misses = 0

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0
            self.hits = 0
            self.misses = 0

    def info(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "entries": len(self._items),
                "bytes": self._bytes,
            }

    def get_or_compute(self, key: tuple, compute: Callable[[], np.ndarray]) -> np.ndarray:
        with self._lock:
            cached = self._items.get(key)
            if cached is not None:
                self._items.move_to_end(key)
                self.hits += 1
                return cached
            flight = self._inflight.get(key)
            if flight is None:
                flight = _Flight()
                self._inflight[key] = flight
                owner = True
            else:
                owner = False
        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            with self._lock:
                self.hits += 1
            return flight.value  # type: ignore[return-value]
        try:
            sealed = _seal(compute())
        except Exception as exc:
            flight.error = exc
            with self._lock:
                self._inflight.pop(key, None)
            flight.event.set()
            raise
        flight.value = sealed
        with self._lock:
            self._store(key, sealed)
            self.misses += 1
            self._inflight.pop(key, None)
        flight.event.set()
        return sealed

    def _store(self, key: tuple, mask: np.ndarray) -> None:
        size = int(mask.nbytes)
        if size > self.max_bytes or self.max_entries < 1:
            return
        previous = self._items.pop(key, None)
        if previous is not None:
            self._bytes -= int(previous.nbytes)
        self._items[key] = mask
        self._bytes += size
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries or (len(self._items) > 1 and self._bytes > self.max_bytes):
            _, evicted = self._items.popitem(last=False)
            self._bytes -= int(evicted.nbytes)


def _seal(array: np.ndarray) -> np.ndarray:
    mask = np.asarray(array)
    if mask.dtype != np.bool_ or not mask.flags.owndata or not mask.flags.c_contiguous:
        mask = np.array(mask, dtype=bool, copy=True)
    mask.setflags(write=False)
    return mask


_CACHE = BaseConstraintCache()


def clear_base_constraint_cache() -> None:
    _CACHE.clear()


def base_constraint_cache_info() -> dict[str, int]:
    return _CACHE.info()


def _content_key(*arrays: np.ndarray) -> tuple:
    result = []
    for array in arrays:
        contiguous = np.ascontiguousarray(array)
        digest = hashlib.sha256(contiguous.reshape(-1).view(np.uint8)).digest()
        result.append((contiguous.shape, contiguous.dtype.str, digest))
    return tuple(result)


def cached_road_buffer(
    sources: SceneBufferSources,
    setback_m: float,
    landuse: np.ndarray,
    osm_road_mask: np.ndarray,
) -> np.ndarray:
    from modeling.context import require_road_setback_m, road_building_buffer

    setback = require_road_setback_m(setback_m)
    key = (_VERSION, "road", sources.landuse, sources.segments, sources.kinds, setback, sources.shape,
           _content_key(landuse, osm_road_mask))
    return _CACHE.get_or_compute(key, lambda: road_building_buffer(landuse, osm_road_mask, setback))


def cached_water_buffer(sources: SceneBufferSources, setback_m: float, landuse: np.ndarray) -> np.ndarray:
    from modeling.context import require_water_setback_m, water_building_buffer

    setback = require_water_setback_m(setback_m)
    key = (_VERSION, "water", sources.landuse, setback, sources.shape, _content_key(landuse))
    return _CACHE.get_or_compute(key, lambda: water_building_buffer(landuse, setback))


def cached_highway_buffer(
    sources: SceneBufferSources,
    setback_m: float,
    segments: np.ndarray,
    kinds: np.ndarray,
    shape: tuple[int, int],
) -> np.ndarray:
    from modeling.context import highway_building_buffer, require_road_setback_m

    setback = require_road_setback_m(setback_m)
    key = (_VERSION, "highway", sources.segments, sources.kinds, setback, sources.shape,
           _content_key(segments, kinds))
    return _CACHE.get_or_compute(key, lambda: highway_building_buffer(segments, kinds, shape, setback))


def cached_farmland_buffer(stamp: FileStamp, width_m: float, shape: tuple[int, int],
                           compute: Callable[[], np.ndarray], *, content_sha256: str) -> np.ndarray:
    key = (_VERSION, "farmland", stamp, content_sha256, float(width_m), (int(shape[0]), int(shape[1])))
    return _CACHE.get_or_compute(key, compute)
