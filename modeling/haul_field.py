"""一次建好的进站距离场。

格子中心上的进站长度、进站累计高差和沿路长度与 `TerrainHaulCost` 一致。
搜索开始时调用 `build_haul_field` 一次，之后用 `query_exact` 查表。
走不通的站址记为不可行，目标值保持 0，不写入哨兵距离。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from modeling.construction_cost import build_approach_grid
from modeling.logistics_cost import logistics_route, nearest_road_point

# 查表列顺序。有进货原点时在前面加上沿路长度。引导式多目标搜索的目标名单直接使用这组名字。
HAUL_COLUMNS_WITHOUT_ORIGIN = ("offroad_haul_m", "haul_rise_m")
HAUL_COLUMNS_WITH_ORIGIN = ("road_haul_m",) + HAUL_COLUMNS_WITHOUT_ORIGIN


def haul_column_names(include_road_haul: bool) -> tuple[str, ...]:
    """进站目标的列名。顺序与 `query_exact` 的返回列一致。"""

    if include_road_haul:
        return HAUL_COLUMNS_WITH_ORIGIN
    return HAUL_COLUMNS_WITHOUT_ORIGIN


@dataclass(frozen=True)
class HaulField:
    """格子中心上的进站长度。没有进货原点时不记录 `road_m`。"""

    dem: np.ndarray
    buildable: np.ndarray
    segments: np.ndarray
    origin: tuple[float, float] | None
    offroad_m: np.ndarray
    access_rise_m: np.ndarray
    road_m: np.ndarray | None
    reachable: np.ndarray
    road_cells: np.ndarray
    geometry: object | None = None


def build_haul_field(
    dem: np.ndarray,
    buildable: np.ndarray,
    segments: np.ndarray,
    origin: tuple[float, float] | None = None,
) -> HaulField:
    """从每个进站口做一次四连通扩展。走不通的格子留空。"""

    if dem.ndim != 2 or dem.shape != buildable.shape:
        raise ValueError("dem and buildable must be 2D arrays of the same shape")
    height, width = dem.shape
    geometry = build_approach_grid(segments, buildable)
    on_road = np.zeros((height, width), dtype=bool)
    for row, col in geometry.road_cells:
        on_road[row, col] = True
    gates = sorted(geometry.gates)
    offroad = np.zeros((height, width), dtype=np.float64)
    rise = np.zeros((height, width), dtype=np.float64)
    road = None if origin is None else np.zeros((height, width), dtype=np.float64)
    reachable = np.zeros((height, width), dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    centers = np.array([geometry.center(gate) for gate in gates], dtype=np.float64)
    contacts = _nearest_on_segments(centers, np.asarray(segments, dtype=np.float64))
    # 有进货原点时，offroad_m 已加上原点到道路的直线空隙，以便和 TerrainHaulCost.measures 一致。
    # 没有原点时，这张表只是站址走到进站口的长度。
    for gate, center, contact in zip(gates, centers, contacts):
        contact_point = (float(contact[0]), float(contact[1]))
        step = math.hypot(float(center[0]) - contact_point[0], float(center[1]) - contact_point[1])
        gate_rise = 0.0 if step == 0.0 else abs(geometry.elevation(dem, (float(center[0]), float(center[1]))) - _elevation_on_grid(geometry, dem, contact_point))
        offroad[gate] = step
        rise[gate] = gate_rise
        if origin is not None and road is not None:
            route = logistics_route(origin, contact_point, segments)
            road[gate] = float(route["road_m"])
            offroad[gate] = float(route["offroad_m"]) + step
        reachable[gate] = True
        queue.append(gate)
    while queue:
        current = queue.popleft()
        current_center = geometry.center(current)
        for neighbor in geometry.neighbors(*current):
            if on_road[neighbor] or reachable[neighbor] or not geometry.can_walk(neighbor):
                continue
            neighbor_center = geometry.center(neighbor)
            step = math.hypot(neighbor_center[0] - current_center[0], neighbor_center[1] - current_center[1])
            rise_step = 0.0 if step == 0.0 else abs(geometry.elevation(dem, neighbor_center) - geometry.elevation(dem, current_center))
            offroad[neighbor] = offroad[current] + step
            rise[neighbor] = rise[current] + rise_step
            if road is not None:
                road[neighbor] = road[current]
            reachable[neighbor] = True
            queue.append(neighbor)
    return HaulField(
        dem=dem,
        buildable=buildable,
        segments=segments,
        origin=None if origin is None else (float(origin[0]), float(origin[1])),
        offroad_m=offroad,
        access_rise_m=rise,
        road_m=road,
        reachable=reachable,
        road_cells=on_road,
        geometry=geometry,
    )


def _nearest_on_segments(points: np.ndarray, segments: np.ndarray) -> np.ndarray:
    """每个点在线段上的最近点。距离相同的线段保留更靠前的那条，与 `nearest_road_point` 一致。"""

    if len(points) == 0:
        return np.zeros((0, 2), dtype=np.float64)
    start = segments[:, :2]
    end = segments[:, 2:]
    span = end - start
    length2 = np.sum(span * span, axis=1)
    safe = np.where(length2 == 0.0, 1.0, length2)
    delta = points[:, None, :] - start[None, :, :]
    ratio = np.sum(delta * span[None, :, :], axis=-1) / safe[None, :]
    ratio = np.clip(ratio, 0.0, 1.0)
    projected = start[None, :, :] + ratio[:, :, None] * span[None, :, :]
    projected = np.where(length2[None, :, None] == 0.0, start[None, :, :], projected)
    distance = np.linalg.norm(points[:, None, :] - projected, axis=-1)
    choice = np.argmin(distance, axis=1)
    return projected[np.arange(len(points)), choice]


def _elevation_on_grid(geometry: object, dem: np.ndarray, point: tuple[float, float]) -> float:
    """读取高程。道路接触点若刚超出网格，改用网格内最近的格子。"""

    height, width = dem.shape
    x = min(max(float(point[0]), 0.0), width - 1e-6)
    y = min(max(float(point[1]), 0.0), height - 1e-6)
    return geometry.elevation(dem, (x, y))


def query_exact(field: HaulField, sites: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """返回进站各列和一个不可行标记。不可行的那一行保持 0。"""

    if sites.ndim != 2 or sites.shape[1] != 2:
        raise ValueError("sites must have shape [N, 2]")
    names = haul_column_names(field.road_m is not None)
    values = np.zeros((len(sites), len(names)), dtype=np.float64)
    blocked = np.zeros(len(sites), dtype=np.float64)
    for index, site in enumerate(sites):
        point = (float(site[0]), float(site[1]))
        try:
            row = _measures_at(field, point)
        except ValueError:
            blocked[index] = 1.0
            continue
        if row is None:
            blocked[index] = 1.0
            continue
        values[index] = [row[name] for name in names]
    return values, blocked


def _measures_at(field: HaulField, site: tuple[float, float]) -> dict[str, float] | None:
    geometry = _geometry(field)
    cell = geometry.cell(site)
    assert cell is not None
    if field.road_cells[cell]:
        return _from_road_cell(field, geometry, site)
    if not field.reachable[cell]:
        return None
    center = geometry.center(cell)
    extra = math.hypot(site[0] - center[0], site[1] - center[1])
    offroad = float(field.offroad_m[cell])
    rise = float(field.access_rise_m[cell])
    # 0.05 米沿用折线去重：站址离格子中心不超过 5 厘米时，不再另加最后一段。
    if extra > 0.05:
        offroad += extra
        rise += abs(geometry.elevation(field.dem, site) - geometry.elevation(field.dem, center))
    measured = {"offroad_haul_m": offroad, "haul_rise_m": rise}
    if field.road_m is not None:
        measured["road_haul_m"] = float(field.road_m[cell])
    return measured


def _geometry(field: HaulField):
    if field.geometry is not None:
        return field.geometry
    return build_approach_grid(field.segments, field.buildable)


def _from_road_cell(field: HaulField, geometry: object, site: tuple[float, float]) -> dict[str, float]:
    contact = nearest_road_point(site, field.segments)
    length, rise, _slope = geometry.measure_polyline(field.dem, [contact, (float(site[0]), float(site[1]))])
    measured = {"offroad_haul_m": length, "haul_rise_m": rise}
    if field.origin is None:
        return measured
    route = logistics_route(field.origin, contact, field.segments)
    measured["road_haul_m"] = float(route["road_m"])
    measured["offroad_haul_m"] = float(route["offroad_m"]) + length
    return measured
