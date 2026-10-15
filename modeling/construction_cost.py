"""从原点到站址的运输量。

这里只记录沿路长度、进站长度和进站累计高差，单位都是米。
不把它们乘上单价或坡度权重。决策界面的引导式多目标搜索把这三项各自当作一个目标。
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass

import numpy as np

from .logistics_cost import logistics_route, nearest_road_point


class ConstructionCost(ABC):
    """从给定原点到站址的运输量。

    `measures` 返回三项米制结果：`road_m`、`offroad_m`、`access_rise_m`。
    没有 DEM 时，`access_rise_m` 为空。不要把这三项加在一起。
    """

    name = "construction_cost"

    @abstractmethod
    def measures(
        self,
        origin: tuple[float, float],
        site: tuple[float, float],
        segments: np.ndarray,
        *,
        dem: np.ndarray | None = None,
        buildable: np.ndarray | None = None,
    ) -> dict[str, float | None]:
        """返回沿路长度、进站长度和进站累计高差。"""


class RoadHaulCost(ConstructionCost):
    """离开道路的两段按直线计算，只得到长度，不乘单价。

    `dem` 和 `buildable` 被忽略。这一类用来和绕行进站路径对照。
    """

    def measures(
        self,
        origin: tuple[float, float],
        site: tuple[float, float],
        segments: np.ndarray,
        *,
        dem: np.ndarray | None = None,
        buildable: np.ndarray | None = None,
    ) -> dict[str, float | None]:
        route = logistics_route(origin, site, segments)
        return {
            "road_m": float(route["road_m"]),
            "offroad_m": float(route["offroad_m"]),
            "access_rise_m": None,
        }


class TerrainHaulCost(ConstructionCost):
    """沿路仍是最短路。站址到道路只走可建设格子。

    进站长度是这条格子路径的米数。进站累计高差是沿路径的高程变化绝对值之和。
    二者分开返回，不乘权重。`buildable` 里非 0 的格子可以走。没有通路时直接报错。
    """

    def measures(
        self,
        origin: tuple[float, float],
        site: tuple[float, float],
        segments: np.ndarray,
        *,
        dem: np.ndarray | None = None,
        buildable: np.ndarray | None = None,
    ) -> dict[str, float | None]:
        route = self.route(origin, site, segments, dem, buildable)
        return {
            "road_m": float(route["road_m"]),
            "offroad_m": float(route["offroad_m"]),
            "access_rise_m": float(route["access_rise_m"]),
        }

    def approach(
        self,
        site: tuple[float, float],
        segments: np.ndarray,
        dem: np.ndarray,
        buildable: np.ndarray,
    ) -> dict[str, float]:
        """站址到道路的长度和高差。不经过进货原点，所以没有沿路长度。"""

        _contact, points = _approach_points(dem, buildable, site, segments)
        length, rise, slope = _path_measures(dem, points)
        return {"offroad_m": length, "access_rise_m": rise, "max_slope_deg": slope, "points": points}

    def route(
        self,
        origin: tuple[float, float],
        site: tuple[float, float],
        segments: np.ndarray,
        dem: np.ndarray | None,
        buildable: np.ndarray | None,
    ) -> dict[str, object]:
        """返回三项米制量和从原点经道路再到站址的折线。"""

        if dem is None or buildable is None:
            raise ValueError("terrain haul requires a DEM and a buildable mask")
        if dem.shape != buildable.shape or dem.ndim != 2:
            raise ValueError("dem and buildable must be 2D arrays of the same shape")
        contact, approach = _approach_points(dem, buildable, site, segments)
        road = logistics_route(origin, contact, segments)
        approach_m, rise_m, _slope = _path_measures(dem, approach)
        points = _dedupe([*road["points"], *approach])
        return {
            "road_m": float(road["road_m"]),
            "offroad_m": float(road["offroad_m"]) + approach_m,
            "access_rise_m": rise_m,
            "points": points,
        }


def _approach_points(
    dem: np.ndarray,
    buildable: np.ndarray,
    site: tuple[float, float],
    segments: np.ndarray,
) -> tuple[tuple[float, float], list[tuple[float, float]]]:
    """Return the road contact and the points from that contact to the site."""

    road_cells = _road_cells(segments, buildable.shape)
    start = _cell(site, buildable.shape)
    if start in road_cells:
        contact = nearest_road_point(site, segments)
        return contact, [contact, (float(site[0]), float(site[1]))]
    if not _can_walk(buildable, start):
        raise ValueError("site cell is not buildable")
    goals = _road_gates(road_cells, buildable)
    if not goals:
        raise ValueError("no buildable cell touches the road")
    chain = _shortest_walk(start, goals, buildable, road_cells)
    contact = nearest_road_point(_center(chain[0]), segments)
    points = [contact, *(_center(cell) for cell in chain), (float(site[0]), float(site[1]))]
    return contact, _dedupe(points)


def _path_measures(dem: np.ndarray, points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """同一条折线的长度、高差和最大坡度。不乘系数。"""

    length = 0.0
    rise = 0.0
    steepest = 0.0
    for left, right in zip(points, points[1:]):
        step = math.hypot(right[0] - left[0], right[1] - left[1])
        if step == 0.0:
            continue
        delta = abs(_elevation(dem, right) - _elevation(dem, left))
        length += step
        rise += delta
        steepest = max(steepest, math.degrees(math.atan(delta / step)))
    return length, rise, steepest


def _road_cells(segments: np.ndarray, shape: tuple[int, int]) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    height, width = shape
    for x1, y1, x2, y2 in segments:
        length = math.hypot(float(x2 - x1), float(y2 - y1))
        steps = max(1, int(math.ceil(length / 0.25)))
        for index in range(steps + 1):
            weight = index / steps
            cell = _cell((x1 + (x2 - x1) * weight, y1 + (y2 - y1) * weight), shape, require_inside=False)
            if cell is not None and 0 <= cell[0] < height and 0 <= cell[1] < width:
                cells.add(cell)
    if not cells:
        raise ValueError("road does not cross the grid")
    return cells


def rasterize_road_mask(segments: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Rasterize OSM centerlines with the same cells used by haul-field gates."""

    mask = np.zeros(shape, dtype=bool)
    for row, col in _road_cells(segments, shape):
        mask[row, col] = True
    return mask


def _road_gates(road_cells: set[tuple[int, int]], buildable: np.ndarray) -> set[tuple[int, int]]:
    gates: set[tuple[int, int]] = set()
    for row, col in road_cells:
        for neighbor in _neighbors(row, col, buildable.shape):
            if neighbor not in road_cells and _can_walk(buildable, neighbor):
                gates.add(neighbor)
    return gates


def _shortest_walk(
    start: tuple[int, int],
    goals: set[tuple[int, int]],
    buildable: np.ndarray,
    road_cells: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return cells from the chosen road gate back to the site."""

    if start in goals:
        return [start]
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue: deque[tuple[int, int]] = deque([start])
    found: tuple[int, int] | None = None
    while queue and found is None:
        current = queue.popleft()
        for neighbor in _neighbors(*current, buildable.shape):
            if neighbor in previous or neighbor in road_cells or not _can_walk(buildable, neighbor):
                continue
            previous[neighbor] = current
            if neighbor in goals:
                found = neighbor
                break
            queue.append(neighbor)
    if found is None:
        raise ValueError("no buildable path from the site to the road")
    chain = []
    cursor: tuple[int, int] | None = found
    while cursor is not None:
        chain.append(cursor)
        cursor = previous[cursor]
    return chain


def _neighbors(row: int, col: int, shape: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    height, width = shape
    found = []
    for next_row, next_col in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
        if 0 <= next_row < height and 0 <= next_col < width:
            found.append((next_row, next_col))
    return tuple(found)


def _can_walk(buildable: np.ndarray, cell: tuple[int, int]) -> bool:
    return bool(buildable[cell[0], cell[1]] != 0)


def _cell(
    point: tuple[float, float],
    shape: tuple[int, int],
    *,
    require_inside: bool = True,
) -> tuple[int, int] | None:
    row = int(math.floor(point[1]))
    col = int(math.floor(point[0]))
    height, width = shape
    if 0 <= row < height and 0 <= col < width:
        return row, col
    if require_inside:
        raise ValueError("point is outside the grid")
    return None


def _center(cell: tuple[int, int]) -> tuple[float, float]:
    return cell[1] + 0.5, cell[0] + 0.5


def _elevation(dem: np.ndarray, point: tuple[float, float]) -> float:
    cell = _cell(point, dem.shape)
    assert cell is not None
    return float(dem[cell[0], cell[1]])


def _dedupe(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    kept: list[tuple[float, float]] = []
    for point in points:
        if not kept or math.hypot(point[0] - kept[-1][0], point[1] - kept[-1][1]) > 0.05:
            kept.append((float(point[0]), float(point[1])))
    return kept


@dataclass(frozen=True)
class ApproachGrid:
    """一次进站路径计算所用的道路格子和可走规则。距离场只通过 `build_approach_grid` 取得这些规则。"""

    road_cells: frozenset[tuple[int, int]]
    gates: frozenset[tuple[int, int]]
    shape: tuple[int, int]
    buildable: np.ndarray

    def neighbors(self, row: int, col: int) -> tuple[tuple[int, int], ...]:
        return _neighbors(row, col, self.shape)

    def can_walk(self, cell: tuple[int, int]) -> bool:
        return _can_walk(self.buildable, cell)

    def cell(self, point: tuple[float, float], *, require_inside: bool = True) -> tuple[int, int] | None:
        return _cell(point, self.shape, require_inside=require_inside)

    def center(self, cell: tuple[int, int]) -> tuple[float, float]:
        return _center(cell)

    def elevation(self, dem: np.ndarray, point: tuple[float, float]) -> float:
        return _elevation(dem, point)

    def measure_polyline(self, dem: np.ndarray, points: list[tuple[float, float]]) -> tuple[float, float, float]:
        return _path_measures(dem, _dedupe(points))


def build_approach_grid(segments: np.ndarray, buildable: np.ndarray) -> ApproachGrid:
    """返回道路格子、进站口，以及四连通可走邻居的规则。"""

    if buildable.ndim != 2 or buildable.size == 0:
        raise ValueError("buildable must be a non-empty 2D array")
    road_cells = _road_cells(segments, buildable.shape)
    return ApproachGrid(
        road_cells=frozenset(road_cells),
        gates=frozenset(_road_gates(road_cells, buildable)),
        shape=buildable.shape,
        buildable=buildable,
    )
