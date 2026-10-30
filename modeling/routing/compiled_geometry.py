"""Float64 exact grid kernels; fastmath is deliberately disabled."""

import math

import numpy as np
from numba import njit, prange

from .geometry import DISTANCE_TOL_M


@njit(cache=True, nogil=True)
def dem_value(dem, x, y):
    height, width = dem.shape
    if not (0 <= x <= width and 0 <= y <= height):
        return np.nan
    x, y = min(max(x - .5, 0), width - 1), min(max(y - .5, 0), height - 1)
    col, row = int(x), int(y)
    right, bottom = min(col + 1, width - 1), min(row + 1, height - 1)
    fx, fy = x - col, y - row
    value = 0.
    for rr, cc, weight in ((row, col, (1 - fx) * (1 - fy)), (row, right, fx * (1 - fy)),
                           (bottom, col, (1 - fx) * fy), (bottom, right, fx * fy)):
        if weight > 0:
            value += float(dem[rr, cc]) * weight
    return value


# A unit square stays within √1/2 of its center. The extra 0.05 covers float32 field rounding.
_CENTER_SLACK = 0.7071067811865476 + 0.05


@njit(cache=True, nogil=True)
def _clearance_class(field, x, y, limit, margin):
    """1 when the disk hits, 0 when it misses, -1 when the bound is too close to call."""
    if field.ndim != 2:
        return 0
    height, width = field.shape
    row0, col0 = math.floor(y - 0.5), math.floor(x - 0.5)
    lower, upper, found = -math.inf, math.inf, False
    for dr in range(2):
        for dc in range(2):
            row, col = row0 + dr, col0 + dc
            if 0 <= row < height and 0 <= col < width:
                gap = math.hypot((col + 0.5) - x, (row + 0.5) - y)
                center = float(field[row, col])
                lower = max(lower, center - gap - _CENTER_SLACK)
                upper = min(upper, center + gap + _CENTER_SLACK)
                found = True
    if not found:
        return -1
    hit, clear = upper <= limit - margin, lower > limit + margin
    if hit == clear:
        return -1
    return 1 if hit else 0


@njit(cache=True, nogil=True)
def clearance_tower_flags(blocked_distance, missing_distance, dem, blocked, x, y, radius):
    height, width = dem.shape
    scale = max(1., abs(x), abs(y), radius)
    limit = radius + 32 * np.finfo(np.float64).eps * scale
    margin = 128 * np.finfo(np.float64).eps * scale * max(1., radius) / (2 * max(limit, 1e-6)) + 1e-6
    boundary = (abs(x - radius) < 1e-8 or abs(y - radius) < 1e-8
                or abs(x - (width - radius)) < 1e-8 or abs(y - (height - radius)) < 1e-8)
    blocked_class = _clearance_class(blocked_distance, x, y, limit, margin)
    missing_class = _clearance_class(missing_distance, x, y, limit, margin)
    if boundary or blocked_class < 0 or missing_class < 0:
        return tower_flags(dem, blocked, x, y, radius)
    outside = not (radius <= x <= width - radius and radius <= y <= height - radius)
    missing = (not math.isfinite(dem_value(dem, x, y))) or missing_class == 1
    return outside, blocked_class == 1, missing


@njit(cache=True, nogil=True)
def _placeable(blocked_distance, missing_distance, dem, blocked, x, y, radius):
    outside, hit, missing = clearance_tower_flags(blocked_distance, missing_distance, dem, blocked, x, y, radius)
    return not (outside or hit or missing)


@njit(cache=True, nogil=True)
def _score_clearance(field, x, y, radius, width, height):
    margin = min(x, y, width - x, height - y) - radius
    if field.ndim == 2:
        row = min(max(int(math.floor(y)), 0), int(height) - 1)
        col = min(max(int(math.floor(x)), 0), int(width) - 1)
        margin = min(margin, float(field[row, col]) - radius)
    return max(0., margin)


@njit(cache=True, nogil=True)
def project_clearance_points(xs, ys, rings, blocked_distance, missing_distance, dem, blocked, score_field,
                             scale, tower_radius, prefer, width, height):
    """Same first-ring and (score, squared offset, clearance) winner as the tensor ring walk.

    Also returns the ring that supplied the winner: 0 when the point is already placeable, ring + 1 when none did.
    """
    out_x, out_y = xs.copy(), ys.copy()
    found_rings = np.zeros(len(xs), np.int64)
    for i in range(len(xs)):
        x, y, ring = xs[i], ys[i], rings[i]
        if _placeable(blocked_distance, missing_distance, dem, blocked, x, y, tower_radius):
            continue
        nearest = ring + 1
        for dy in range(-ring, ring + 1):
            for dx in range(-ring, ring + 1):
                chebyshev = max(abs(dx), abs(dy))
                if chebyshev == 0 or chebyshev >= nearest:
                    continue
                if _placeable(blocked_distance, missing_distance, dem, blocked, x + scale * dx, y + scale * dy, tower_radius):
                    nearest = chebyshev
        found_rings[i] = nearest
        if nearest > ring:
            continue
        found = False
        best_x, best_y, best_score, best_d2, best_clear = x, y, 0., 0., 0.
        for dy in range(-nearest, nearest + 1):
            for dx in range(-nearest, nearest + 1):
                cx, cy = x + scale * dx, y + scale * dy
                if not _placeable(blocked_distance, missing_distance, dem, blocked, cx, cy, tower_radius):
                    continue
                d2 = float(dx * dx + dy * dy)
                clear = _score_clearance(score_field, cx, cy, tower_radius, width, height)
                score = (1. - prefer) * d2 - prefer * 2. * (clear / scale)
                better = (not found or score < best_score or (score == best_score and d2 < best_d2)
                          or (score == best_score and d2 == best_d2 and clear > best_clear))
                if better:
                    found = True
                    best_x, best_y, best_score, best_d2, best_clear = cx, cy, score, d2, clear
        out_x[i], out_y[i] = best_x, best_y
    return out_x, out_y, found_rings


@njit(cache=True, nogil=True)
def tower_flags(dem, blocked, x, y, radius):
    height, width = dem.shape
    limit = radius + 32 * np.finfo(np.float64).eps * max(1., abs(x), abs(y), radius)
    outside = not (radius <= x <= width - radius and radius <= y <= height - radius)
    hit, missing = False, not math.isfinite(dem_value(dem, x, y))
    for row in range(max(0, math.ceil(y - limit) - 1), min(height - 1, math.floor(y + limit)) + 1):
        for col in range(max(0, math.ceil(x - limit) - 1), min(width - 1, math.floor(x + limit)) + 1):
            dx = x - min(max(x, col), col + 1)
            dy = y - min(max(y, row), row + 1)
            if dx * dx + dy * dy <= limit * limit:
                hit |= blocked[row, col]
                missing |= not math.isfinite(dem[row, col])
    return outside, hit, missing


@njit(cache=True, nogil=True)
def crossing_length(start, end, mask):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length == 0:
        return 0.
    capacity = int(abs(dx)) + int(abs(dy)) + 6
    boundaries = np.empty(capacity)
    boundaries[0], boundaries[1] = 0., 1.
    size = 2
    for axis in range(2):
        delta = end[axis] - start[axis]
        if delta != 0:
            lo, hi = min(start[axis], end[axis]), max(start[axis], end[axis])
            for line in range(math.floor(lo) + 1, math.ceil(hi)):
                boundaries[size] = (line - start[axis]) / delta
                size += 1
    boundaries = np.sort(boundaries[:size])
    total = 0.
    edge_x = dx == 0 and start[0] == math.floor(start[0])
    edge_y = dy == 0 and start[1] == math.floor(start[1])
    for i in range(size - 1):
        left, right = boundaries[i], boundaries[i + 1]
        if left == right:
            continue
        t = (left + right) / 2
        col, row = math.floor(start[0] + t * dx), math.floor(start[1] + t * dy)
        hit = False
        for dc in range(2 if edge_x else 1):
            for dr in range(2 if edge_y else 1):
                rr, cc = row - dr, col - dc
                if 0 <= rr < mask.shape[0] and 0 <= cc < mask.shape[1]:
                    hit |= mask[rr, cc]
        if hit:
            total += right - left
    return total * length


@njit(cache=True, nogil=True)
def evaluate_route(points, dem, blocked, crossing, radius, max_span, max_turn):
    count = len(points) - 2
    values = np.zeros(8)
    elevations = np.empty(len(points))
    spans = np.zeros((len(points) - 1, 3))
    turns = np.zeros(count)
    tower_hits = np.zeros(count, dtype=np.bool_)
    for i in range(len(points)):
        elevations[i] = dem_value(dem, points[i, 0], points[i, 1])
        if i == 0 or i == len(points) - 1:
            values[3] += not math.isfinite(elevations[i])
        else:
            outside, hit, missing = tower_flags(dem, blocked, points[i, 0], points[i, 1], radius)
            values[1] += outside
            values[2] += hit
            values[3] += missing
            tower_hits[i - 1] = hit
    for i in range(1, len(points) - 1):
        for j in range(i + 1, len(points) - 1):
            delta = points[i] - points[j]
            overlap = 2 * radius - math.sqrt(delta[0]**2 + delta[1]**2)
            if overlap > DISTANCE_TOL_M:
                values[4] += overlap
    for i in range(len(points) - 1):
        delta = points[i + 1] - points[i]
        distance = math.sqrt(delta[0]**2 + delta[1]**2)
        spatial = math.hypot(distance, elevations[i + 1] - elevations[i])
        values[0] += distance == 0
        if distance - max_span > DISTANCE_TOL_M:
            values[5] += distance - max_span
        spans[i, 0], spans[i, 1] = distance, spatial
        if distance > 0 and (0 <= points[i, 0] <= dem.shape[1] and 0 <= points[i, 1] <= dem.shape[0]
                            and 0 <= points[i + 1, 0] <= dem.shape[1] and 0 <= points[i + 1, 1] <= dem.shape[0]):
            spans[i, 2] = spatial * crossing_length(points[i], points[i + 1], crossing) / distance
        if i:
            previous = points[i] - points[i - 1]
            previous_length = spans[i - 1, 0]
            a = previous / max(previous_length, np.finfo(np.float64).tiny)
            b = delta / max(distance, np.finfo(np.float64).tiny)
            # A zero span is invalid geometry; signed zero must not add a pi turn.
            angle = 0. if distance == 0 or previous_length == 0 else math.atan2(
                abs(a[0] * b[1] - a[1] * b[0]), a[0] * b[0] + a[1] * b[1])
            turns[i - 1] = angle
            if angle - max_turn > 1e-12:
                values[6] += angle - max_turn
    objectives = np.array([float(count), spans[:, 1].sum(), turns.sum(), spans[:, 2].sum()])
    for i in range(4):
        if not math.isfinite(objectives[i]):
            objectives[i] = math.inf
    return objectives, values, elevations, spans, tower_hits


@njit(cache=True, nogil=True, parallel=True)
def evaluate_routes_compact(towers, counts, start, end, dem, blocked, crossing,
                            radius, max_span, max_turn):
    """Evaluate packed variable-length routes in parallel without reports."""
    objectives = np.empty((len(towers), 4), dtype=np.float64)
    values = np.empty((len(towers), 8), dtype=np.float64)
    for index in prange(len(towers)):
        count = counts[index]
        points = np.empty((count + 2, 2), dtype=np.float64)
        points[0] = start
        for tower in range(count):
            points[tower + 1] = towers[index, tower]
        points[count + 1] = end
        objective, violation, _, _, _ = evaluate_route(
            points, dem, blocked, crossing, radius, max_span, max_turn)
        objectives[index] = objective
        values[index] = violation
    return objectives, values
