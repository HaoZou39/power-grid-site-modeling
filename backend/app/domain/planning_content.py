"""Current site and routing inputs saved on one workspace. Not a replayable history."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PLAN_BYTE_LIMIT = 256 * 1024
COORD_LIMIT = 10_000_000
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_UNSAFE_TEXT = re.compile(r"[\x00-\x1f/\\:]|\.\.")


class PlanRevisionConflict(Exception):
    pass


class PlanNotWritable(Exception):
    pass


class PlanTooLarge(Exception):
    pass


class PlanInvalid(Exception):
    pass


def canonical_plan(document: dict) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _finite_text(value: str) -> bool:
    try:
        number = float(value)
    except ValueError:
        return False
    return math.isfinite(number)


def _orientation(start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]) -> int:
    first = (end[0] - start[0]) * (point[1] - start[1])
    second = (end[1] - start[1]) * (point[0] - start[0])
    cross = first - second
    tolerance = math.ulp(1.0) * 16 * (abs(first) + abs(second))
    if abs(cross) <= tolerance:
        return 0
    return 1 if cross > 0 else -1


def _on_segment(start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]) -> bool:
    return (
        _orientation(start, end, point) == 0
        and min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
        and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
    )


def _segments_cross(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
    fourth: tuple[float, float],
) -> bool:
    abc = _orientation(first, second, third)
    abd = _orientation(first, second, fourth)
    cda = _orientation(third, fourth, first)
    cdb = _orientation(third, fourth, second)
    return (abc * abd < 0 and cda * cdb < 0) or (
        (abc == 0 and _on_segment(first, second, third))
        or (abd == 0 and _on_segment(first, second, fourth))
        or (cda == 0 and _on_segment(third, fourth, first))
        or (cdb == 0 and _on_segment(third, fourth, second))
    )


def _checked_ring(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Reject a ring that cannot be a closed zone. The stored points stay unchanged."""
    if any(not math.isfinite(x) or not math.isfinite(y) or abs(x) > COORD_LIMIT or abs(y) > COORD_LIMIT for x, y in points):
        raise ValueError("区域坐标无效")
    ring = [points[0]]
    for point in points[1:]:
        if point != ring[-1]:
            ring.append(point)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        raise ValueError("区域至少需要三个不同的顶点")
    area = 0.0
    for index, current in enumerate(ring):
        previous = ring[(index - 1) % len(ring)]
        nxt = ring[(index + 1) % len(ring)]
        area += (current[0] - ring[0][0]) * (nxt[1] - ring[0][1]) - (current[1] - ring[0][1]) * (nxt[0] - ring[0][0])
        if _orientation(previous, current, nxt) == 0 and (
            (previous[0] - current[0]) * (nxt[0] - current[0]) + (previous[1] - current[1]) * (nxt[1] - current[1]) > 0
        ):
            raise ValueError("区域边界不能重叠或交叉")
        for other in range(index + 1, len(ring)):
            if other == index + 1 or (index == 0 and other == len(ring) - 1):
                continue
            if _segments_cross(current, nxt, ring[other], ring[(other + 1) % len(ring)]):
                raise ValueError("区域边界不能重叠或交叉")
    if area == 0:
        raise ValueError("区域面积必须大于零")
    return points


def _json_value(value: object, depth: int) -> None:
    if depth > 4:
        raise ValueError("算法配置嵌套过深")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError("算法配置含有非有限数值")
        return
    if isinstance(value, str):
        if len(value) > 80 or _UNSAFE_TEXT.search(value):
            raise ValueError("算法配置含有不能保存的文本")
        return
    if isinstance(value, list):
        if len(value) > 40:
            raise ValueError("算法配置列表过长")
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 80:
            raise ValueError("算法配置字段过多")
        for key, item in value.items():
            if not isinstance(key, str) or _KEY.fullmatch(key) is None:
                raise ValueError("算法配置字段名无效")
            _json_value(item, depth + 1)
        return
    raise ValueError("算法配置含有不能保存的类型")


class SiteZone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    points: list[tuple[float, float]] = Field(min_length=3, max_length=200)

    @field_validator("points")
    @classmethod
    def _ring(cls, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return _checked_ring(points)


class SiteOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(allow_inf_nan=False, ge=-COORD_LIMIT, le=COORD_LIMIT)
    y: float = Field(allow_inf_nan=False, ge=-COORD_LIMIT, le=COORD_LIMIT)


class SitePlan(BaseModel):
    """Pending site inputs. The rectangle is the next search size, not a drawn solution."""

    model_config = ConfigDict(extra="forbid")

    rect_w_m: float = Field(allow_inf_nan=False, gt=0, le=100_000)
    rect_h_m: float = Field(allow_inf_nan=False, gt=0, le=100_000)
    field_policy: Literal["blocked", "allowed", "costly"]
    mountain_policy: Literal["blocked", "allowed"]
    field_cost: float = Field(allow_inf_nan=False, gt=0, le=1)
    include_demand: bool
    diagonal_access: bool
    road_setback_m: float = Field(allow_inf_nan=False, ge=0, le=1_000_000)
    water_setback_m: float = Field(allow_inf_nan=False, ge=0, le=1_000_000)
    highway_setback_m: float | None = Field(default=None, allow_inf_nan=False, ge=0, le=1_000_000)
    elevation_enabled: bool
    elevation_draft: str = Field(max_length=32)
    exclusion_zones: list[SiteZone] = Field(max_length=100)
    feasible_zones: list[SiteZone] = Field(max_length=100)
    origin: SiteOrigin | None

    @field_validator("elevation_draft")
    @classmethod
    def _elevation(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("最高海拔含有无效字符")
        if value.strip() and not _finite_text(value):
            raise ValueError("最高海拔必须是有限数值或留空")
        return value

    @model_validator(mode="after")
    def _unique_zones(self) -> "SitePlan":
        ids = [zone.id for zone in (*self.exclusion_zones, *self.feasible_zones)]
        if len(ids) != len(set(ids)):
            raise ValueError("区域编号重复")
        return self


class RoutingEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lng: str = Field(max_length=32)
    lat: str = Field(max_length=32)

    @model_validator(mode="after")
    def _coordinates(self) -> "RoutingEndpoint":
        self._one("lng", self.lng, 180)
        self._one("lat", self.lat, 90)
        return self

    @staticmethod
    def _one(name: str, value: str, limit: float) -> None:
        if any(ord(char) < 32 for char in value):
            raise ValueError(f"{name} 含有无效字符")
        if not value.strip():
            return
        if not _finite_text(value) or abs(float(value)) > limit:
            raise ValueError(f"{name} 必须是范围内的有限数值或留空")


class RoutingPlan(BaseModel):
    """Routing form text and user algorithm overrides. Empty fields are allowed."""

    model_config = ConfigDict(extra="forbid")

    start: RoutingEndpoint
    end: RoutingEndpoint
    max_span_m: str = Field(max_length=32)
    tower_radius_m: str = Field(max_length=32)
    max_turn_deg: str = Field(max_length=32)
    road_setback_m: str = Field(max_length=32)
    highway_setback_m: str = Field(max_length=32)
    no_tower_zones: list[list[tuple[float, float]]] = Field(max_length=100)
    no_cross_zones: list[list[tuple[float, float]]] = Field(max_length=100)
    algorithm_overrides: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _partial_values(self) -> "RoutingPlan":
        for name in ("max_span_m", "tower_radius_m", "max_turn_deg", "road_setback_m", "highway_setback_m"):
            value = getattr(self, name)
            if any(ord(char) < 32 for char in value):
                raise ValueError(f"{name} 含有无效字符")
            if value.strip() and not _finite_text(value):
                raise ValueError(f"{name} 必须是有限数值或留空")
        for rings in (self.no_tower_zones, self.no_cross_zones):
            for ring in rings:
                if not 3 <= len(ring) <= 200:
                    raise ValueError("区域至少需要三个顶点")
                _checked_ring(ring)
        _json_value(self.algorithm_overrides, 0)
        return self


class PlanningDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    site: SitePlan | None
    routing: RoutingPlan | None


def parse_stored_plan(raw: str) -> PlanningDocument:
    try:
        return PlanningDocument.model_validate_json(raw)
    except ValueError as exc:
        raise PlanInvalid("已保存的规划配置无法读取") from exc


def dump_plan(document: PlanningDocument) -> str:
    return canonical_plan(document.model_dump(mode="json"))
