# -*- coding: utf-8 -*-
"""
dsop/path_operators.py
──────────────────────
Path-level variation and local-search operators used by the evolutionary core.

Operators
---------
_path_crossover_operator     recombine two parent paths at their nearest waypoints
_path_mutation_operator      perturb a single random intermediate waypoint
_shorten_path_operator       greedily remove waypoints that are no longer needed
_smoothness_path_operator    move high-angle waypoints toward their neighbours
_safety_path_operator        shift high-risk segments away from obstacles
_local_mutation_operator     small random perturbations on interior points
_adaptive_vns_local_search_operator  adaptive VNS for elite post-survival refinement

Helpers
-------
_distance_gradient_at        gradient of the distance map at a pixel
_path_internal_point_clearances  clearance values for non-terminal waypoints
_adaptive_neighborhood_radius    clearance-based perturbation radius
_path_is_collision_free      check every segment of a path
_sanitize_path_candidate     snap + dedup after creating a new candidate path
_select_better_path_bundle   compare two paths and return the better one
_segment_risk_score          combined proximity + terrain risk of a line segment
"""

import random
import numpy as np
from typing import List, Optional, Sequence, Tuple

from dsop.constants import (
    MAX_TOWERS, LINE_SAMPLE_SPACING, RESIDENT_CODES,
    PATH_CROSSOVER_MAX_PAIRS, PATH_MUTATION_TRIES,
    _neutral_prefer_safety,
)
from dsop.map_cache import _get_distance_map, _get_distance_gradients
from dsop.path_metrics import (
    compute_path_metrics, decode_solution_to_path,
    _project_to_valid_cell, _dedup_consecutive_points, _resample_polyline,
    _sample_polyline_cells_sparse,
)
from dsop.path_planners import _edge_is_collision_free
from dsop.preference import PreferenceGuidance, _candidate_is_better

# ─────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────

def _distance_gradient_at(point: Sequence[float]) -> np.ndarray:
    """Unit gradient vector of the distance-from-obstacles map at a pixel."""
    gx, gy = _get_distance_gradients()
    dm = _get_distance_map()
    x  = int(np.clip(round(float(point[0])), 0, dm.shape[1] - 1))
    y  = int(np.clip(round(float(point[1])), 0, dm.shape[0] - 1))
    g  = np.array([gx[y, x], gy[y, x]], dtype=float)
    n  = np.linalg.norm(g)
    if n <= 1e-8:
        return np.zeros(2, dtype=float)
    return g / n


def _path_internal_point_clearances(path: Sequence[Sequence[float]]) -> np.ndarray:
    """Return the distance-map clearance at each non-terminal waypoint."""
    dm  = _get_distance_map()
    pts = np.asarray(path, dtype=float)
    if len(pts) <= 2:
        return np.zeros(0, dtype=float)
    mids = pts[1:-1]
    x = np.clip(np.rint(mids[:, 0]).astype(int), 0, dm.shape[1] - 1)
    y = np.clip(np.rint(mids[:, 1]).astype(int), 0, dm.shape[0] - 1)
    return dm[y, x]


def _adaptive_neighborhood_radius(path: Sequence[Sequence[float]], idx: int) -> float:
    """Return a perturbation radius calibrated to local obstacle clearance."""
    clearances = _path_internal_point_clearances(path)
    if len(clearances) == 0:
        return 6.0
    local_idx   = int(np.clip(idx - 1, 0, len(clearances) - 1))
    local_clear = float(clearances[local_idx])
    return float(np.clip(2.0 + 0.9 * local_clear, 3.0, 14.0))


# ─────────────────────────────────────────────
# Path validity / sanitisation
# ─────────────────────────────────────────────

def _path_is_collision_free(path: Sequence[Sequence[float]], grid_map) -> bool:
    pts = list(map(tuple, path))
    if len(pts) < 2:
        return False
    for p0, p1 in zip(pts[:-1], pts[1:]):
        if not _edge_is_collision_free(p0, p1, grid_map):
            return False
    return True


def _sanitize_path_candidate(
    path: Sequence[Sequence[float]],
    grid_map,
    prefer_safety: float = 0.0,
) -> Optional[List[tuple]]:
    """Snap all interior waypoints to valid cells and remove consecutive duplicates."""
    pts = np.asarray(path, dtype=float)
    if pts.ndim != 2 or len(pts) < 2:
        return None

    snapped: List[tuple] = []
    for idx, pt in enumerate(pts):
        if idx == 0 or idx == len(pts) - 1:
            snapped.append((int(round(float(pt[0]))), int(round(float(pt[1])))))
        else:
            snapped.append(_project_to_valid_cell(pt, grid_map, max_radius=6, prefer_safety=prefer_safety))

    dedup = _dedup_consecutive_points(snapped)
    if len(dedup) < 2:
        return None
    if len(dedup) > MAX_TOWERS + 2:
        dense = _resample_polyline(np.asarray(dedup, dtype=float), MAX_TOWERS + 2)
        dedup = [tuple(map(int, np.rint(pt))) for pt in dense]
        dedup = _dedup_consecutive_points(dedup)
    if len(dedup) < 2:
        return None
    return dedup


def _select_better_path_bundle(
    current_path: Sequence[Sequence[float]],
    cand_path: Sequence[Sequence[float]],
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
    target_idx: Optional[int] = None,
    target_margin: float = 0.0,
):
    """Evaluate both paths and return the better one (path, F, G)."""
    cur_F,  cur_G  = compute_path_metrics(current_path, grid_map)
    cand_F, cand_G = compute_path_metrics(cand_path,    grid_map)
    if _candidate_is_better(
        cur_F, cur_G, cand_F, cand_G,
        guidance=guidance, target_idx=target_idx, target_margin=target_margin,
    ):
        return list(map(tuple, cand_path)), cand_F, cand_G
    return list(map(tuple, current_path)), cur_F, cur_G


def _segment_risk_score(
    p0: Sequence[float], p1: Sequence[float], grid_map
) -> Tuple[float, np.ndarray]:
    """Scalar risk of a line segment: inverse clearance + resident-cell count + length."""
    seg   = np.asarray([p0, p1], dtype=float)
    cells = _sample_polyline_cells_sparse(seg, grid_map.shape, spacing=max(1.0, LINE_SAMPLE_SPACING * 0.35))
    if len(cells) == 0:
        return 0.0, cells

    dm         = _get_distance_map()
    clearances = np.asarray(dm[cells[:, 1], cells[:, 0]], dtype=float)
    terrains   = np.asarray(grid_map[cells[:, 1], cells[:, 0]], dtype=int)
    risk = (
        float(np.sum(1.0 / (clearances + 1.0)))
        + 2.5 * float(np.sum(np.isin(terrains, RESIDENT_CODES)))
        + 0.15 * len(cells)
    )
    return risk, cells


# ─────────────────────────────────────────────
# Crossover / mutation operators
# ─────────────────────────────────────────────

def _path_crossover_operator(
    path_a: Sequence[Sequence[float]],
    path_b: Sequence[Sequence[float]],
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
    max_pairs: Optional[int] = None,
):
    """Recombine two parents at their nearest-neighbour waypoints."""
    if max_pairs is None:
        max_pairs = int(PATH_CROSSOVER_MAX_PAIRS)
    curr_a = list(map(tuple, path_a))
    curr_b = list(map(tuple, path_b))
    best_path, best_F, best_G = _select_better_path_bundle(curr_a, curr_b, grid_map, guidance=guidance)

    if len(curr_a) <= 2 or len(curr_b) <= 2:
        return best_path, best_F, best_G

    pts_a  = np.asarray(curr_a, dtype=float)
    ints_b = np.asarray(curr_b, dtype=float)[1:-1]
    if len(ints_b) == 0:
        return best_path, best_F, best_G

    candidate_pairs = []
    for i in range(1, len(curr_a) - 1):
        deltas = ints_b - pts_a[i]
        d2     = np.sum(deltas * deltas, axis=1)
        j      = 1 + int(np.argmin(d2))
        candidate_pairs.append((float(np.min(d2)), i, j))
    candidate_pairs.sort(key=lambda item: item[0])

    _improved = False
    for _, i, j in candidate_pairs[: max(1, int(max_pairs))]:
        if not _edge_is_collision_free(curr_a[i], curr_b[j], grid_map):
            continue

        for raw_child in (
            curr_a[: i + 1] + [curr_b[j]] + curr_b[j + 1:],
            curr_b[: j + 1] + [curr_a[i]] + curr_a[i + 1:],
        ):
            child = _sanitize_path_candidate(raw_child, grid_map, prefer_safety=_neutral_prefer_safety())
            if child is None or not _path_is_collision_free(child, grid_map):
                continue
            cand_F, cand_G = compute_path_metrics(child, grid_map)
            if _candidate_is_better(best_F, best_G, cand_F, cand_G, guidance=guidance):
                best_path, best_F, best_G = child, cand_F, cand_G
                _improved = True
        if _improved:
            break

    return best_path, best_F, best_G


def _path_mutation_operator(
    path: Sequence[Sequence[float]],
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
    tries: int = PATH_MUTATION_TRIES,
):
    """Randomly perturb a single intermediate waypoint."""
    curr_path = list(map(tuple, path))
    curr_F, curr_G = compute_path_metrics(curr_path, grid_map)
    if len(curr_path) <= 2:
        return curr_path, curr_F, curr_G

    best_path, best_F, best_G = curr_path, curr_F, curr_G
    idx    = random.randint(1, len(curr_path) - 2)
    radius = _adaptive_neighborhood_radius(curr_path, idx)
    base   = np.asarray(curr_path[idx], dtype=float)
    prev_pt = curr_path[idx - 1]
    next_pt = curr_path[idx + 1]

    for _ in range(max(1, int(tries))):
        angle = float(np.random.uniform(0.0, 2.0 * np.pi))
        dist  = float(np.random.uniform(0.25, 1.0) * radius)
        moved = base + dist * np.array([np.cos(angle), np.sin(angle)], dtype=float)
        moved = _project_to_valid_cell(
            moved, grid_map, max_radius=int(max(3, round(radius))), prefer_safety=0.35
        )
        if not _edge_is_collision_free(prev_pt, moved, grid_map):
            continue
        if not _edge_is_collision_free(moved, next_pt, grid_map):
            continue

        cand = curr_path.copy()
        cand[idx] = moved
        cand = _dedup_consecutive_points(cand)
        if len(cand) < 2 or not _path_is_collision_free(cand, grid_map):
            continue

        cand_F, cand_G = compute_path_metrics(cand, grid_map)
        if _candidate_is_better(best_F, best_G, cand_F, cand_G, guidance=guidance):
            best_path, best_F, best_G = cand, cand_F, cand_G

    return best_path, best_F, best_G


# ─────────────────────────────────────────────
# Length / smoothness / safety refinement
# ─────────────────────────────────────────────

def _shorten_path_operator(
    path: Sequence[Sequence[float]],
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
):
    """Greedily remove intermediate waypoints that have free line-of-sight to skip."""
    curr_path = list(map(tuple, path))
    curr_F, curr_G = compute_path_metrics(curr_path, grid_map)
    best_path, best_F, best_G = curr_path, curr_F, curr_G

    if len(curr_path) <= 3:
        return best_path, best_F, best_G

    for idx in range(1, len(curr_path) - 1):
        if not _edge_is_collision_free(curr_path[idx - 1], curr_path[idx + 1], grid_map):
            continue
        cand = curr_path[:idx] + curr_path[idx + 1:]
        if len(cand) < 2:
            continue
        cand_F, cand_G = compute_path_metrics(cand, grid_map)
        if _candidate_is_better(
            best_F, best_G, cand_F, cand_G,
            guidance=guidance, target_idx=1, target_margin=1.0,
        ):
            best_path, best_F, best_G = cand, cand_F, cand_G
    return best_path, best_F, best_G


def _smoothness_path_operator(
    path: Sequence[Sequence[float]],
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
):
    """Move high-angle waypoints toward their neighbours to reduce bend penalty."""
    curr_path = list(map(tuple, path))
    curr_F, curr_G = compute_path_metrics(curr_path, grid_map)
    if len(curr_path) <= 2:
        return curr_path, curr_F, curr_G

    pts = np.asarray(curr_path, dtype=float)
    if len(pts) <= 3:
        idxs = [1]
    else:
        v1   = pts[1:-1] - pts[:-2]
        v2   = pts[2:]   - pts[1:-1]
        denom = np.linalg.norm(v1, axis=1) * np.linalg.norm(v2, axis=1) + 1e-8
        ang   = np.arccos(np.clip(np.sum(v1 * v2, axis=1) / denom, -1.0, 1.0))
        idxs  = (1 + np.argsort(-ang)).tolist()[: min(3, len(ang))]

    best_path, best_F, best_G = curr_path, curr_F, curr_G
    for idx in idxs:
        prev_pt = np.asarray(curr_path[idx - 1], dtype=float)
        curr_pt = np.asarray(curr_path[idx],     dtype=float)
        next_pt = np.asarray(curr_path[idx + 1], dtype=float)

        quartile_candidates = [
            prev_pt + 0.75 * (curr_pt - prev_pt),
            curr_pt + 0.25 * (next_pt - curr_pt),
        ]
        for q_pt in quartile_candidates:
            radius = _adaptive_neighborhood_radius(curr_path, idx)
            moved  = _project_to_valid_cell(
                q_pt, grid_map, max_radius=int(max(3, round(radius))), prefer_safety=0.25
            )
            cand = curr_path.copy()
            cand[idx] = moved
            cand = _dedup_consecutive_points(cand)
            if len(cand) < 2 or not _path_is_collision_free(cand, grid_map):
                continue
            cand_F, cand_G = compute_path_metrics(cand, grid_map)
            if _candidate_is_better(
                best_F, best_G, cand_F, cand_G,
                guidance=guidance, target_idx=3, target_margin=1e-4,
            ):
                best_path, best_F, best_G = cand, cand_F, cand_G
    return best_path, best_F, best_G


def _safety_path_operator(
    path: Sequence[Sequence[float]],
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
):
    """Shift high-risk segments away from obstacles using the distance gradient."""
    curr_path = list(map(tuple, path))
    curr_F, curr_G = compute_path_metrics(curr_path, grid_map)
    if len(curr_path) <= 2:
        return curr_path, curr_F, curr_G

    best_path, best_F, best_G = curr_path, curr_F, curr_G

    ranked_segments = []
    for seg_idx, (p0, p1) in enumerate(zip(curr_path[:-1], curr_path[1:])):
        risk, cells = _segment_risk_score(p0, p1, grid_map)
        ranked_segments.append((risk, seg_idx, cells))
    ranked_segments.sort(key=lambda item: item[0], reverse=True)

    for _, seg_idx, cells in ranked_segments[: min(4, len(ranked_segments))]:
        if len(cells) == 0:
            continue
        dm         = _get_distance_map()
        clearances = np.asarray(dm[cells[:, 1], cells[:, 0]], dtype=float)
        worst_cell = cells[int(np.argmin(clearances))]
        grad       = _distance_gradient_at(worst_cell)
        if np.linalg.norm(grad) <= 1e-8:
            continue

        p0          = np.asarray(curr_path[seg_idx],     dtype=float)
        p1          = np.asarray(curr_path[seg_idx + 1], dtype=float)
        base_radius = float(np.clip(0.45 * np.linalg.norm(p1 - p0) + 2.0, 3.0, 18.0))

        for mult in (0.5, 0.85, 1.2):
            cand  = curr_path.copy()
            shift = grad * base_radius * mult
            r     = int(max(3, round(base_radius)))
            if seg_idx == 0 and len(curr_path) > 2:
                cand[1] = _project_to_valid_cell(p1 + shift, grid_map, max_radius=r, prefer_safety=1.0)
            elif seg_idx == len(curr_path) - 2 and len(curr_path) > 2:
                cand[-2] = _project_to_valid_cell(p0 + shift, grid_map, max_radius=r, prefer_safety=1.0)
            else:
                cand[seg_idx]     = _project_to_valid_cell(p0 + shift, grid_map, max_radius=r, prefer_safety=1.0)
                cand[seg_idx + 1] = _project_to_valid_cell(p1 + shift, grid_map, max_radius=r, prefer_safety=1.0)

            cand = _dedup_consecutive_points(cand)
            if len(cand) < 2 or not _path_is_collision_free(cand, grid_map):
                continue

            cand_F, cand_G = compute_path_metrics(cand, grid_map)
            if _candidate_is_better(
                best_F, best_G, cand_F, cand_G,
                guidance=guidance, target_idx=2, target_margin=1e-4,
            ):
                best_path, best_F, best_G = cand, cand_F, cand_G
    return best_path, best_F, best_G


def _local_mutation_operator(
    path: Sequence[Sequence[float]],
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
    tries: int = 10,
):
    """Apply small random Gaussian perturbations to a random subset of interior waypoints."""
    curr_path = list(map(tuple, path))
    curr_F, curr_G = compute_path_metrics(curr_path, grid_map)
    if len(curr_path) <= 2:
        return curr_path, curr_F, curr_G

    best_path, best_F, best_G = curr_path, curr_F, curr_G
    internal_indices = list(range(1, len(curr_path) - 1))
    random.shuffle(internal_indices)

    for idx in internal_indices[: min(3, len(internal_indices))]:
        radius = _adaptive_neighborhood_radius(curr_path, idx)
        base   = np.asarray(curr_path[idx], dtype=float)
        for _ in range(max(1, int(tries))):
            delta = np.random.normal(0.0, 0.45 * radius, size=2)
            moved = _project_to_valid_cell(
                base + delta, grid_map, max_radius=int(max(3, round(radius))), prefer_safety=0.35
            )
            if not _edge_is_collision_free(curr_path[idx - 1], moved, grid_map):
                continue
            if not _edge_is_collision_free(moved, curr_path[idx + 1], grid_map):
                continue
            cand = curr_path.copy()
            cand[idx] = moved
            cand = _dedup_consecutive_points(cand)
            if len(cand) < 2 or not _path_is_collision_free(cand, grid_map):
                continue
            cand_F, cand_G = compute_path_metrics(cand, grid_map)
            if _candidate_is_better(best_F, best_G, cand_F, cand_G, guidance=guidance):
                best_path, best_F, best_G = cand, cand_F, cand_G
    return best_path, best_F, best_G


# ─────────────────────────────────────────────
# VNS local search (elite post-survival refinement)
# ─────────────────────────────────────────────

def _adaptive_vns_local_search_operator(
    path: Sequence[Sequence[float]],
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
    exhaustive: bool = False,
):
    """Variable-neighbourhood search on interior waypoints.

    In exhaustive mode all waypoints are considered and more perturbation
    tries are used; in fast mode a random subset is selected.
    """
    curr_path = list(map(tuple, path))
    curr_F, curr_G = compute_path_metrics(curr_path, grid_map)
    if len(curr_path) <= 2:
        return curr_path, curr_F, curr_G

    if exhaustive:
        idxs = list(range(1, len(curr_path) - 1))
    else:
        idxs = list(range(1, len(curr_path) - 1))
        random.shuffle(idxs)
        idxs = idxs[: min(2, len(idxs))]

    best_path, best_F, best_G = curr_path, curr_F, curr_G
    for idx in idxs:
        if idx <= 0 or idx >= len(best_path) - 1:
            continue
        radius = _adaptive_neighborhood_radius(best_path, idx)
        tries  = max(4, int(round(radius))) if exhaustive else max(3, int(round(0.6 * radius)))
        base   = np.asarray(best_path[idx], dtype=float)
        local_best_path, local_best_F, local_best_G = best_path, best_F, best_G

        for _ in range(tries):
            if idx <= 0 or idx >= len(local_best_path) - 1:
                break
            sigma = (0.26 if exhaustive else 0.20) * radius
            delta = np.random.normal(0.0, sigma, size=2)
            moved = _project_to_valid_cell(
                base + delta, grid_map, max_radius=int(max(3, round(radius))), prefer_safety=0.45
            )
            if not _edge_is_collision_free(local_best_path[idx - 1], moved, grid_map):
                continue
            if not _edge_is_collision_free(moved, local_best_path[idx + 1], grid_map):
                continue
            cand = local_best_path.copy()
            cand[idx] = moved
            cand = _dedup_consecutive_points(cand)
            if len(cand) < 2:
                continue
            # Only run full check when dedup actually merged points (rare).
            if len(cand) != len(local_best_path) and not _path_is_collision_free(cand, grid_map):
                continue
            cand_F, cand_G = compute_path_metrics(cand, grid_map)
            if _candidate_is_better(local_best_F, local_best_G, cand_F, cand_G, guidance=guidance):
                local_best_path, local_best_F, local_best_G = cand, cand_F, cand_G

        best_path, best_F, best_G = local_best_path, local_best_F, local_best_G

    return best_path, best_F, best_G
