# -*- coding: utf-8 -*-
"""
dsop/path_metrics.py
────────────────────
Path encoding/decoding, polyline geometry utilities, and the multi-objective
evaluation function `compute_path_metrics`.

Public API
----------
compute_path_metrics(path, grid_map)    -> (F_list, G_list)
decode_solution_to_path(row, start, end)-> list of (x,y) tuples
_encode_path_to_legacy_row(path, ...)   -> np.ndarray  (chromosome row)
_canonicalize_objective_batch(metrics)  -> np.ndarray  readable coords
_normalize_readable_for_scoring(readable)-> np.ndarray  [0,1] lower-better
_normalize_weight_vector(weights, n_obj)-> np.ndarray
_resample_polyline(points, n)           -> np.ndarray
_sample_polyline_cells_sparse(...)      -> np.ndarray  (N,2) int32
_project_to_valid_cell(pt, grid_map)    -> (x, y) tuple
set_reproducible_rng(seed)             seeding helper that also clears the cache
"""

import random
import numpy as np
from typing import List, Optional, Sequence, Tuple

from dsop.constants import (
    DEFAULT_N_OBJ, DEFAULT_WEIGHTS,
    MIN_TOWERS, MAX_TOWERS,
    LINE_SAMPLE_SPACING, LINE_COST_WEIGHT, LINE_LANDUSE_REF_LENGTH,
    BEND_COST_FREE_ANGLE, BEND_COST_SHARP_ANGLE,
    SAFETY_CLEARANCE_REF, SAFETY_CLEARANCE_WEIGHT, SAFETY_HUMAN_EXPOSURE_WEIGHT,
    _TERRAIN_SITING_COST_ARR, _LINE_CROSSING_COST_ARR, _LINE_TERRAIN_COST_ARR,
    _LINE_TERRAIN_BASE_COST, RESIDENT_CODES, PREFERENCE_MAXIMIZE_IDXS,
    _maximize_objective_indices, _flip_higher_is_better_columns,
)
from dsop.map_cache import _get_distance_map, _get_safety_clearance_distance_map
from dsop.evaluation_archive import record_active_evaluation

# ─────────────────────────────────────────────
# Path-metrics cache (cleared by set_reproducible_rng)
# ─────────────────────────────────────────────

_PATH_METRICS_CACHE: dict = {}
_PATH_METRICS_CACHE_MAX = 8192

# ─────────────────────────────────────────────
# RNG seeding
# ─────────────────────────────────────────────

def set_reproducible_rng(seed: int) -> None:
    """Seed ``random`` and ``numpy.random`` for repeatable experiments.

    Also invalidates the path-metrics cache so cached values computed under a
    previous cost-function state are not reused.
    """
    global _PATH_METRICS_CACHE
    random.seed(int(seed))
    np.random.seed(int(seed))
    _PATH_METRICS_CACHE = {}


# ─────────────────────────────────────────────
# Weight-vector helpers
# ─────────────────────────────────────────────

def _normalize_weight_vector(
    weights: Optional[Sequence[float]], n_obj: int = DEFAULT_N_OBJ
) -> np.ndarray:
    """Return a non-negative, sum-to-1 weight vector of length n_obj."""
    w = np.asarray(weights if weights is not None else DEFAULT_WEIGHTS, dtype=float).reshape(-1)
    w = np.clip(np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0), 0.0, None)

    if w.size < n_obj:
        w = np.pad(w, (0, n_obj - w.size), constant_values=0.0)
    elif w.size > n_obj:
        w = w[:n_obj]

    if float(w.sum()) <= 1e-12:
        w = np.ones(n_obj, dtype=float)
    return w / (w.sum() + 1e-12)


# ─────────────────────────────────────────────
# Objective-space transforms
# ─────────────────────────────────────────────

def _canonicalize_objective_batch(metrics: Sequence[Sequence[float]]) -> np.ndarray:
    """Convert raw objectives to readable-space (flip sign of minimised safety/smoothness)."""
    arr = np.asarray(metrics, dtype=float)
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.shape[1] >= 4:
        return np.column_stack([arr[:, 0], arr[:, 1], -arr[:, 2], -arr[:, 3]])
    if arr.shape[1] == 3:
        return np.column_stack([arr[:, 0], arr[:, 1], -arr[:, 2]])
    return arr.copy()


def _normalize_readable_for_scoring(readable: np.ndarray) -> np.ndarray:
    """Normalise readable objectives to [0,1], then flip higher-is-better columns."""
    arr = np.asarray(readable, dtype=float)
    if arr.ndim == 1:
        arr = arr[None, :]
    arr = arr.copy()
    mins  = arr.min(axis=0)
    maxs  = arr.max(axis=0)
    denom = maxs - mins + 1e-8
    normed = (arr - mins) / denom
    return _flip_higher_is_better_columns(normed)


# ─────────────────────────────────────────────
# Polyline geometry
# ─────────────────────────────────────────────

def _dedup_consecutive_points(points: Sequence[Sequence[float]]) -> List[tuple]:
    """Remove consecutive duplicate (x,y) points."""
    dedup: List[tuple] = []
    for pt in points:
        p = (int(pt[0]), int(pt[1]))
        if not dedup or p != dedup[-1]:
            dedup.append(p)
    return dedup


def _polyline_cumlen(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=float)
    if len(pts) <= 1:
        return np.zeros(len(pts), dtype=float)
    seg = np.sqrt(np.sum(np.diff(pts, axis=0) ** 2, axis=1))
    return np.concatenate([[0.0], np.cumsum(seg)])


def _resample_polyline(points, n_samples: int) -> np.ndarray:
    """Uniformly re-sample a polyline to exactly n_samples points."""
    pts = np.asarray(points, dtype=float)
    if len(pts) == 0:
        return np.zeros((0, 2), dtype=float)
    if len(pts) == 1 or n_samples <= 1:
        return np.repeat(pts[:1], max(int(n_samples), 1), axis=0)

    cum   = _polyline_cumlen(pts)
    total = float(cum[-1])
    if total <= 1e-8:
        return np.repeat(pts[:1], n_samples, axis=0)

    targets = np.linspace(0.0, total, int(n_samples))
    xs = np.interp(targets, cum, pts[:, 0])
    ys = np.interp(targets, cum, pts[:, 1])
    return np.column_stack([xs, ys])


def _sample_polyline_cells_sparse(
    path_arr: np.ndarray,
    shape: Sequence[int],
    spacing: float = LINE_SAMPLE_SPACING,
) -> np.ndarray:
    """Sample integer grid cells along a polyline at `spacing`-pixel intervals."""
    pts = np.asarray(path_arr, dtype=np.float64)
    if len(pts) == 0:
        return np.zeros((0, 2), dtype=np.int32)
    if len(pts) == 1:
        single = np.rint(pts).astype(np.int32)
        single[:, 0] = np.clip(single[:, 0], 0, shape[1] - 1)
        single[:, 1] = np.clip(single[:, 1], 0, shape[0] - 1)
        return single

    step = max(float(spacing), 1.0)
    sampled_chunks = [np.rint(pts[:1]).astype(np.int32)]

    for p0, p1 in zip(pts[:-1], pts[1:]):
        seg     = p1 - p0
        seg_len = float(np.linalg.norm(seg))
        if seg_len <= 1e-8:
            continue
        n_steps  = max(1, int(np.ceil(seg_len / step)))
        ts       = np.linspace(1.0 / n_steps, 1.0, n_steps, dtype=np.float64)
        seg_pts  = p0[None, :] + ts[:, None] * seg[None, :]
        sampled_chunks.append(np.rint(seg_pts).astype(np.int32))

    cells        = np.vstack(sampled_chunks)
    cells[:, 0]  = np.clip(cells[:, 0], 0, shape[1] - 1)
    cells[:, 1]  = np.clip(cells[:, 1], 0, shape[0] - 1)

    keep = np.ones(len(cells), dtype=bool)
    if len(cells) > 1:
        keep[1:] = np.any(cells[1:] != cells[:-1], axis=1)
    return cells[keep]


def _project_to_valid_cell(
    pt, grid_map, max_radius: int = 3, prefer_safety: float = 0.0
) -> tuple:
    """Find the nearest non-resident cell; bias towards safer cells when prefer_safety > 0."""
    h, w = grid_map.shape
    x = int(np.clip(np.rint(pt[0]), 0, w - 1))
    y = int(np.clip(np.rint(pt[1]), 0, h - 1))
    if grid_map[y, x] not in RESIDENT_CODES:
        return (x, y)

    distance_map = _get_distance_map()
    safe_pref    = float(np.clip(prefer_safety, 0.0, 1.0))
    best         = None
    best_key     = None
    for r in range(1, max_radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and grid_map[ny, nx] not in RESIDENT_CODES:
                    dist2    = float(dx * dx + dy * dy)
                    safe     = float(distance_map[ny, nx])
                    weighted = (1.0 - safe_pref) * dist2 - safe_pref * 2.0 * safe
                    key      = (weighted, dist2, -safe)
                    if best_key is None or key < best_key:
                        best_key = key
                        best     = (nx, ny)
        if best is not None:
            return best
    return (x, y)


# ─────────────────────────────────────────────
# Chromosome encoding / decoding
# ─────────────────────────────────────────────

def _encode_path_to_legacy_row(
    path: Sequence[Sequence[float]],
    grid_map,
    num_towers: Optional[int] = None,
    prefer_safety: float = 0.0,
) -> np.ndarray:
    """Convert an arbitrary polyline into the legacy absolute-coordinate chromosome."""
    k   = int(np.clip(MAX_TOWERS if num_towers is None else num_towers, MIN_TOWERS, MAX_TOWERS))
    pts = np.asarray(path, dtype=float)
    if pts.ndim != 2 or len(pts) < 2:
        raise ValueError("Path must contain at least start/end points")

    resampled = _resample_polyline(pts, k + 2)
    snapped   = [
        _project_to_valid_cell(pt, grid_map, max_radius=4, prefer_safety=prefer_safety)
        for pt in resampled
    ]
    snapped[0]  = (int(round(pts[0, 0])), int(round(pts[0, 1])))
    snapped[-1] = (int(round(pts[-1, 0])), int(round(pts[-1, 1])))
    dedup = _dedup_consecutive_points(snapped)
    if len(dedup) < 2:
        dedup = [snapped[0], snapped[-1]]
    if len(dedup) != k + 2:
        dense   = _resample_polyline(np.asarray(dedup, dtype=float), k + 2)
        snapped = [
            _project_to_valid_cell(pt, grid_map, max_radius=4, prefer_safety=prefer_safety)
            for pt in dense
        ]
        snapped[0]  = dedup[0]
        snapped[-1] = dedup[-1]
    else:
        snapped = dedup

    row       = np.zeros(1 + 2 * MAX_TOWERS, dtype=float)
    row[0]    = k
    mids      = np.asarray(snapped[1:-1], dtype=float).reshape(-1)
    row[1:1 + 2 * k] = mids
    return row


def _row_signature(row: np.ndarray) -> tuple:
    """Compact integer representation of a chromosome row, used for deduplication."""
    arr    = np.asarray(row, dtype=float).copy()
    arr[0] = np.clip(np.round(arr[0]), MIN_TOWERS, MAX_TOWERS)
    arr[1:] = np.rint(arr[1:])
    return tuple(arr.astype(int).tolist())


def decode_solution_to_path(decision_vars: np.ndarray, start: tuple, end: tuple):
    """Decode a legacy-absolute chromosome row into an ordered list of (x,y) waypoints."""
    row           = np.asarray(decision_vars, dtype=float)
    k             = int(np.clip(np.round(row[0]), MIN_TOWERS, MAX_TOWERS))
    coords        = np.rint(row[1:1 + 2 * k]).astype(int)
    intermediates = [(int(coords[j]), int(coords[j + 1])) for j in range(0, 2 * k, 2)]
    return [start] + intermediates + [end]


# ─────────────────────────────────────────────
# Multi-objective path evaluation
# ─────────────────────────────────────────────

def compute_path_metrics(path, grid_map):
    """Return ([cost, length, safe_obj, bend_obj], [g_length, g_sharp_turn]).

    All four objectives are minimised by the evolutionary core.
    Constraints satisfy g <= 0 ⟹ feasible.

    Objectives
    ----------
    cost      tower siting cost + terrain/crossing premium
    length    Euclidean path length in pixels
    safe_obj  negative safety score (lower = safer); safety uses hazard
              clearance on routing_coarse maps (building, road, water)
    bend_obj  smoothness penalty extracted from angles between consecutive segments
    """
    global _PATH_METRICS_CACHE
    # The evaluation archive keys decisions in exact float64 coordinates.
    # Using a float32 projection here lets distinct long paths collide and
    # attaches the first path's objectives to the second exact decision.
    _cache_key = np.ascontiguousarray(path, dtype=np.float64).tobytes()
    _cached    = _PATH_METRICS_CACHE.get(_cache_key)
    if _cached is not None:
        record_active_evaluation(
            path=path,
            objectives=_cached[0],
            constraints=_cached[1],
        )
        return _cached[0], _cached[1]

    distance_map = _get_distance_map()
    path_arr = np.asarray(path, dtype=np.float64)
    n = len(path_arr)

    y_idx = np.clip(path_arr[:, 1].astype(np.int32), 0, grid_map.shape[0] - 1)
    x_idx = np.clip(path_arr[:, 0].astype(np.int32), 0, grid_map.shape[1] - 1)

    terrains          = np.clip(np.asarray(grid_map[y_idx, x_idx], dtype=np.int32), 0, 511)
    internal_terrains = terrains[1:-1] if len(terrains) > 2 else np.zeros(0, dtype=np.int32)
    tower_cost        = float(np.sum(_TERRAIN_SITING_COST_ARR[internal_terrains]))

    length = float(np.sum(np.sqrt(np.sum(np.diff(path_arr, axis=0) ** 2, axis=1)))) if n > 1 else 0.0

    if n > 2:
        v1   = path_arr[1:-1] - path_arr[:-2]
        v2   = path_arr[2:]   - path_arr[1:-1]
        norm1 = np.linalg.norm(v1, axis=1)
        norm2 = np.linalg.norm(v2, axis=1)
        dots  = np.sum(v1 * v2, axis=1)
        angles = np.arccos(np.clip(dots / (norm1 * norm2 + 1e-8), -1.0, 1.0))
        sharp_turn_violation = float(np.sum(np.maximum(0.0, angles - np.pi / 3)))
        mild_turn  = np.maximum(0.0, angles - BEND_COST_FREE_ANGLE)
        sharp_turn = np.maximum(0.0, angles - BEND_COST_SHARP_ANGLE)
        bend_obj   = float(np.sum(0.45 * np.square(mild_turn) + 1.75 * np.square(sharp_turn)))
    else:
        sharp_turn_violation = 0.0
        bend_obj             = 0.0

    line_cells = _sample_polyline_cells_sparse(path_arr, grid_map.shape, spacing=LINE_SAMPLE_SPACING)
    line_y, line_x = line_cells[:, 1], line_cells[:, 0]

    line_terrains     = np.clip(np.asarray(grid_map[line_y, line_x], dtype=np.int32), 0, 511)
    line_cross_penalty = float(np.sum(_LINE_CROSSING_COST_ARR[line_terrains]))

    if len(line_terrains) > 0:
        terrain_premium  = np.maximum(_LINE_TERRAIN_COST_ARR[line_terrains] - _LINE_TERRAIN_BASE_COST, 0.0)
        line_landuse_cost = float(np.sum(terrain_premium)) * LINE_SAMPLE_SPACING / LINE_LANDUSE_REF_LENGTH
    else:
        line_landuse_cost = 0.0

    clearance_dm = _get_safety_clearance_distance_map()
    hazard_clearances = np.asarray(clearance_dm[line_y, line_x], dtype=np.float64)
    q10_clearance = float(np.percentile(hazard_clearances, 10))
    clearance_norm = float(np.clip(q10_clearance / max(SAFETY_CLEARANCE_REF, 1e-8), 0.0, 1.0))
    human_exposure_ratio = float(np.mean(hazard_clearances < SAFETY_CLEARANCE_REF))
    safety_score = (
        SAFETY_CLEARANCE_WEIGHT * clearance_norm
        + SAFETY_HUMAN_EXPOSURE_WEIGHT * (1.0 - human_exposure_ratio)
    )
    safe_obj = -safety_score
    cost     = tower_cost + line_landuse_cost + LINE_COST_WEIGHT * line_cross_penalty

    MAX_LENGTH = 3000.0
    g_length     = length - MAX_LENGTH
    g_sharp_turn = sharp_turn_violation

    _result_F = [cost, length, safe_obj, bend_obj]
    _result_G = [g_length, g_sharp_turn]

    if len(_PATH_METRICS_CACHE) >= _PATH_METRICS_CACHE_MAX:
        evict = list(_PATH_METRICS_CACHE.keys())[: _PATH_METRICS_CACHE_MAX // 2]
        for _k in evict:
            del _PATH_METRICS_CACHE[_k]
    _PATH_METRICS_CACHE[_cache_key] = (_result_F, _result_G)
    record_active_evaluation(
        path=path,
        objectives=_result_F,
        constraints=_result_G,
    )
    return _result_F, _result_G
