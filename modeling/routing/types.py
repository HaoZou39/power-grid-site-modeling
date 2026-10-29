"""Metric routing inputs and records. Endpoints are never chromosome genes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

import numpy as np
from pyproj import CRS

from data_tools.scene_coordinates import local_to_lonlat, lonlat_to_local

OBJECTIVE_NAMES = ("tower_count", "length_3d_m", "bend_sum_rad", "crossing_3d_m")


@dataclass(frozen=True)
class RoutingConstraints:
    max_span_m: float
    tower_radius_m: float
    max_turn_deg: float
    road_setback_m: float
    highway_setback_m: float

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if self.max_span_m <= 0 or self.tower_radius_m <= 0:
            raise ValueError("max_span_m and tower_radius_m must be positive")
        if not 0 <= self.max_turn_deg <= 180:
            raise ValueError("max_turn_deg must be in [0, 180]")
        if min(self.road_setback_m, self.highway_setback_m) < 0:
            raise ValueError("road setbacks must be non-negative")


@dataclass(frozen=True)
class RoutingFrame:
    crs: str
    transform: tuple[float, ...]
    width: int
    height: int

    def __post_init__(self) -> None:
        crs = CRS.from_user_input(self.crs)
        if crs.to_epsg() not in {*range(32601, 32661), *range(32701, 32761)}:
            raise ValueError("routing requires a WGS84 UTM metric grid")
        if len(self.transform) != 6 or not np.isfinite(self.transform).all():
            raise ValueError("routing frame requires six finite affine values")
        a, b, _c, d, e, _f = self.transform
        if (a, b, d, e) != (1, 0, 0, -1):
            raise ValueError("routing requires an unrotated 1 m grid")
        if any(type(value) is not int or value < 2 for value in (self.width, self.height)):
            raise ValueError("routing frame dimensions must be integers >= 2")

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> RoutingFrame:
        dem = metadata["dem"]
        height, width = dem["shape"]
        return cls(dem["reference_crs"], tuple(dem["target_transform"]), int(width), int(height))

    def validate_point(self, point: Any) -> np.ndarray:
        result = np.asarray(point, dtype=np.float64)
        if result.shape != (2,) or not np.isfinite(result).all():
            raise ValueError("connection point must contain two finite coordinates")
        if not (0 <= result[0] <= self.width and 0 <= result[1] <= self.height):
            raise ValueError("connection point is outside the scene")
        return result

    def to_local(self, lng: float, lat: float) -> np.ndarray:
        if not np.isfinite([lng, lat]).all() or not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise ValueError("invalid WGS84 longitude/latitude")
        return self.validate_point(lonlat_to_local(self._coordinate_frame(), lng, lat))

    def to_wgs84(self, point: Any) -> tuple[float, float]:
        x, y = self.validate_point(point)
        return local_to_lonlat(self._coordinate_frame(), float(x), float(y))

    def _coordinate_frame(self) -> dict[str, Any]:
        return {"crs": self.crs, "transform": self.transform}


@dataclass(frozen=True)
class Route:
    towers: np.ndarray

    def __post_init__(self) -> None:
        points = np.array(self.towers, dtype=np.float64, copy=True)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError("tower coordinates must be finite [N, 2]")
        points.flags.writeable = False
        object.__setattr__(self, "towers", points)

    def points(self, start: Any, end: Any) -> np.ndarray:
        return np.vstack([start, self.towers, end])


@dataclass
class RouteEvaluation:
    objectives: np.ndarray
    violations: dict[str, float]
    violation: float
    elevations: np.ndarray
    spans: list[dict[str, float]]
    tower_slopes_deg: list[float]

    def compact(self):
        return RouteEvaluation(self.objectives, self.violations, self.violation, np.empty(0), [], [])

    @property
    def is_feasible(self) -> bool:
        return all(value == 0 for value in self.violations.values())
