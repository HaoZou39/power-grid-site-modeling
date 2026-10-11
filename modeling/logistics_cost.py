"""从进货原点沿已保存的道路线段量到站址。

只返回沿路长度和离开道路的直线长度，单位是米，不乘单价。
"""

from __future__ import annotations

import heapq
import math

import numpy as np


def logistics_route(
    origin: tuple[float, float],
    site: tuple[float, float],
    segments: np.ndarray,
) -> dict[str, object]:
    """返回沿路长度、直线离路长度，以及从原点到站址的折线。"""

    _check_segments(segments)
    origin_point, origin_gap, origin_edge = _closest(origin, segments)
    site_point, site_gap, site_edge = _closest(site, segments)
    if origin_edge == site_edge:
        road_points = [tuple(float(value) for value in origin_point), tuple(float(value) for value in site_point)]
        along_road = float(np.linalg.norm(origin_point - site_point))
    else:
        graph, origin_key, site_key = _road_graph(origin_point, origin_edge, site_point, site_edge, segments)
        keys = _dijkstra(graph, origin_key, site_key)
        road_points = [tuple(float(value) for value in origin_point)]
        road_points.extend((float(key[0]), float(key[1])) for key in keys[1:-1])
        road_points.append(tuple(float(value) for value in site_point))
        along_road = _path_length(graph, keys)
    points = _dedupe([(float(origin[0]), float(origin[1])), *road_points, (float(site[0]), float(site[1]))])
    return {
        "road_m": along_road,
        "offroad_m": origin_gap + site_gap,
        "points": points,
    }


def nearest_road_point(point: tuple[float, float], segments: np.ndarray) -> tuple[float, float]:
    """Closest point on the road network, in the same local meters as the segments."""

    _check_segments(segments)
    projected, _gap, _edge = _closest(point, segments)
    return float(projected[0]), float(projected[1])


def _check_segments(segments: np.ndarray) -> None:
    if segments.ndim != 2 or segments.shape[1] != 4 or segments.shape[0] == 0:
        raise ValueError("road segments must have shape [N, 4]")
    if not np.isfinite(segments).all():
        raise ValueError("road segments must be finite")


def _closest(point: tuple[float, float], segments: np.ndarray) -> tuple[np.ndarray, float, int]:
    best_gap = math.inf
    best_point = np.zeros(2)
    best_edge = 0
    query = np.array(point, dtype=np.float64)
    for index, segment in enumerate(segments):
        projected, _t, gap = _project(query, segment[:2], segment[2:])
        if gap < best_gap:
            best_gap = gap
            best_point = projected
            best_edge = index
    return best_point, best_gap, best_edge


def _project(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> tuple[np.ndarray, float, float]:
    span = end - start
    length2 = float(np.dot(span, span))
    if length2 == 0:
        return start.astype(np.float64), 0.0, float(np.linalg.norm(point - start))
    ratio = float(np.clip(np.dot(point - start, span) / length2, 0.0, 1.0))
    projected = start + ratio * span
    return projected.astype(np.float64), ratio, float(np.linalg.norm(point - projected))


def _road_graph(
    origin_point: np.ndarray,
    origin_edge: int,
    site_point: np.ndarray,
    site_edge: int,
    segments: np.ndarray,
):
    graph: dict[tuple, list[tuple[tuple, float]]] = {}

    def join(left: tuple, right: tuple, length: float) -> None:
        graph.setdefault(left, []).append((right, length))
        graph.setdefault(right, []).append((left, length))

    for segment in segments:
        join(_key(segment[:2]), _key(segment[2:]), float(np.linalg.norm(segment[2:] - segment[:2])))
    origin_key = ("origin",)
    site_key = ("site",)
    origin_segment = segments[origin_edge]
    site_segment = segments[site_edge]
    join(origin_key, _key(origin_segment[:2]), float(np.linalg.norm(origin_point - origin_segment[:2])))
    join(origin_key, _key(origin_segment[2:]), float(np.linalg.norm(origin_point - origin_segment[2:])))
    join(site_key, _key(site_segment[:2]), float(np.linalg.norm(site_point - site_segment[:2])))
    join(site_key, _key(site_segment[2:]), float(np.linalg.norm(site_point - site_segment[2:])))
    return graph, origin_key, site_key


def _path_length(graph: dict, keys: list) -> float:
    total = 0.0
    for left, right in zip(keys, keys[1:]):
        total += next(length for neighbor, length in graph[left] if neighbor == right)
    return total


def _dedupe(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    kept = [points[0]]
    for point in points[1:]:
        if math.hypot(point[0] - kept[-1][0], point[1] - kept[-1][1]) > 0.05:
            kept.append(point)
    return kept


def _key(point: np.ndarray) -> tuple[float, float]:
    return (round(float(point[0]), 3), round(float(point[1]), 3))


def _dijkstra(graph: dict, start: tuple, goal: tuple) -> list:
    queue = [(0.0, 0, start)]
    best = {start: 0.0}
    previous: dict[tuple, tuple | None] = {start: None}
    order = 1
    while queue:
        cost, _order, node = heapq.heappop(queue)
        if node == goal:
            path = []
            cursor: tuple | None = goal
            while cursor is not None:
                path.append(cursor)
                cursor = previous[cursor]
            path.reverse()
            return path
        if cost > best.get(node, math.inf):
            continue
        for nxt, length in graph[node]:
            total = cost + length
            if total < best.get(nxt, math.inf):
                best[nxt] = total
                previous[nxt] = node
                heapq.heappush(queue, (total, order, nxt))
                order += 1
    raise ValueError("origin and site do not lie on a connected road network")
