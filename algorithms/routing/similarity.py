"""A5 similarity for the displayed route list.

Hausdorff is the published vertex distance, with pairs at or under 52 m
resampled every 2 m. A route is compared only with representatives already
kept. These functions do not read diagnostics or change the stored front.
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit, prange

A5_TOLERANCE = (0.0, 30.0, 3.0, 10.0)
GEO_M = 20.0
HAUSDORFF_DEFINITION = "vertex_then_sample_2m_pairs_le_52"


def normalized_sum(objectives: np.ndarray) -> np.ndarray:
    span = np.ptp(objectives, axis=0)
    scale = np.where(span > 0, span, 1.0)
    return ((objectives - objectives.min(axis=0)) / scale).sum(axis=1)


def _within_tolerance(delta: np.ndarray) -> bool:
    return all(abs(float(delta[column])) <= A5_TOLERANCE[column] for column in range(4))


def a5_keep(
    distance: np.ndarray,
    objectives: np.ndarray,
    forced: list[int],
) -> tuple[list[int], dict[int, int]]:
    """Greedy A5. A route is compared only with routes already kept."""
    score = normalized_sum(objectives)
    order = [int(index) for index in np.argsort(score, kind="stable")]
    forced_set = set(forced)
    kept: list[int] = []
    assignment: dict[int, int] = {}
    for index in list(forced) + [index for index in order if index not in forced_set]:
        if index in assignment or index in kept:
            continue
        match = None
        if index not in forced_set:
            hits = []
            for other in kept:
                gap = float(distance[index, other])
                delta = objectives[index] - objectives[other]
                if gap <= GEO_M and _within_tolerance(delta):
                    hits.append((gap, other))
            if hits:
                match = min(hits)[1]
        if match is None:
            kept.append(index)
        else:
            assignment[index] = int(match)
    return kept, assignment


def member_accepts_representative(member: int, representative: int, objectives: np.ndarray, distance: np.ndarray) -> bool:
    if member == representative:
        return True
    gap = float(distance[member, representative])
    return gap <= GEO_M and _within_tolerance(objectives[member] - objectives[representative])


def tangent_normal(polyline: np.ndarray, index: int) -> tuple[np.ndarray, np.ndarray]:
    """Tangent is the sum of the adjacent unit segments. normal = (-ty, tx) in stored coordinates."""
    if index <= 0:
        direction = polyline[1] - polyline[0]
    elif index >= len(polyline) - 1:
        direction = polyline[-1] - polyline[-2]
    else:
        incoming = polyline[index] - polyline[index - 1]
        outgoing = polyline[index + 1] - polyline[index]
        incoming_length = float(np.linalg.norm(incoming))
        outgoing_length = float(np.linalg.norm(outgoing))
        direction = incoming / max(incoming_length, 1e-12) + outgoing / max(outgoing_length, 1e-12)
        if float(np.linalg.norm(direction)) <= 1e-8:
            direction = outgoing
    tangent = direction / max(float(np.linalg.norm(direction)), 1e-12)
    normal = np.array([-tangent[1], tangent[0]])
    return tangent, normal


def tower_components(member: np.ndarray, representative: np.ndarray) -> dict | None:
    """Index-aligned interior towers. A large along-track value is sliding, not a new corridor."""
    if len(member) != len(representative) or len(member) < 2:
        return None
    along, cross = [], []
    for index in range(1, len(member) - 1):
        tangent, normal = tangent_normal(representative, index)
        delta = member[index] - representative[index]
        along.append(float(np.dot(delta, tangent)))
        cross.append(float(np.dot(delta, normal)))
    if not along:
        return {"max_m": 0.0, "mean_m": 0.0, "max_abs_along_m": 0.0, "max_abs_cross_m": 0.0, "mean_abs_along_m": 0.0, "mean_abs_cross_m": 0.0}
    distance = np.hypot(along, cross)
    return {
        "max_m": float(distance.max()),
        "mean_m": float(distance.mean()),
        "max_abs_along_m": float(np.max(np.abs(along))),
        "max_abs_cross_m": float(np.max(np.abs(cross))),
        "mean_abs_along_m": float(np.mean(np.abs(along))),
        "mean_abs_cross_m": float(np.mean(np.abs(cross))),
    }


@njit
def _point_segment(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    if denom <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * abx + (py - ay) * aby) / denom
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(ax + t * abx - px, ay + t * aby - py)


@njit
def _directed(points, n_points, poly, n_poly, step):
    worst = 0.0
    for index in range(n_points - 1):
        ax, ay = points[index, 0], points[index, 1]
        bx, by = points[index + 1, 0], points[index + 1, 1]
        seglen = math.hypot(bx - ax, by - ay)
        pieces = 1 if seglen <= step else int(math.ceil(seglen / step))
        for sample in range(pieces + 1):
            t = sample / pieces
            px, py = ax + t * (bx - ax), ay + t * (by - ay)
            best = 1e300
            for segment in range(n_poly - 1):
                dist = _point_segment(px, py, poly[segment, 0], poly[segment, 1], poly[segment + 1, 0], poly[segment + 1, 1])
                if dist < best:
                    best = dist
            if best > worst:
                worst = best
    return worst


@njit(parallel=True)
def _vertex_matrix(polys, lengths):
    count = len(lengths)
    out = np.empty((count, count))
    for left in prange(count):
        out[left, left] = 0.0
        for right in range(left + 1, count):
            forward = _directed(polys[left], lengths[left], polys[right], lengths[right], 1e9)
            backward = _directed(polys[right], lengths[right], polys[left], lengths[left], 1e9)
            dist = forward if forward >= backward else backward
            out[left, right] = out[right, left] = dist
    return out


@njit(parallel=True)
def _refine(polys, lengths, pairs):
    out = np.empty(len(pairs))
    for index in prange(len(pairs)):
        left, right = pairs[index, 0], pairs[index, 1]
        forward = _directed(polys[left], lengths[left], polys[right], lengths[right], 2.0)
        backward = _directed(polys[right], lengths[right], polys[left], lengths[left], 2.0)
        out[index] = forward if forward >= backward else backward
    return out


def symmetric_hausdorff(points: list[np.ndarray]) -> tuple[np.ndarray, dict]:
    max_points = max(len(item) for item in points)
    packed = np.zeros((len(points), max_points, 2))
    lengths = np.array([len(item) for item in points], dtype=np.int64)
    for index, item in enumerate(points):
        packed[index, : len(item)] = item
    vertex = _vertex_matrix(packed, lengths)
    pairs = np.argwhere(np.triu(vertex <= 52.0, 1))
    distance = vertex.copy()
    if len(pairs):
        refined = _refine(packed, lengths, pairs.astype(np.int64))
        for (left, right), value in zip(pairs, refined):
            distance[int(left), int(right)] = distance[int(right), int(left)] = float(value)
    gap = (distance - vertex)[pairs[:, 0], pairs[:, 1]] if len(pairs) else np.empty(0)
    meta = {
        "definition": HAUSDORFF_DEFINITION,
        "refined_pairs": int(len(pairs)),
        "sampled_minus_vertex_max": float(gap.max()) if len(gap) else 0.0,
        "sampled_minus_vertex_p95": float(np.percentile(gap, 95)) if len(gap) else 0.0,
    }
    return distance, meta
