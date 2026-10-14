"""从进货原点沿已保存的道路线段量到站址。

只返回沿路长度和离开道路的直线长度，单位是米，不乘单价。
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np


class RoadDisconnectedError(ValueError):
    """进货原点和目标投影位于不同道路连通分量。"""


@dataclass(frozen=True)
class RoadProjection:
    point: tuple[float, float]
    gap_m: float
    edge: int
    ratio: float


class RoadNetwork:
    """一次构建的道路端点图。交叉规则与原有 1 mm 端点取整保持一致。"""

    def __init__(self, segments: np.ndarray) -> None:
        _check_segments(segments)
        self.segments = np.asarray(segments, dtype=np.float64)
        self.graph = _build_graph(self.segments)
        components, count = _component_ids(self.graph)
        self.component_count = count
        self.segment_components = np.asarray(
            [components[_key(segment[:2])] for segment in self.segments],
            dtype=np.int64,
        )

    def project(self, point: tuple[float, float]) -> RoadProjection:
        projected, gap, edge, ratio = _closest(point, self.segments)
        return RoadProjection(
            point=(float(projected[0]), float(projected[1])),
            gap_m=float(gap),
            edge=int(edge),
            ratio=float(ratio),
        )

    def projection_on_edge(self, point: tuple[float, float], edge: int) -> RoadProjection:
        if edge < 0 or edge >= len(self.segments):
            raise ValueError("road edge index is out of range")
        segment = self.segments[edge]
        projected, ratio, gap = _project(np.asarray(point, dtype=np.float64), segment[:2], segment[2:])
        return RoadProjection(
            point=(float(projected[0]), float(projected[1])),
            gap_m=float(gap),
            edge=int(edge),
            ratio=float(ratio),
        )

    def component(self, projection: RoadProjection) -> int:
        return int(self.segment_components[projection.edge])

    def routes_from(self, origin: tuple[float, float]) -> RoadOriginRoutes:
        return RoadOriginRoutes(self, origin)


class RoadOriginRoutes:
    """一张道路图上从一个进货原点出发的一次单源最短路结果。"""

    def __init__(self, network: RoadNetwork, origin: tuple[float, float]) -> None:
        self.network = network
        self.origin = (float(origin[0]), float(origin[1]))
        self.origin_projection = network.project(self.origin)
        self.component_id = network.component(self.origin_projection)
        graph = {node: list(neighbors) for node, neighbors in network.graph.items()}
        self._origin_key = ("origin",)
        segment = network.segments[self.origin_projection.edge]
        point = np.asarray(self.origin_projection.point, dtype=np.float64)
        _join(graph, self._origin_key, _key(segment[:2]), float(np.linalg.norm(point - segment[:2])))
        _join(graph, self._origin_key, _key(segment[2:]), float(np.linalg.norm(point - segment[2:])))
        self._best, self._previous = _dijkstra_all(graph, self._origin_key)

    def is_reachable(self, projection: RoadProjection) -> bool:
        return self.network.component(projection) == self.component_id

    def route_to(self, site: tuple[float, float]) -> dict[str, object]:
        return self.route_to_projection(site, self.network.project(site))

    def route_to_projection(
        self,
        site: tuple[float, float],
        projection: RoadProjection,
    ) -> dict[str, object]:
        if not self.is_reachable(projection):
            raise RoadDisconnectedError("origin and site do not lie on a connected road network")

        segment = self.network.segments[projection.edge]
        site_point = np.asarray(projection.point, dtype=np.float64)
        choices: list[tuple[float, int, tuple | None]] = []
        if projection.edge == self.origin_projection.edge:
            direct = float(np.linalg.norm(np.asarray(self.origin_projection.point) - site_point))
            choices.append((direct, 0, None))
        for order, endpoint in enumerate((segment[:2], segment[2:]), start=1):
            key = _key(endpoint)
            if key in self._best:
                choices.append((self._best[key] + float(np.linalg.norm(site_point - endpoint)), order, key))
        if not choices:
            raise RoadDisconnectedError("origin and site do not lie on a connected road network")

        along_road, _order, endpoint = min(choices, key=lambda item: (item[0], item[1]))
        road_points = [self.origin_projection.point]
        if endpoint is not None:
            road_points.extend((float(key[0]), float(key[1])) for key in _path_to(self._previous, endpoint)[1:])
        road_points.append(projection.point)
        points = _dedupe([self.origin, *road_points, (float(site[0]), float(site[1]))])
        return {
            "road_m": float(along_road),
            "offroad_m": self.origin_projection.gap_m + projection.gap_m,
            "points": points,
        }


def logistics_route(
    origin: tuple[float, float],
    site: tuple[float, float],
    segments: np.ndarray,
) -> dict[str, object]:
    """返回沿路长度、直线离路长度，以及从原点到站址的折线。"""

    return RoadNetwork(segments).routes_from(origin).route_to(site)


def nearest_road_point(point: tuple[float, float], segments: np.ndarray) -> tuple[float, float]:
    """Closest point on the road network, in the same local meters as the segments."""

    _check_segments(segments)
    projected, _gap, _edge, _ratio = _closest(point, np.asarray(segments, dtype=np.float64))
    return float(projected[0]), float(projected[1])


def _check_segments(segments: np.ndarray) -> None:
    if segments.ndim != 2 or segments.shape[1] != 4 or segments.shape[0] == 0:
        raise ValueError("road segments must have shape [N, 4]")
    if not np.isfinite(segments).all():
        raise ValueError("road segments must be finite")


def _closest(point: tuple[float, float], segments: np.ndarray) -> tuple[np.ndarray, float, int, float]:
    best_gap = math.inf
    best_point = np.zeros(2)
    best_edge = 0
    best_ratio = 0.0
    query = np.array(point, dtype=np.float64)
    for index, segment in enumerate(segments):
        projected, ratio, gap = _project(query, segment[:2], segment[2:])
        if gap < best_gap:
            best_gap = gap
            best_point = projected
            best_edge = index
            best_ratio = ratio
    return best_point, best_gap, best_edge, best_ratio


def _project(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> tuple[np.ndarray, float, float]:
    span = end - start
    length2 = float(np.dot(span, span))
    if length2 == 0:
        return start.astype(np.float64), 0.0, float(np.linalg.norm(point - start))
    ratio = float(np.clip(np.dot(point - start, span) / length2, 0.0, 1.0))
    projected = start + ratio * span
    return projected.astype(np.float64), ratio, float(np.linalg.norm(point - projected))


def _build_graph(segments: np.ndarray) -> dict[tuple, list[tuple[tuple, float]]]:
    graph: dict[tuple, list[tuple[tuple, float]]] = {}
    for segment in segments:
        _join(graph, _key(segment[:2]), _key(segment[2:]), float(np.linalg.norm(segment[2:] - segment[:2])))
    return graph


def _join(graph: dict, left: tuple, right: tuple, length: float) -> None:
    graph.setdefault(left, []).append((right, length))
    graph.setdefault(right, []).append((left, length))


def _component_ids(graph: dict) -> tuple[dict[tuple, int], int]:
    components: dict[tuple, int] = {}
    count = 0
    for start in graph:
        if start in components:
            continue
        components[start] = count
        stack = [start]
        while stack:
            node = stack.pop()
            for neighbor, _length in graph[node]:
                if neighbor not in components:
                    components[neighbor] = count
                    stack.append(neighbor)
        count += 1
    return components, count


def _dijkstra_all(graph: dict, start: tuple) -> tuple[dict[tuple, float], dict[tuple, tuple | None]]:
    queue = [(0.0, 0, start)]
    best = {start: 0.0}
    previous: dict[tuple, tuple | None] = {start: None}
    order = 1
    while queue:
        cost, _order, node = heapq.heappop(queue)
        if cost > best.get(node, math.inf):
            continue
        for nxt, length in graph[node]:
            total = cost + length
            if total < best.get(nxt, math.inf):
                best[nxt] = total
                previous[nxt] = node
                heapq.heappush(queue, (total, order, nxt))
                order += 1
    return best, previous


def _path_to(previous: dict[tuple, tuple | None], goal: tuple) -> list[tuple]:
    path = []
    cursor: tuple | None = goal
    while cursor is not None:
        path.append(cursor)
        cursor = previous[cursor]
    path.reverse()
    return path


def _dedupe(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    kept = [points[0]]
    for point in points[1:]:
        if math.hypot(point[0] - kept[-1][0], point[1] - kept[-1][1]) > 0.05:
            kept.append(point)
    return kept


def _key(point: np.ndarray) -> tuple[float, float]:
    return (round(float(point[0]), 3), round(float(point[1]), 3))
