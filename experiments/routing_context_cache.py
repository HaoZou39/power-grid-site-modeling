"""One bounded, read-only raster entry; task endpoints and polygons are excluded."""

import threading

RASTER_FIELDS = ("dem", "landuse", "road_control", "tower_blocked", "crossing_mask")


class RoutingRasterCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._key = None
        self._rasters = None
        self._bytes = 0

    def get(self, key, max_bytes, build):
        with self._lock:
            if key is not None and max_bytes > 0 and key == self._key and self._bytes <= max_bytes:
                return self._rasters, True, self._bytes
            problem = build()
            rasters = {name: getattr(problem, name) for name in RASTER_FIELDS}
            size = sum(array.nbytes for array in rasters.values())
            if key is not None and size <= max_bytes:
                self._key, self._rasters, self._bytes = key, rasters, size
            else:
                self._key, self._rasters, self._bytes = None, None, 0
            return rasters, False, size


RASTER_CACHE = RoutingRasterCache()
