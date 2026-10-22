"""一次建好的进站距离场。

使用多源 Dijkstra 按每步水平距离加高程变化惩罚选路。长度和累计高差仍单独记录。
搜索开始时调用 `build_haul_field` 一次，之后用 `query_exact` 查表。
走不通的站址记为不可行，目标值保持 0，不写入哨兵距离。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from time import perf_counter

import numpy as np
from numba import njit

from modeling.construction_cost import build_approach_grid
from modeling.logistics_cost import RoadNetwork, RoadOriginRoutes, nearest_road_point


_LOGGER = logging.getLogger("uvicorn.error")

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
    access_elevation_weight: float = 1.0
    road_routes: RoadOriginRoutes | None = None
    gate_count: int = 0
    reachable_gate_count: int = 0
    unreachable_gate_count: int = 0
    predecessor: np.ndarray | None = None
    gate_owner: np.ndarray | None = None
    gate_cells: np.ndarray | None = None
    gate_contacts: np.ndarray | None = None
    gate_contact_edges: np.ndarray | None = None
    gate_reachable: np.ndarray | None = None
    gate_road_m: np.ndarray | None = None
    gate_offroad_m: np.ndarray | None = None
    gate_rise_m: np.ndarray | None = None


_PREDECESSOR_UNREACHABLE = np.int8(0)
_PREDECESSOR_GATE = np.int8(1)
_PREDECESSOR_DELTAS = {
    2: (-1, 0),
    3: (1, 0),
    4: (0, -1),
    5: (0, 1),
    6: (-1, -1),
    7: (-1, 1),
    8: (1, -1),
    9: (1, 1),
}


def build_haul_field(
    dem: np.ndarray,
    buildable: np.ndarray,
    segments: np.ndarray,
    origin: tuple[float, float] | None = None,
    diagonal: bool = False,
    access_elevation_weight: float = 1.0,
) -> HaulField:
    """从所有可用进站口做多源 Dijkstra，选择加权代价最低的可建设路径。"""

    started = perf_counter()
    if dem.ndim != 2 or dem.shape != buildable.shape:
        raise ValueError("dem and buildable must be 2D arrays of the same shape")
    if not math.isfinite(access_elevation_weight) or access_elevation_weight < 0:
        raise ValueError("access_elevation_weight must be finite and non-negative")
    height, width = dem.shape
    geometry = build_approach_grid(segments, buildable)
    on_road = np.zeros((height, width), dtype=bool)
    for row, col in geometry.road_cells:
        on_road[row, col] = True
    gates = sorted(geometry.gates)
    offroad = np.zeros((height, width), dtype=np.float64)
    rise = np.zeros((height, width), dtype=np.float64)
    selection_cost = np.full((height, width), np.inf, dtype=np.float64)
    road = None if origin is None else np.zeros((height, width), dtype=np.float64)
    reachable = np.zeros((height, width), dtype=bool)
    predecessor = np.zeros((height, width), dtype=np.int8)
    gate_owner = np.full((height, width), -1, dtype=np.int32)
    seeds: list[tuple[int, int]] = []
    centers = np.array([geometry.center(gate) for gate in gates], dtype=np.float64)
    contacts, contact_edges = _nearest_on_segments(centers, np.asarray(segments, dtype=np.float64))
    gate_reachable = np.zeros(len(gates), dtype=bool)
    gate_road_m = np.zeros(len(gates), dtype=np.float64)
    gate_offroad_m = np.zeros(len(gates), dtype=np.float64)
    gate_rise_m = np.zeros(len(gates), dtype=np.float64)
    routes = None if origin is None else RoadNetwork(segments).routes_from(origin)
    reachable_gate_count = 0
    # 有进货原点时，offroad_m 已加上原点到道路的直线空隙，以便和 TerrainHaulCost.measures 一致。
    # 没有原点时，这张表只是站址走到进站口的长度。
    for gate_index, (gate, center, contact, contact_edge) in enumerate(zip(gates, centers, contacts, contact_edges)):
        contact_point = (float(contact[0]), float(contact[1]))
        route = None
        if routes is not None:
            projection = routes.network.projection_on_edge(contact_point, int(contact_edge))
            if not routes.is_reachable(projection):
                continue
            route = routes.route_to_projection(contact_point, projection)
        step = math.hypot(float(center[0]) - contact_point[0], float(center[1]) - contact_point[1])
        gate_rise = 0.0 if step == 0.0 else abs(geometry.elevation(dem, (float(center[0]), float(center[1]))) - _elevation_on_grid(geometry, dem, contact_point))
        offroad[gate] = step
        rise[gate] = gate_rise
        selection_cost[gate] = step + access_elevation_weight * gate_rise
        if route is not None and road is not None:
            road[gate] = float(route["road_m"])
            offroad[gate] = float(route["offroad_m"]) + step
        reachable[gate] = True
        predecessor[gate] = _PREDECESSOR_GATE
        gate_owner[gate] = gate_index
        gate_reachable[gate_index] = True
        gate_road_m[gate_index] = 0.0 if road is None else road[gate]
        gate_offroad_m[gate_index] = offroad[gate]
        gate_rise_m[gate_index] = rise[gate]
        seeds.append(gate)
        reachable_gate_count += 1
    unreachable_gate_count = len(gates) - reachable_gate_count
    if origin is not None and reachable_gate_count == 0:
        _LOGGER.warning(
            "haul_field.build status=failed elapsed_s=%.3f shape=%sx%s gates=%s reason=no_reachable_gate",
            perf_counter() - started,
            height,
            width,
            len(gates),
        )
        raise ValueError(
            "origin cannot reach any valid road gate "
            f"(total_gates={len(gates)}, reachable_gates=0, unreachable_gates={unreachable_gate_count})"
        )
    _expand_dijkstra(
        geometry,
        dem,
        on_road,
        offroad,
        rise,
        road,
        reachable,
        predecessor,
        gate_owner,
        seeds,
        selection_cost,
        diagonal=diagonal,
        access_elevation_weight=access_elevation_weight,
    )
    field = HaulField(
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
        access_elevation_weight=access_elevation_weight,
        road_routes=routes,
        gate_count=len(gates),
        reachable_gate_count=reachable_gate_count,
        unreachable_gate_count=unreachable_gate_count,
        predecessor=predecessor,
        gate_owner=gate_owner,
        gate_cells=np.asarray(gates, dtype=np.int32).reshape((-1, 2)),
        gate_contacts=contacts,
        gate_contact_edges=contact_edges.astype(np.int32, copy=False),
        gate_reachable=gate_reachable,
        gate_road_m=gate_road_m,
        gate_offroad_m=gate_offroad_m,
        gate_rise_m=gate_rise_m,
    )
    _LOGGER.info(
        "haul_field.build status=ok elapsed_s=%.3f shape=%sx%s gates=%s reachable_gates=%s origin=%s diagonal=%s elevation_weight=%s",
        perf_counter() - started,
        height,
        width,
        len(gates),
        reachable_gate_count,
        origin is not None,
        diagonal,
        access_elevation_weight,
    )
    return field


def _expand_dijkstra(
    geometry: object,
    dem: np.ndarray,
    on_road: np.ndarray,
    offroad: np.ndarray,
    rise: np.ndarray,
    road: np.ndarray | None,
    reachable: np.ndarray,
    predecessor: np.ndarray,
    gate_owner: np.ndarray,
    seeds: list[tuple[int, int]],
    selection_cost: np.ndarray,
    *,
    diagonal: bool,
    access_elevation_weight: float,
) -> None:
    """按水平长度加逐步高程惩罚排序扩展可建设格子。"""

    _expand_dijkstra_compiled(
        dem,
        geometry.buildable != 0,
        on_road,
        road,
        offroad,
        rise,
        reachable,
        predecessor,
        gate_owner,
        selection_cost,
        np.asarray(seeds, dtype=np.int64).reshape((-1, 2)),
        diagonal,
        access_elevation_weight,
    )


@njit
def _expand_dijkstra_compiled(
    dem: np.ndarray,
    walkable: np.ndarray,
    on_road: np.ndarray,
    road: np.ndarray | None,
    offroad: np.ndarray,
    rise: np.ndarray,
    reachable: np.ndarray,
    predecessor: np.ndarray,
    gate_owner: np.ndarray,
    selection_cost: np.ndarray,
    seeds: np.ndarray,
    diagonal: bool,
    access_elevation_weight: float,
) -> None:
    height, width = dem.shape
    node_count = height * width
    heap = np.empty(node_count, dtype=np.int64)
    heap_position = np.full(node_count, -1, dtype=np.int64)
    heap_size = 0

    for seed in seeds:
        node = int(seed[0]) * width + int(seed[1])
        position = heap_size
        heap[position] = node
        heap_position[node] = position
        heap_size += 1
        while position > 0:
            parent = (position - 1) // 2
            parent_node = heap[parent]
            node_cost = selection_cost[node // width, node % width]
            parent_cost = selection_cost[parent_node // width, parent_node % width]
            if node_cost > parent_cost or (node_cost == parent_cost and node >= parent_node):
                break
            heap[position] = parent_node
            heap_position[parent_node] = position
            position = parent
            heap[position] = node
            heap_position[node] = position

    row_steps = (-1, 1, 0, 0, -1, -1, 1, 1)
    col_steps = (0, 0, -1, 1, -1, 1, -1, 1)
    direction_count = 8 if diagonal else 4

    while heap_size > 0:
        current_node = heap[0]
        current_row = current_node // width
        current_col = current_node % width
        heap_position[current_node] = -2
        heap_size -= 1
        if heap_size > 0:
            last_node = heap[heap_size]
            heap[0] = last_node
            heap_position[last_node] = 0
            position = 0
            while True:
                left = position * 2 + 1
                if left >= heap_size:
                    break
                right = left + 1
                child = left
                left_node = heap[left]
                if right < heap_size:
                    right_node = heap[right]
                    left_cost = selection_cost[left_node // width, left_node % width]
                    right_cost = selection_cost[right_node // width, right_node % width]
                    if right_cost < left_cost or (right_cost == left_cost and right_node < left_node):
                        child = right
                child_node = heap[child]
                position_node = heap[position]
                child_cost = selection_cost[child_node // width, child_node % width]
                position_cost = selection_cost[position_node // width, position_node % width]
                if child_cost > position_cost or (child_cost == position_cost and child_node >= position_node):
                    break
                heap[position] = child_node
                heap_position[child_node] = position
                heap[child] = position_node
                heap_position[position_node] = child
                position = child

        for direction in range(direction_count):
            row_step = row_steps[direction]
            col_step = col_steps[direction]
            neighbor_row = current_row + row_step
            neighbor_col = current_col + col_step
            if neighbor_row < 0 or neighbor_row >= height or neighbor_col < 0 or neighbor_col >= width:
                continue
            if on_road[neighbor_row, neighbor_col] or not walkable[neighbor_row, neighbor_col]:
                continue
            if diagonal and row_step != 0 and col_step != 0:
                if not walkable[current_row, neighbor_col] or not walkable[neighbor_row, current_col]:
                    continue
            neighbor_node = neighbor_row * width + neighbor_col
            if heap_position[neighbor_node] == -2:
                continue
            step = math.sqrt(row_step * row_step + col_step * col_step)
            rise_step = abs(dem[neighbor_row, neighbor_col] - dem[current_row, current_col])
            new_cost = selection_cost[current_row, current_col] + step + access_elevation_weight * rise_step
            if reachable[neighbor_row, neighbor_col] and new_cost >= selection_cost[neighbor_row, neighbor_col]:
                continue

            selection_cost[neighbor_row, neighbor_col] = new_cost
            if road is not None:
                road[neighbor_row, neighbor_col] = road[current_row, current_col]
            offroad[neighbor_row, neighbor_col] = offroad[current_row, current_col] + step
            rise[neighbor_row, neighbor_col] = rise[current_row, current_col] + rise_step
            reachable[neighbor_row, neighbor_col] = True
            predecessor[neighbor_row, neighbor_col] = _predecessor_code_numba(row_step, col_step)
            gate_owner[neighbor_row, neighbor_col] = gate_owner[current_row, current_col]
            position = heap_position[neighbor_node]
            if position == -1:
                position = heap_size
                heap[position] = neighbor_node
                heap_position[neighbor_node] = position
                heap_size += 1
            while position > 0:
                parent = (position - 1) // 2
                parent_node = heap[parent]
                node_cost = selection_cost[neighbor_row, neighbor_col]
                parent_cost = selection_cost[parent_node // width, parent_node % width]
                if node_cost > parent_cost or (node_cost == parent_cost and neighbor_node >= parent_node):
                    break
                heap[position] = parent_node
                heap_position[parent_node] = position
                position = parent
                heap[position] = neighbor_node
                heap_position[neighbor_node] = position


@njit
def _predecessor_code_numba(row_step: int, col_step: int) -> np.int8:
    if row_step == -1:
        return np.int8(3 if col_step == 0 else (9 if col_step == -1 else 8))
    if row_step == 1:
        return np.int8(2 if col_step == 0 else (7 if col_step == -1 else 6))
    return np.int8(5 if col_step == -1 else 4)


def _nearest_on_segments(points: np.ndarray, segments: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """每个点在线段上的最近点。距离相同的线段保留更靠前的那条，与 `nearest_road_point` 一致。"""

    if len(points) == 0:
        return np.zeros((0, 2), dtype=np.float64), np.zeros(0, dtype=np.int64)
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
    return projected[np.arange(len(points)), choice], choice


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


def query_route(field: HaulField, site: tuple[float, float]) -> dict[str, object]:
    """Reconstruct the exact path whose metrics are returned by ``query_exact``."""

    site = (float(site[0]), float(site[1]))
    geometry = _geometry(field)
    cell = geometry.cell(site)
    assert cell is not None
    if not field.road_cells[cell] and not geometry.can_walk(cell):
        raise ValueError("site cell is not buildable")
    measured = _measures_at(field, site)
    if measured is None:
        raise ValueError("no buildable path from the site to the road")
    if field.road_cells[cell]:
        approach, gate_index, contact, contact_edge = _route_from_road_cell(field, geometry, site)
    else:
        approach, gate_index, contact, contact_edge = _route_from_predecessors(field, geometry, cell, site)
    slope = _max_slope_deg(field, geometry, approach)
    points = approach
    if field.origin is not None:
        routes = field.road_routes or RoadNetwork(field.segments).routes_from(field.origin)
        projection = routes.network.projection_on_edge(contact, contact_edge)
        road_route = routes.route_to_projection(contact, projection)
        points = _join_points([*road_route["points"], *approach])
    result: dict[str, object] = {
        **measured,
        "access_slope_deg": slope,
        "points": points,
        "gate_index": gate_index,
        "road_contact": contact,
        "road_segment_id": contact_edge,
    }
    return result


def _route_from_road_cell(
    field: HaulField,
    geometry: object,
    site: tuple[float, float],
) -> tuple[list[tuple[float, float]], int | None, tuple[float, float], int]:
    if field.road_routes is not None:
        projection = field.road_routes.network.project(site)
        contact = projection.point
        edge = projection.edge
    else:
        contacts, edges = _nearest_on_segments(np.asarray([site], dtype=np.float64), field.segments)
        contact = (float(contacts[0, 0]), float(contacts[0, 1]))
        edge = int(edges[0])
    return _dedupe_points([contact, site]), None, contact, edge


def _route_from_predecessors(
    field: HaulField,
    geometry: object,
    cell: tuple[int, int],
    site: tuple[float, float],
) -> tuple[list[tuple[float, float]], int, tuple[float, float], int]:
    if (
        field.predecessor is None
        or field.gate_owner is None
        or field.gate_cells is None
        or field.gate_contacts is None
        or field.gate_contact_edges is None
    ):
        raise ValueError("haul field does not contain route reconstruction data")
    gate_index = int(field.gate_owner[cell])
    if gate_index < 0:
        raise ValueError("no buildable path from the site to the road")
    chain = [cell]
    cursor = cell
    while int(field.predecessor[cursor]) != int(_PREDECESSOR_GATE):
        code = int(field.predecessor[cursor])
        delta = _PREDECESSOR_DELTAS.get(code)
        if delta is None:
            raise ValueError("haul field predecessor chain is incomplete")
        cursor = cursor[0] + delta[0], cursor[1] + delta[1]
        chain.append(cursor)
        if len(chain) > field.reachable.size:
            raise ValueError("haul field predecessor chain contains a cycle")
    expected_gate = tuple(int(value) for value in field.gate_cells[gate_index])
    if cursor != expected_gate:
        raise ValueError("haul field gate ownership does not match its predecessor chain")
    contact = tuple(float(value) for value in field.gate_contacts[gate_index])
    approach = [contact, *(geometry.center(item) for item in reversed(chain))]
    center = geometry.center(cell)
    if math.hypot(site[0] - center[0], site[1] - center[1]) > 0.05:
        approach.append(site)
    return approach, gate_index, contact, int(field.gate_contact_edges[gate_index])


def _max_slope_deg(field: HaulField, geometry: object, points: list[tuple[float, float]]) -> float:
    steepest = 0.0
    for left, right in zip(points, points[1:]):
        step = math.hypot(right[0] - left[0], right[1] - left[1])
        if step == 0.0:
            continue
        delta = abs(_elevation_on_grid(geometry, field.dem, right) - _elevation_on_grid(geometry, field.dem, left))
        steepest = max(steepest, math.degrees(math.atan(delta / step)))
    return steepest


def _dedupe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    kept: list[tuple[float, float]] = []
    for point in points:
        normalized = (float(point[0]), float(point[1]))
        if not kept or math.hypot(normalized[0] - kept[-1][0], normalized[1] - kept[-1][1]) > 0.05:
            kept.append(normalized)
    return kept


def _join_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    kept: list[tuple[float, float]] = []
    for point in points:
        normalized = (float(point[0]), float(point[1]))
        if not kept or normalized != kept[-1]:
            kept.append(normalized)
    return kept


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
    routes = field.road_routes or RoadNetwork(field.segments).routes_from(field.origin)
    route = routes.route_to(contact)
    measured["road_haul_m"] = float(route["road_m"])
    measured["offroad_haul_m"] = float(route["offroad_m"]) + length
    return measured
