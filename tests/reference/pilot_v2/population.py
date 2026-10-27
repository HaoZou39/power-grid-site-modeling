# -*- coding: utf-8 -*-
"""
dsop/population.py
──────────────────
Population management, environment-selection, and the INSGA-II-style main loop.

Module layout
─────────────
  Scoring helpers          _normalize_readable_for_scoring, _scalarize_metrics
  Constraint coercion      _coerce_constraint_matrix
  Population evaluation    _evaluate_population_with_decoder
  Best-index selection     _select_weighted_best_index, _select_guided_best_index
  Crowding / front         _crowding_distance_like, _refine_legacy_feasible_front
  Preference scores        _population_preference_scores, _prefer_population_index
  Dedup / state            _deduplicate_population_rows, _compute_population_state
  Tournament selection     _tournament_better_index, _binary_tournament_select
  Environment selection    _select_population_environment
  Offspring generation     _encode_path_candidate_row, _generate_insga_offspring_row
  Local / global search    _apply_local_search_population, _apply_hybrid_global_search_population
  Core loop                _run_insga4_core
"""

import random
import time
from collections import Counter
import numpy as np
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
try:
    from pymoo.algorithms.moo.pinsga2 import VFDominator as _PymooVFDominator
except Exception:  # pragma: no cover - optional dependency path
    _PymooVFDominator = None  # type: ignore[assignment]

from benchmark_defaults import FORMAL_PROPOSED_SESSION_KWARGS

_GUIDANCE_RATIO_FALLBACK = float(FORMAL_PROPOSED_SESSION_KWARGS["guidance_ratio"])

from dsop.constants import (
    DEFAULT_N_OBJ, MIN_TOWERS, MAX_TOWERS,
    INSGA_STAGNATION_LIMIT, INSGA_GLOBAL_SEARCH_FRACTION, INSGA_LOCAL_SEARCH_FRACTION,
    LOCAL_SEARCH_INTERVAL, OFFSPRING_EMBEDDED_LOCAL_SEARCH,
    LOCAL_SEARCH_INCLUDE_REST_OF_ND_FRONT,
    PATH_CROSSOVER_PROB, PATH_MUTATION_PROB,
    _neutral_prefer_safety, resolve_init_strategy,
)
from dsop.map_cache import _constraint_violation, _is_feasible_from_G
from dsop.evaluation_archive import evaluation_source
from dsop.path_metrics import (
    compute_path_metrics, decode_solution_to_path,
    _encode_path_to_legacy_row, _row_signature,
    _normalize_weight_vector, _canonicalize_objective_batch, _normalize_readable_for_scoring,
)
from dsop.path_planners import _build_astar_rrt_population, _build_weak_population
from dsop.path_operators import (
    _path_crossover_operator, _path_mutation_operator,
    _shorten_path_operator, _safety_path_operator, _smoothness_path_operator,
    _adaptive_vns_local_search_operator, _path_is_collision_free, _sanitize_path_candidate,
)
from dsop.preference import (
    PreferenceGuidance, _utility_model_scores, _candidate_is_better,
)


def _profile_name(algorithm_profile: Optional[str]) -> str:
    return str(algorithm_profile or "default").lower()


def _is_pinsga2_vf_profile(algorithm_profile: Optional[str]) -> bool:
    return _profile_name(algorithm_profile) in {"pinsga2_official", "pinsga2_official_strict"}


def _is_pinsga2_official_profile(algorithm_profile: Optional[str]) -> bool:
    return _is_pinsga2_vf_profile(algorithm_profile)


def _is_pinsga2_official_strict_profile(algorithm_profile: Optional[str]) -> bool:
    return _profile_name(algorithm_profile) == "pinsga2_official_strict"


def _is_preference_env_only_profile(algorithm_profile: Optional[str]) -> bool:
    return _profile_name(algorithm_profile) == "preference_env_only"


def _is_benchmark_env_consult_only_profile(algorithm_profile: Optional[str]) -> bool:
    return _profile_name(algorithm_profile) == "preference_benchmark_env_only"


def _is_search_guidance_disabled_profile(algorithm_profile: Optional[str]) -> bool:
    return (
        _is_preference_env_only_profile(algorithm_profile)
        or _is_benchmark_env_consult_only_profile(algorithm_profile)
    )


def _is_utility_scalarized_profile(algorithm_profile: Optional[str]) -> bool:
    return _profile_name(algorithm_profile) == "utility_scalarized"


class _Pinsga2VFDominatorProxy:
    def __init__(self, vf_res: Any, v2: Optional[float]) -> None:
        self.vf_res = vf_res
        self.v2 = v2


def _get_profile_dominator(vf_dominance_state: Optional[dict]) -> Optional[Any]:
    if _PymooVFDominator is None or not vf_dominance_state:
        return None
    vf_res = vf_dominance_state.get("vf_res")
    if vf_res is None or getattr(vf_res, "vf", None) is None:
        return None
    proxy = _Pinsga2VFDominatorProxy(
        vf_res=vf_res,
        v2=vf_dominance_state.get("v2"),
    )
    return _PymooVFDominator(proxy)


def _profile_fronts(
    F_batch: np.ndarray,
    algorithm_profile: Optional[str] = None,
    vf_dominance_state: Optional[dict] = None,
) -> List[np.ndarray]:
    arr = np.asarray(F_batch, dtype=float)
    if arr.ndim == 1:
        arr = arr[None, :]
    if len(arr) == 0:
        return []

    if _is_pinsga2_official_profile(algorithm_profile):
        dominator = _get_profile_dominator(vf_dominance_state)
        if dominator is not None:
            try:
                return NonDominatedSorting(dominator=dominator).do(arr)
            except Exception:
                pass
    return NonDominatedSorting().do(arr)

# ─────────────────────────────────────────────
# Scoring helpers
# ─────────────────────────────────────────────

def _scalarize_metrics(F_batch: Sequence[Sequence[float]], weights: Sequence[float]) -> np.ndarray:
    """Weighted scalarisation: normalise readable objectives then dot with weight vector."""
    readable = _canonicalize_objective_batch(F_batch)
    normed   = _normalize_readable_for_scoring(readable)
    w        = _normalize_weight_vector(weights, n_obj=normed.shape[1])
    return normed.dot(w)


def _coerce_constraint_matrix(
    G: Optional[Sequence[Sequence[float]]],
    n_rows: int,
    n_cols: int,
) -> Optional[np.ndarray]:
    """Ensure G is a (n_rows, n_cols) float array, padding or zero-filling as needed."""
    if n_cols <= 0:
        return None
    if G is None:
        return np.zeros((int(n_rows), int(n_cols)), dtype=float)

    arr = np.asarray(G, dtype=float)
    if arr.ndim == 1:
        if int(n_rows) == 1 and arr.shape[0] == int(n_cols):
            arr = arr[None, :]
        else:
            arr = arr.reshape(int(n_rows), -1)
    if arr.shape[1] < int(n_cols):
        pad = np.zeros((arr.shape[0], int(n_cols) - arr.shape[1]), dtype=float)
        arr = np.hstack([arr, pad])
    return arr


# ─────────────────────────────────────────────
# Population evaluation
# ─────────────────────────────────────────────

def _evaluate_population_with_decoder(
    X_batch,
    decode_fn,
    grid_map,
) -> Tuple[np.ndarray, np.ndarray]:
    """Evaluate all rows in X_batch using decode_fn and compute_path_metrics."""
    X_arr = np.asarray(X_batch, dtype=float)
    if X_arr.ndim == 1:
        X_arr = X_arr[None, :]

    F_rows: List[np.ndarray] = []
    G_rows: List[np.ndarray] = []
    for row in X_arr:
        path  = decode_fn(row)
        f_vec, g_vec = compute_path_metrics(path, grid_map)
        F_rows.append(np.asarray(f_vec, dtype=float))
        G_rows.append(np.asarray(g_vec, dtype=float))

    if not F_rows:
        return np.zeros((0, DEFAULT_N_OBJ), dtype=float), np.zeros((0, 0), dtype=float)
    return np.vstack(F_rows), np.vstack(G_rows)


# ─────────────────────────────────────────────
# Best-index selection
# ─────────────────────────────────────────────

def _select_weighted_best_index(
    F_batch: Sequence[Sequence[float]],
    G_batch: Optional[Sequence[Sequence[float]]],
    weights: Sequence[float],
) -> Optional[int]:
    """Return the index of the feasible solution with lowest weighted-scalarisation score."""
    objs = np.asarray(F_batch, dtype=float)
    if objs.ndim == 1:
        objs = objs[None, :]
    if len(objs) == 0:
        return None

    G_arr = None if G_batch is None else np.asarray(G_batch, dtype=float)
    if G_arr is not None and G_arr.ndim == 1:
        G_arr = G_arr[None, :]

    if G_arr is not None:
        cv         = _constraint_violation(G_arr)
        is_feasible = cv <= 1e-8
    else:
        cv          = np.zeros(len(objs), dtype=float)
        is_feasible = np.ones(len(objs), dtype=bool)

    pool_idx = np.where(is_feasible)[0] if np.any(is_feasible) else np.argsort(cv)[: min(10, len(objs))]

    pool_F   = objs[pool_idx]
    readable = _canonicalize_objective_batch(pool_F)
    mins     = readable.min(axis=0)
    maxs     = readable.max(axis=0)
    normed   = (readable - mins) / (maxs - mins + 1e-8)
    from dsop.constants import _flip_higher_is_better_columns
    normed   = _flip_higher_is_better_columns(normed)

    w     = _normalize_weight_vector(weights, n_obj=normed.shape[1])
    scores = normed.dot(w)
    return int(pool_idx[int(np.argmin(scores))])


def _select_guided_best_index(
    F_batch: Sequence[Sequence[float]],
    G_batch: Optional[Sequence[Sequence[float]]],
    weights: Sequence[float],
    guidance: Optional[PreferenceGuidance] = None,
) -> Optional[int]:
    """Return best index using utility model when available, else fall back to weighted."""
    if guidance is None or guidance.utility_model is None:
        return _select_weighted_best_index(F_batch, G_batch, weights)

    objs = np.asarray(F_batch, dtype=float)
    if objs.ndim == 1:
        objs = objs[None, :]
    if len(objs) == 0:
        return None

    G_arr = None if G_batch is None else np.asarray(G_batch, dtype=float)
    if G_arr is not None and G_arr.ndim == 1:
        G_arr = G_arr[None, :]

    if G_arr is not None:
        cv          = _constraint_violation(G_arr)
        is_feasible = cv <= 1e-8
    else:
        cv          = np.zeros(len(objs), dtype=float)
        is_feasible = np.ones(len(objs), dtype=bool)

    pool_idx = np.where(is_feasible)[0] if np.any(is_feasible) else np.argsort(cv)[: min(10, len(objs))]
    pool_G   = None if G_arr is None else G_arr[pool_idx]
    util     = _utility_model_scores(objs[pool_idx], pool_G, guidance, normalize=False)
    if util is None or len(util) == 0:
        return _select_weighted_best_index(F_batch, G_batch, weights)
    return int(pool_idx[int(np.argmin(util))])


# ─────────────────────────────────────────────
# Crowding distance & Pareto front refinement
# ─────────────────────────────────────────────

def _crowding_distance_like(F: np.ndarray) -> np.ndarray:
    """Compute a crowding-distance-like diversity measure on the objective matrix."""
    arr = np.asarray(F, dtype=float)
    n   = len(arr)
    if n == 0:
        return np.zeros(0, dtype=float)
    if n <= 2:
        return np.full(n, np.inf, dtype=float)

    readable = _canonicalize_objective_batch(arr)
    normed   = _normalize_readable_for_scoring(readable)
    dist     = np.zeros(n, dtype=float)
    m        = normed.shape[1]

    for j in range(m):
        order        = np.argsort(normed[:, j])
        dist[order[0]]  = np.inf
        dist[order[-1]] = np.inf
        span = normed[order[-1], j] - normed[order[0], j] + 1e-12
        for t in range(1, n - 1):
            if not np.isinf(dist[order[t]]):
                dist[order[t]] += (normed[order[t + 1], j] - normed[order[t - 1], j]) / span
    return dist


def _refine_legacy_feasible_front(
    pareto_X: np.ndarray,
    pareto_F: np.ndarray,
    start: tuple,
    end: tuple,
    grid_map,
    max_refine: int = 12,
) -> Tuple[np.ndarray, np.ndarray]:
    """Apply a quick round of path-refinement operators to boundary & sparse ND solutions."""
    if pareto_X is None or pareto_F is None or len(pareto_X) == 0:
        return np.asarray(pareto_X), np.asarray(pareto_F)

    F_arr = np.asarray(pareto_F, dtype=float)
    X_arr = np.asarray(pareto_X, dtype=float)

    boundary = set()
    for j in range(F_arr.shape[1]):
        boundary.add(int(np.argmin(F_arr[:, j])))

    crowd       = _crowding_distance_like(F_arr)
    sparse_rank = np.argsort(-np.nan_to_num(crowd, nan=-1.0, posinf=1e9))
    elite = list(dict.fromkeys(
        list(boundary) + sparse_rank[: max(2, min(len(F_arr), max_refine // 2))].tolist()
    ))
    elite = elite[: min(max_refine, len(elite))]

    add_X = []
    add_F = []
    seen  = set()
    for idx in elite:
        path    = decode_solution_to_path(X_arr[idx], start, end)
        current = list(map(tuple, path))
        curr_F, curr_G = compute_path_metrics(current, grid_map)

        for op in (_shorten_path_operator, _safety_path_operator, _smoothness_path_operator):
            current, curr_F, curr_G = op(current, grid_map)

        from dsop.path_metrics import _encode_path_to_legacy_row, _row_signature
        row = _encode_path_to_legacy_row(
            current, grid_map,
            num_towers=len(current) - 2,
            prefer_safety=_neutral_prefer_safety(),
        )
        encoded_path = decode_solution_to_path(row, start, end)
        encoded_F, encoded_G = compute_path_metrics(encoded_path, grid_map)
        encoded_F_arr = np.asarray(encoded_F, dtype=float)
        encoded_G_arr = np.asarray(encoded_G, dtype=float)
        if (
            not np.all(np.isfinite(encoded_F_arr))
            or not np.all(np.isfinite(encoded_G_arr))
            or np.any(encoded_G_arr > 1e-8)
        ):
            continue
        sig = _row_signature(row)
        if sig in seen:
            continue
        seen.add(sig)
        add_X.append(row)
        add_F.append(encoded_F_arr)

    if not add_X:
        return X_arr, F_arr

    merged_X = np.vstack([X_arr, np.asarray(add_X, dtype=float)])
    merged_F = np.vstack([F_arr, np.asarray(add_F, dtype=float)])
    nd = NonDominatedSorting().do(merged_F, only_non_dominated_front=True)
    return merged_X[nd], merged_F[nd]


# ─────────────────────────────────────────────
# Preference scores & deduplication
# ─────────────────────────────────────────────

def _population_preference_scores(
    F_batch: Sequence[Sequence[float]],
    G_batch: Optional[Sequence[Sequence[float]]],
    guidance: Optional[PreferenceGuidance] = None,
) -> np.ndarray:
    """Return utility scores when available, otherwise zeros for neutral sorting."""
    F_arr = np.asarray(F_batch, dtype=float)
    if F_arr.ndim == 1:
        F_arr = F_arr[None, :]

    util = _utility_model_scores(F_arr, G_batch, guidance, normalize=True)
    if util is not None and len(F_arr) > 0:
        return util
    return np.zeros(len(F_arr), dtype=float)


def _unit_interval(arr: Sequence[float], invert: bool = False) -> np.ndarray:
    vals = np.asarray(arr, dtype=float).reshape(-1)
    if len(vals) == 0:
        return vals
    vals = np.nan_to_num(vals, nan=0.0, posinf=np.max(vals[np.isfinite(vals)]) if np.any(np.isfinite(vals)) else 1.0, neginf=0.0)
    lo = float(np.min(vals))
    hi = float(np.max(vals))
    if hi - lo <= 1e-12:
        out = np.ones_like(vals)
    else:
        out = (vals - lo) / (hi - lo)
    if invert:
        out = 1.0 - out
    return out


def _guided_secondary_scores(
    crowding: Sequence[float],
    pref_scores: Sequence[float],
    guidance_strength: float,
) -> np.ndarray:
    alpha = float(np.clip(guidance_strength, 0.0, 0.50))
    crowd_term = _unit_interval(
        np.nan_to_num(np.asarray(crowding, dtype=float), nan=-1.0, posinf=1e9),
        invert=False,
    )
    pref_term = _unit_interval(pref_scores, invert=True)
    return (1.0 - alpha) * crowd_term + alpha * pref_term


def _prefer_population_index(
    idx_a: int,
    idx_b: int,
    feasible: np.ndarray,
    cv: np.ndarray,
    pref_scores: np.ndarray,
    algorithm_profile: Optional[str] = None,
) -> int:
    """Return the preferred index for deduplication: feasibility > cv > preference score."""
    if feasible[idx_a] and not feasible[idx_b]:
        return idx_a
    if feasible[idx_b] and not feasible[idx_a]:
        return idx_b
    if not feasible[idx_a] and not feasible[idx_b]:
        if cv[idx_a] < cv[idx_b] - 1e-8:
            return idx_a
        if cv[idx_b] < cv[idx_a] - 1e-8:
            return idx_b
    if _is_pinsga2_official_profile(algorithm_profile) or _is_search_guidance_disabled_profile(algorithm_profile):
        return min(int(idx_a), int(idx_b))
    if pref_scores[idx_a] < pref_scores[idx_b] - 1e-10:
        return idx_a
    if pref_scores[idx_b] < pref_scores[idx_a] - 1e-10:
        return idx_b
    return idx_a


def _deduplicate_population_rows(
    X_batch: Sequence[Sequence[float]],
    F_batch: Sequence[Sequence[float]],
    G_batch: Optional[Sequence[Sequence[float]]],
    guidance: Optional[PreferenceGuidance] = None,
    algorithm_profile: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """Remove duplicate chromosome rows, keeping the better duplicate."""
    X_arr = np.asarray(X_batch, dtype=float)
    if X_arr.ndim == 1:
        X_arr = X_arr[None, :]
    F_arr = np.asarray(F_batch, dtype=float)
    if F_arr.ndim == 1:
        F_arr = F_arr[None, :]
    G_arr = None if G_batch is None else np.asarray(G_batch, dtype=float)
    if G_arr is not None and G_arr.ndim == 1:
        G_arr = G_arr[None, :]

    if len(X_arr) <= 1:
        return X_arr, F_arr, G_arr

    cv         = np.zeros(len(X_arr), dtype=float) if G_arr is None else _constraint_violation(G_arr)
    feasible   = np.ones(len(X_arr), dtype=bool)   if G_arr is None else (cv <= 1e-8)
    if _is_pinsga2_official_profile(algorithm_profile) or _is_search_guidance_disabled_profile(algorithm_profile):
        pref_scores = np.zeros(len(F_arr), dtype=float)
    else:
        pref_scores = _population_preference_scores(F_arr, G_arr, guidance=guidance)

    keep: dict = {}
    for idx, row in enumerate(X_arr):
        sig = _row_signature(row)
        if sig not in keep:
            keep[sig] = idx
        else:
            best      = keep[sig]
            keep[sig] = _prefer_population_index(
                idx,
                best,
                feasible,
                cv,
                pref_scores,
                algorithm_profile=algorithm_profile,
            )

    chosen = np.array(sorted(set(keep.values())), dtype=int)
    return X_arr[chosen], F_arr[chosen], (None if G_arr is None else G_arr[chosen])


# ─────────────────────────────────────────────
# Population state (front / crowding / preference)
# ─────────────────────────────────────────────

def _compute_population_state(
    F_batch: Sequence[Sequence[float]],
    G_batch: Optional[Sequence[Sequence[float]]],
    guidance: Optional[PreferenceGuidance] = None,
    algorithm_profile: Optional[str] = None,
    vf_dominance_state: Optional[dict] = None,
) -> dict:
    """Return a state dict with NDS fronts, crowding, constraint violation, pref scores."""
    F_arr = np.asarray(F_batch, dtype=float)
    if F_arr.ndim == 1:
        F_arr = F_arr[None, :]
    n = len(F_arr)

    G_arr = None if G_batch is None else np.asarray(G_batch, dtype=float)
    if G_arr is not None and G_arr.ndim == 1:
        G_arr = G_arr[None, :]

    cv          = np.zeros(n, dtype=float) if G_arr is None else _constraint_violation(G_arr)
    feasible    = np.ones(n, dtype=bool)   if G_arr is None else (cv <= 1e-8)
    official_profile = _is_pinsga2_official_profile(algorithm_profile)
    search_guidance_disabled = _is_search_guidance_disabled_profile(algorithm_profile)
    pref_scores = (
        np.zeros(n, dtype=float)
        if (official_profile or search_guidance_disabled)
        else _population_preference_scores(F_arr, G_arr, guidance=guidance)
    )
    has_guidance = (
        (not official_profile)
        and (not search_guidance_disabled)
        and guidance is not None
        and getattr(guidance, "utility_model", None) is not None
    )

    rank           = np.full(n, np.inf, dtype=float)
    crowding       = np.zeros(n, dtype=float)
    feasible_fronts: List[np.ndarray] = []
    nd_idx         = np.zeros(0, dtype=int)
    boundary_idx   = np.zeros(0, dtype=int)
    sparse_idx     = np.zeros(0, dtype=int)

    if np.any(feasible):
        feas_idx     = np.where(feasible)[0]
        if _is_utility_scalarized_profile(algorithm_profile) and has_guidance:
            utility_order = np.argsort(pref_scores[feas_idx], kind="mergesort")
            fronts_local = [np.asarray([idx], dtype=int) for idx in utility_order]
        else:
            fronts_local = _profile_fronts(
                F_arr[feas_idx],
                algorithm_profile=algorithm_profile,
                vf_dominance_state=vf_dominance_state,
            )
        for front_rank, front_local in enumerate(fronts_local):
            front_idx = feas_idx[np.asarray(front_local, dtype=int)]
            feasible_fronts.append(front_idx)
            rank[front_idx]     = float(front_rank)
            crowding[front_idx] = _crowding_distance_like(F_arr[front_idx])

        if feasible_fronts:
            nd_idx   = feasible_fronts[0]
            boundary = set()
            for j in range(F_arr.shape[1]):
                boundary.add(int(nd_idx[np.argmin(F_arr[nd_idx, j])]))
            boundary_idx = np.asarray(sorted(boundary), dtype=int)

            boundary_set = set(boundary_idx.tolist())
            sparse_pool  = np.asarray([idx for idx in nd_idx if idx not in boundary_set], dtype=int)
            if len(sparse_pool) > 0:
                crowd  = np.nan_to_num(crowding[sparse_pool], nan=-1.0, posinf=1e9)
                top_k  = min(len(sparse_pool), max(2, int(np.ceil(0.25 * len(nd_idx)))))
                sparse_idx = sparse_pool[np.argsort(-crowd)[:top_k]]

    return {
        "F": F_arr, "G": G_arr, "cv": cv,
        "feasible": feasible, "pref_scores": pref_scores,
        "has_guidance": has_guidance,
        "algorithm_profile": str(algorithm_profile or "default"),
        "vf_dominance_state": vf_dominance_state,
        "rank": rank, "crowding": crowding,
        "feasible_fronts": feasible_fronts,
        "nd_idx": nd_idx, "boundary_idx": boundary_idx, "sparse_idx": sparse_idx,
    }


# ─────────────────────────────────────────────
# Tournament selection
# ─────────────────────────────────────────────

def _tournament_better_index(idx_a: int, idx_b: int, state: dict) -> int:
    """Binary tournament: feasibility > front rank > utility score (learn-to-rank)."""
    feasible    = state["feasible"]
    cv          = state["cv"]
    rank        = state["rank"]
    pref_scores = state["pref_scores"]
    has_guidance = state.get("has_guidance", False)
    official_profile = _is_pinsga2_official_profile(state.get("algorithm_profile"))
    env_only_profile = _is_search_guidance_disabled_profile(state.get("algorithm_profile"))

    if feasible[idx_a] and not feasible[idx_b]:
        return idx_a
    if feasible[idx_b] and not feasible[idx_a]:
        return idx_b

    if not feasible[idx_a] and not feasible[idx_b]:
        if cv[idx_a] < cv[idx_b] - 1e-8:
            return idx_a
        if cv[idx_b] < cv[idx_a] - 1e-8:
            return idx_b
        if official_profile or env_only_profile:
            return idx_a if random.random() < 0.5 else idx_b
        return idx_a if pref_scores[idx_a] <= pref_scores[idx_b] else idx_b

    if rank[idx_a] < rank[idx_b]:
        return idx_a
    if rank[idx_b] < rank[idx_a]:
        return idx_b

    if official_profile or env_only_profile:
        crowding = state["crowding"]
        crowd_a = float(np.nan_to_num(crowding[idx_a], nan=-1.0, posinf=1e9))
        crowd_b = float(np.nan_to_num(crowding[idx_b], nan=-1.0, posinf=1e9))
        if crowd_a > crowd_b + 1e-12:
            return idx_a
        if crowd_b > crowd_a + 1e-12:
            return idx_b
    elif has_guidance:
        if pref_scores[idx_a] < pref_scores[idx_b] - 1e-10:
            return idx_a
        if pref_scores[idx_b] < pref_scores[idx_a] - 1e-10:
            return idx_b
    else:
        crowding = state["crowding"]
        crowd_a = float(np.nan_to_num(crowding[idx_a], nan=-1.0, posinf=1e9))
        crowd_b = float(np.nan_to_num(crowding[idx_b], nan=-1.0, posinf=1e9))
        if crowd_a > crowd_b + 1e-12:
            return idx_a
        if crowd_b > crowd_a + 1e-12:
            return idx_b

    return idx_a if random.random() < 0.5 else idx_b


def _binary_tournament_select(state: dict) -> int:
    n = len(state["F"])
    if n <= 1:
        return 0
    idx_a, idx_b = random.sample(range(n), 2)
    return _tournament_better_index(idx_a, idx_b, state)


# ─────────────────────────────────────────────
# Preference archive (biased mating / elite slots)
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# Environment selection
# ─────────────────────────────────────────────

def _select_population_environment(
    X_batch: Sequence[Sequence[float]],
    F_batch: Sequence[Sequence[float]],
    G_batch: Optional[Sequence[Sequence[float]]],
    pop_size: int,
    guidance: Optional[PreferenceGuidance] = None,
    algorithm_profile: Optional[str] = None,
    vf_dominance_state: Optional[dict] = None,
    environment_selector: Optional[Any] = None,
    generation: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], dict]:
    """NSGA-II-style environmental selection: dedup → fronts → crowding → preference."""
    X_raw = np.asarray(X_batch, dtype=float)
    if X_raw.ndim == 1:
        X_raw = X_raw[None, :]
    F_raw = np.asarray(F_batch, dtype=float)
    if F_raw.ndim == 1:
        F_raw = F_raw[None, :]
    G_raw = None if G_batch is None else np.asarray(G_batch, dtype=float)
    if G_raw is not None and G_raw.ndim == 1:
        G_raw = G_raw[None, :]

    X_arr, F_arr, G_arr = _deduplicate_population_rows(
        X_raw,
        F_raw,
        G_raw,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
    )
    if len(X_arr) < int(pop_size):
        X_arr, F_arr, G_arr = X_raw, F_raw, G_raw
    state = _compute_population_state(
        F_arr,
        G_arr,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
        vf_dominance_state=vf_dominance_state,
    )

    selected: List[int] = []
    has_guidance = state.get("has_guidance", False)
    official_profile = _is_pinsga2_official_profile(algorithm_profile)
    env_only_profile = _is_search_guidance_disabled_profile(algorithm_profile)
    use_standard_nd_query_pool = (
        _is_utility_scalarized_profile(algorithm_profile) and bool(has_guidance)
    )
    query_pool_meta: Optional[dict] = None

    # The scalarized ablation intentionally replaces Pareto ranking for
    # survival and tournament selection.  Query construction is not part of
    # that intervention: derive its splitting front from standard constrained
    # nondominated sorting so the DM menu follows the same mechanism as PILOT.
    if use_standard_nd_query_pool:
        query_state = _compute_population_state(F_arr, G_arr)
        query_selected = 0
        for query_front in query_state["feasible_fronts"]:
            query_front = np.asarray(query_front, dtype=int)
            if query_selected + len(query_front) <= int(pop_size):
                query_selected += len(query_front)
                continue
            query_pool_meta = {
                "query_X": np.asarray(X_arr[query_front], dtype=float).copy(),
                "query_F": np.asarray(F_arr[query_front], dtype=float).copy(),
                "query_G": (
                    None
                    if G_arr is None
                    else np.asarray(G_arr[query_front], dtype=float).copy()
                ),
                "query_pool_source": "critical_front",
                "query_pool_generation": None if generation is None else int(generation),
            }
            break

    for front_idx in state["feasible_fronts"]:
        front_idx = np.asarray(front_idx, dtype=int)
        if len(selected) + len(front_idx) <= int(pop_size):
            selected.extend(front_idx.tolist())
            continue
        slots = int(pop_size) - len(selected)
        if not use_standard_nd_query_pool:
            query_pool_meta = {
                "query_X": np.asarray(X_arr[front_idx], dtype=float).copy(),
                "query_F": np.asarray(F_arr[front_idx], dtype=float).copy(),
                "query_G": None if G_arr is None else np.asarray(G_arr[front_idx], dtype=float).copy(),
                "query_pool_source": "critical_front",
                "query_pool_generation": None if generation is None else int(generation),
            }

        if environment_selector is not None:
            selector_result = environment_selector(
                generation=None if generation is None else int(generation),
                pop_X=X_arr,
                pop_F=F_arr,
                pop_G=G_arr,
                population_state=state,
                front_indices=front_idx.copy(),
                slots=int(slots),
                guidance=guidance,
                algorithm_profile=algorithm_profile,
            )
            if selector_result:
                chosen_front = (
                    selector_result.get("selected_front_indices", [])
                    if isinstance(selector_result, dict)
                    else selector_result
                )
                valid_front = set(front_idx.tolist())
                picked_custom: List[int] = []
                for raw_idx in np.asarray(chosen_front, dtype=int).reshape(-1):
                    idx_int = int(raw_idx)
                    if idx_int in valid_front and idx_int not in picked_custom:
                        picked_custom.append(idx_int)
                    if len(picked_custom) >= slots:
                        break
                if picked_custom:
                    selected.extend(picked_custom)
                    if len(picked_custom) < slots:
                        picked_set = set(picked_custom)
                        crowd = np.nan_to_num(state["crowding"][front_idx], nan=-1.0, posinf=1e9)
                        crowd_order = np.argsort(-crowd, kind="mergesort")
                        for ci in crowd_order:
                            idx_int = int(front_idx[ci])
                            if idx_int in picked_set:
                                continue
                            selected.append(idx_int)
                            picked_set.add(idx_int)
                            if len(picked_set) >= slots:
                                break
                    break

        if has_guidance and not official_profile and not env_only_profile:
            utility_ratio = float(
                np.clip(
                    getattr(guidance, "guidance_ratio", _GUIDANCE_RATIO_FALLBACK)
                    if guidance is not None
                    else _GUIDANCE_RATIO_FALLBACK,
                    0.0,
                    1.0,
                )
            )
            n_util = int(round(slots * utility_ratio))
            n_util = min(slots, max(0, n_util))
            n_diverse = slots - n_util

            picked_util: List[int] = []
            if n_util > 0:
                pref = state["pref_scores"][front_idx]
                pref_order = np.argsort(pref, kind="mergesort")
                picked_util = front_idx[pref_order[:n_util]].tolist()

            picked_set = set(picked_util)
            picked_diverse: List[int] = []
            if n_diverse > 0:
                crowd = np.nan_to_num(state["crowding"][front_idx], nan=-1.0, posinf=1e9)
                crowd_order = np.argsort(-crowd, kind="mergesort")
                for ci in crowd_order:
                    if int(front_idx[ci]) not in picked_set:
                        picked_diverse.append(int(front_idx[ci]))
                        picked_set.add(int(front_idx[ci]))
                        if len(picked_diverse) >= n_diverse:
                            break

            selected.extend(picked_util)
            selected.extend(picked_diverse)
        else:
            crowd = np.nan_to_num(state["crowding"][front_idx], nan=-1.0, posinf=1e9)
            order = np.argsort(-crowd, kind="mergesort")
            selected.extend(front_idx[order[:slots]].tolist())
        break

    if len(selected) < int(pop_size):
        infeas_idx = np.where(~state["feasible"])[0]
        if len(infeas_idx) > 0:
            if official_profile or env_only_profile:
                order = np.argsort(state["cv"][infeas_idx], kind="mergesort")
            else:
                order = np.lexsort((state["pref_scores"][infeas_idx], state["cv"][infeas_idx]))
            fill  = infeas_idx[order[: int(pop_size) - len(selected)]]
            selected.extend(fill.tolist())

    if len(selected) == 0:
        selected = list(range(min(int(pop_size), len(X_arr))))

    # Some interactive baselines consult on a splitting front.  When the
    # feasible fronts exactly fill the survivor budget, no such callback is
    # made and a scheduled interaction could otherwise disappear silently.
    # This optional hook is observational with respect to the survivor set;
    # the policy may only update its own learned preference model.
    ensure_consultation = (
        None
        if environment_selector is None
        else getattr(environment_selector, "ensure_scheduled_consultation", None)
    )
    if callable(ensure_consultation):
        ensure_consultation(
            generation=None if generation is None else int(generation),
            pop_X=X_arr,
            pop_F=F_arr,
            pop_G=G_arr,
            population_state=state,
        )

    selected_idx = np.asarray(selected[: int(pop_size)], dtype=int)
    X_sel = X_arr[selected_idx]
    F_sel = F_arr[selected_idx]
    G_sel = None if G_arr is None else G_arr[selected_idx]
    selected_state = _compute_population_state(
        F_sel,
        G_sel,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
        vf_dominance_state=vf_dominance_state,
    )
    # Preserve the exact already-evaluated pool used for this environmental
    # selection.  Interactive sessions can re-apply truncation after receiving
    # feedback without re-evaluating candidates or touching the search RNG.
    selected_state.update(
        {
            "selection_context_X": np.asarray(X_arr, dtype=float).copy(),
            "selection_context_F": np.asarray(F_arr, dtype=float).copy(),
            "selection_context_G": (
                None if G_arr is None else np.asarray(G_arr, dtype=float).copy()
            ),
        }
    )
    if query_pool_meta is None:
        selected_state.update(
            {
                "query_X": None,
                "query_F": None,
                "query_G": None,
                "query_pool_source": None,
                "query_pool_generation": None,
            }
        )
    else:
        selected_state.update(query_pool_meta)
    return X_sel, F_sel, G_sel, selected_state


# ─────────────────────────────────────────────
# Offspring generation
# ─────────────────────────────────────────────

def _encode_path_candidate_row(
    path: Sequence[Sequence[float]],
    start: tuple,
    end: tuple,
    grid_map,
    tower_hint: Optional[int] = None,
) -> np.ndarray:
    """Sanitise a path candidate and encode it as a legacy-absolute chromosome row."""
    prefer_safety = _neutral_prefer_safety()
    clean = _sanitize_path_candidate(path, grid_map, prefer_safety=prefer_safety)
    if clean is None:
        clean = [tuple(map(int, start)), tuple(map(int, end))]
    row = _encode_path_to_legacy_row(
        clean, grid_map,
        num_towers=int(np.clip(len(clean) - 2 if tower_hint is None else tower_hint, MIN_TOWERS, MAX_TOWERS)),
        prefer_safety=prefer_safety,
    )
    decoded = decode_solution_to_path(row, start, end)
    if not _path_is_collision_free(decoded, grid_map):
        row = _encode_path_to_legacy_row(
            clean, grid_map,
            num_towers=int(np.clip(len(clean) - 2, MIN_TOWERS, MAX_TOWERS)),
            prefer_safety=prefer_safety,
        )
    return row


def _generate_insga_offspring_row(
    row_a: np.ndarray,
    row_b: np.ndarray,
    F_a: Sequence[float],
    G_a: Sequence[float],
    F_b: Sequence[float],
    G_b: Sequence[float],
    start: tuple,
    end: tuple,
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
    timing_acc: Optional[dict] = None,
    algorithm_profile: Optional[str] = None,
) -> np.ndarray:
    """Produce one offspring row via crossover + optional mutation."""
    def _acc(key: str, t0: float) -> None:
        if timing_acc is not None:
            timing_acc[key] = timing_acc.get(key, 0.0) + (time.perf_counter() - t0)

    t0     = time.perf_counter()
    path_a = decode_solution_to_path(row_a, start, end)
    path_b = decode_solution_to_path(row_b, start, end)
    guide = None if (_is_pinsga2_official_profile(algorithm_profile) or _is_search_guidance_disabled_profile(algorithm_profile)) else guidance
    if _candidate_is_better(F_a, G_a, F_b, G_b, guidance=guide):
        best_path = list(map(tuple, path_b))
        best_F, best_G = list(F_b), list(G_b)
        tower_hint = int(np.clip(round(float(row_b[0])), MIN_TOWERS, MAX_TOWERS))
    else:
        best_path = list(map(tuple, path_a))
        best_F, best_G = list(F_a), list(G_a)
        tower_hint = int(np.clip(round(float(row_a[0])), MIN_TOWERS, MAX_TOWERS))
    _acc("offs_decode_parents_and_pick", t0)

    t0 = time.perf_counter()
    if random.random() < PATH_CROSSOVER_PROB:
        cand_path, cand_F, cand_G = _path_crossover_operator(path_a, path_b, grid_map, guidance=guide)
        if _candidate_is_better(best_F, best_G, cand_F, cand_G, guidance=guide):
            best_path, best_F, best_G = cand_path, cand_F, cand_G
    _acc("offs_path_crossover_operator", t0)

    t0 = time.perf_counter()
    if random.random() < PATH_MUTATION_PROB:
        cand_path, cand_F, cand_G = _path_mutation_operator(best_path, grid_map, guidance=guide)
        if _candidate_is_better(best_F, best_G, cand_F, cand_G, guidance=guide):
            best_path, best_F, best_G = cand_path, cand_F, cand_G
    _acc("offs_path_mutation_operator", t0)

    t0 = time.perf_counter()
    if OFFSPRING_EMBEDDED_LOCAL_SEARCH and not _is_pinsga2_official_strict_profile(algorithm_profile):
        for op in (_shorten_path_operator, _safety_path_operator, _smoothness_path_operator):
            cand_path, cand_F, cand_G = op(best_path, grid_map, guidance=guide)
            if _candidate_is_better(best_F, best_G, cand_F, cand_G, guidance=guide):
                best_path, best_F, best_G = cand_path, cand_F, cand_G
    _acc("offs_shorten_safety_smooth_operators", t0)

    t0  = time.perf_counter()
    row = _encode_path_candidate_row(
        best_path, start=start, end=end, grid_map=grid_map, tower_hint=tower_hint,
    )
    _acc("offs_encode_path_candidate_row", t0)
    return row


# ─────────────────────────────────────────────
# Population-level local and global search
# ─────────────────────────────────────────────

def _apply_local_search_population(
    X_batch: np.ndarray,
    F_batch: np.ndarray,
    G_batch: Optional[np.ndarray],
    start: tuple,
    end: tuple,
    grid_map,
    pop_size: int,
    guidance: Optional[PreferenceGuidance] = None,
    algorithm_profile: Optional[str] = None,
    vf_dominance_state: Optional[dict] = None,
    environment_selector: Optional[Any] = None,
    generation: Optional[int] = None,
    return_state: bool = False,
):
    """Post-survival VNS local search on ND boundary and sparse-crowding elites.

    Priority order: boundary solutions (per-objective extremes on the ND front),
    then sparse solutions (high crowding-distance), matching MOEA literature.
    """
    if _is_pinsga2_official_strict_profile(algorithm_profile):
        if return_state:
            return X_batch, F_batch, G_batch, None
        return X_batch, F_batch, G_batch

    local_guidance = None if _is_search_guidance_disabled_profile(algorithm_profile) else guidance

    state  = _compute_population_state(
        F_batch,
        G_batch,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
        vf_dominance_state=vf_dominance_state,
    )
    nd_idx = state["nd_idx"]
    if len(nd_idx) == 0:
        if return_state:
            return X_batch, F_batch, G_batch, None
        return X_batch, F_batch, G_batch

    boundary_set = set(state["boundary_idx"].tolist())
    sparse_set   = set(state["sparse_idx"].tolist())
    priority     = list(state["boundary_idx"].tolist())
    priority.extend(idx for idx in state["sparse_idx"].tolist() if idx not in boundary_set)
    if LOCAL_SEARCH_INCLUDE_REST_OF_ND_FRONT:
        priority.extend(
            idx for idx in nd_idx.tolist()
            if idx not in boundary_set and idx not in sparse_set
        )

    max_refine = min(len(priority), max(4, int(np.ceil(pop_size * INSGA_LOCAL_SEARCH_FRACTION))))
    add_rows: List[np.ndarray] = []
    add_F:    List[np.ndarray] = []
    add_G:    List[np.ndarray] = []

    for idx in priority[:max_refine]:
        current_path = decode_solution_to_path(X_batch[idx], start, end)
        curr_F       = np.asarray(F_batch[idx], dtype=float)
        curr_G       = np.zeros(0, dtype=float) if G_batch is None else np.asarray(G_batch[idx], dtype=float)
        cand_path, cand_F, cand_G = _adaptive_vns_local_search_operator(
            current_path, grid_map, guidance=local_guidance,
            exhaustive=(idx in boundary_set or idx in sparse_set),
        )
        if not _candidate_is_better(curr_F, curr_G, cand_F, cand_G, guidance=local_guidance):
            continue
        row = _encode_path_candidate_row(
            cand_path, start=start, end=end, grid_map=grid_map,
            tower_hint=int(np.clip(round(float(X_batch[idx, 0])), MIN_TOWERS, MAX_TOWERS)),
        )
        encoded_path = decode_solution_to_path(row, start, end)
        encoded_F, encoded_G = compute_path_metrics(encoded_path, grid_map)
        if not _candidate_is_better(
            curr_F,
            curr_G,
            encoded_F,
            encoded_G,
            guidance=local_guidance,
        ):
            continue
        add_rows.append(row)
        add_F.append(np.asarray(encoded_F, dtype=float))
        add_G.append(np.asarray(encoded_G, dtype=float))

    if not add_rows:
        if return_state:
            return X_batch, F_batch, G_batch, None
        return X_batch, F_batch, G_batch

    merged_X = np.vstack([X_batch, np.asarray(add_rows, dtype=float)])
    merged_F = np.vstack([F_batch, np.asarray(add_F, dtype=float)])
    merged_G = None if G_batch is None else np.vstack([G_batch, np.asarray(add_G, dtype=float)])
    sel_X, sel_F, sel_G, selected_state = _select_population_environment(
        merged_X,
        merged_F,
        merged_G,
        pop_size=pop_size,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
        vf_dominance_state=vf_dominance_state,
        environment_selector=environment_selector,
        generation=generation,
    )
    if return_state:
        return sel_X, sel_F, sel_G, selected_state
    return sel_X, sel_F, sel_G


def _update_stagnation_counts(
    X_batch: np.ndarray,
    prev_counts: Optional[dict] = None,
) -> dict:
    """Track how many consecutive generations each chromosome signature has survived."""
    prev = {} if prev_counts is None else dict(prev_counts)
    out  = {}
    for row in np.asarray(X_batch, dtype=float):
        sig     = _row_signature(row)
        out[sig] = prev.get(sig, 0) + 1
    return out


def _apply_hybrid_global_search_population(
    X_batch: np.ndarray,
    F_batch: np.ndarray,
    G_batch: Optional[np.ndarray],
    start: tuple,
    end: tuple,
    grid_map,
    pop_size: int,
    stagnation_counts: Optional[dict],
    guidance: Optional[PreferenceGuidance] = None,
    algorithm_profile: Optional[str] = None,
    vf_dominance_state: Optional[dict] = None,
    environment_selector: Optional[Any] = None,
    generation: Optional[int] = None,
    return_state: bool = False,
):
    """Replace stagnant dominated solutions with fresh A*/RRT seeds and ND crossover offspring."""
    if _is_pinsga2_official_strict_profile(algorithm_profile):
        if return_state:
            return X_batch, F_batch, G_batch, None
        return X_batch, F_batch, G_batch

    state        = _compute_population_state(
        F_batch,
        G_batch,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
        vf_dominance_state=vf_dominance_state,
    )
    nd_set       = set(state["nd_idx"].tolist())
    dominated_idx = [idx for idx in range(len(X_batch)) if idx not in nd_set]
    if len(dominated_idx) == 0:
        if return_state:
            return X_batch, F_batch, G_batch, None
        return X_batch, F_batch, G_batch

    target_new = max(2, int(np.ceil(pop_size * INSGA_GLOBAL_SEARCH_FRACTION)))
    stagnant   = []
    if stagnation_counts is not None:
        for idx in dominated_idx:
            sig = _row_signature(X_batch[idx])
            if stagnation_counts.get(sig, 0) >= INSGA_STAGNATION_LIMIT:
                stagnant.append(idx)

    add_rows: List[np.ndarray] = []
    n_random    = max(1, target_new // 2)
    random_rows = _build_astar_rrt_population(
        start, end, grid_map, pop_size=n_random, include_astar=False,
    )
    add_rows.extend([np.asarray(row, dtype=float).copy() for row in random_rows])

    parent_pool = state["nd_idx"]
    if len(parent_pool) < 2:
        feasible_idx = np.where(state["feasible"])[0]
        parent_pool  = feasible_idx if len(feasible_idx) > 1 else np.arange(len(X_batch))

    for _ in range(max(0, target_new - n_random)):
        if len(parent_pool) >= 2:
            a, b = np.random.choice(parent_pool, size=2, replace=False)
        else:
            a = b = int(parent_pool[0]) if len(parent_pool) > 0 else 0
        row = _generate_insga_offspring_row(
            X_batch[a], X_batch[b],
            F_batch[a], np.zeros(0, dtype=float) if G_batch is None else G_batch[a],
            F_batch[b], np.zeros(0, dtype=float) if G_batch is None else G_batch[b],
            start=start, end=end, grid_map=grid_map, guidance=guidance,
            algorithm_profile=algorithm_profile,
        )
        add_rows.append(row)

    if not add_rows:
        if return_state:
            return X_batch, F_batch, G_batch, None
        return X_batch, F_batch, G_batch

    add_X  = np.asarray(add_rows, dtype=float)
    decode = lambda row: decode_solution_to_path(row, start, end)
    add_F, add_G = _evaluate_population_with_decoder(add_X, decode, grid_map)

    if stagnant:
        remove_k  = min(len(stagnant), len(add_X))
        keep_mask = np.ones(len(X_batch), dtype=bool)
        for idx in stagnant[:remove_k]:
            keep_mask[int(idx)] = False
        base_X = X_batch[keep_mask]
        base_F = F_batch[keep_mask]
        base_G = None if G_batch is None else G_batch[keep_mask]
    else:
        base_X, base_F, base_G = X_batch, F_batch, G_batch

    merged_X = np.vstack([base_X, add_X])
    merged_F = np.vstack([base_F, add_F])
    merged_G = None if base_G is None else np.vstack([base_G, add_G])
    sel_X, sel_F, sel_G, selected_state = _select_population_environment(
        merged_X,
        merged_F,
        merged_G,
        pop_size=pop_size,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
        vf_dominance_state=vf_dominance_state,
        environment_selector=environment_selector,
        generation=generation,
    )
    if return_state:
        return sel_X, sel_F, sel_G, selected_state
    return sel_X, sel_F, sel_G


# ─────────────────────────────────────────────
# Convergence snapshot helper
# ─────────────────────────────────────────────

def _record_convergence_snapshot(
    callback: Optional[Any],
    F_batch: np.ndarray,
    G_batch: Optional[np.ndarray],
) -> None:
    if callback is None:
        return
    callback.F_list.append(np.asarray(F_batch, dtype=float).copy())
    callback.G_list.append(None if G_batch is None else np.asarray(G_batch, dtype=float).copy())


# ─────────────────────────────────────────────
# Population initialisation
# ─────────────────────────────────────────────

def _prepare_initial_population(
    initial_population: Optional[np.ndarray],
    pop_size: int,
    start: tuple,
    end: tuple,
    grid_map,
    guidance: Optional[PreferenceGuidance] = None,
    algorithm_profile: Optional[str] = None,
    vf_dominance_state: Optional[dict] = None,
) -> np.ndarray:
    """Build or wrap the initial population, padding with A*/RRT if needed."""
    def _seed(n: int) -> np.ndarray:
        strategy = resolve_init_strategy()
        if strategy == "astar_rrt":
            return _build_astar_rrt_population(start, end, grid_map, pop_size=n)
        return _build_weak_population(start, end, grid_map, pop_size=n, mode=strategy)

    if initial_population is None:
        return _seed(pop_size)

    arr = np.asarray(initial_population, dtype=float)
    if arr.ndim == 1:
        arr = arr[None, :]

    if len(arr) < pop_size:
        add = _seed(max(pop_size - len(arr), 2))
        arr = np.vstack([arr, add])

    decode = lambda row: decode_solution_to_path(row, start, end)
    F_arr, G_arr = _evaluate_population_with_decoder(arr, decode, grid_map)
    sel_X, _, _, _ = _select_population_environment(
        arr,
        F_arr,
        G_arr,
        pop_size=pop_size,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
        vf_dominance_state=vf_dominance_state,
    )
    return sel_X


# ─────────────────────────────────────────────
# INSGA-II-style core loop
# ─────────────────────────────────────────────

def _run_insga4_core(
    *,
    start: tuple,
    end: tuple,
    grid_map,
    pop_size: int,
    n_gen: int,
    initial_population: Optional[np.ndarray],
    guidance: Optional[PreferenceGuidance] = None,
    callback: Optional[Any] = None,
    perf_session: Optional[Any] = None,
    algorithm_profile: Optional[str] = None,
    vf_dominance_state: Optional[dict] = None,
    generation_observer: Optional[Any] = None,
    environment_selector: Optional[Any] = None,
) -> dict:
    """Main NSGA-II-style evolutionary loop.

    Parameters
    ----------
    perf_session : _PerfSession | None
        Optional performance logger; if supplied, per-generation timing is written.
    callback : ConvergenceCallback | None
        If supplied, F/G snapshots are appended each generation.
    """
    perf = perf_session

    t0    = time.perf_counter()
    with evaluation_source("initialization"):
        pop_X = _prepare_initial_population(
            initial_population=initial_population,
            pop_size=pop_size, start=start, end=end, grid_map=grid_map,
            guidance=guidance,
            algorithm_profile=algorithm_profile,
            vf_dominance_state=vf_dominance_state,
        )
    if perf:
        perf.log("_insga4_prepare_initial_population", time.perf_counter() - t0)

    decode = lambda row: decode_solution_to_path(row, start, end)
    t0     = time.perf_counter()
    with evaluation_source("initial_population"):
        pop_F, pop_G = _evaluate_population_with_decoder(pop_X, decode, grid_map)
    if perf:
        perf.log("_insga4_initial_evaluate_population", time.perf_counter() - t0)

    t0 = time.perf_counter()
    pop_X, pop_F, pop_G, last_environment_state = _select_population_environment(
        pop_X,
        pop_F,
        pop_G,
        pop_size=pop_size,
        guidance=guidance,
        algorithm_profile=algorithm_profile,
        vf_dominance_state=vf_dominance_state,
        environment_selector=environment_selector,
        generation=0,
    )
    if perf:
        perf.log("_insga4_initial_select_population_environment", time.perf_counter() - t0)

    stagnation_counts = _update_stagnation_counts(pop_X, prev_counts=None)
    _record_convergence_snapshot(callback, pop_F, pop_G)

    n_gen_i       = max(int(n_gen), 0)
    sum_offspring = sum_eval_off = sum_merge_select = 0.0
    sum_local     = sum_global   = sum_tail          = 0.0
    offspring_detail: Optional[dict] = {} if (perf is not None and perf._fp is not None) else None

    for _gen_idx in range(n_gen_i):
        t_off = time.perf_counter()

        prev_pop_X = np.asarray(pop_X, dtype=float).copy()
        prev_pop_F = np.asarray(pop_F, dtype=float).copy()
        prev_pop_G = None if pop_G is None else np.asarray(pop_G, dtype=float).copy()

        state = _compute_population_state(
            pop_F,
            pop_G,
            guidance=guidance,
            algorithm_profile=algorithm_profile,
            vf_dominance_state=vf_dominance_state,
        )

        offspring_rows: List[np.ndarray] = []
        for _ in range(pop_size):
            idx_a = _binary_tournament_select(state)
            idx_b = _binary_tournament_select(state)
            if pop_size > 1:
                tries = 0
                while idx_b == idx_a and tries < 4:
                    idx_b = _binary_tournament_select(state)
                    tries += 1

            with evaluation_source("offspring_operators"):
                row = _generate_insga_offspring_row(
                    pop_X[idx_a], pop_X[idx_b],
                    pop_F[idx_a], np.zeros(0, dtype=float) if pop_G is None else pop_G[idx_a],
                    pop_F[idx_b], np.zeros(0, dtype=float) if pop_G is None else pop_G[idx_b],
                    start=start, end=end, grid_map=grid_map,
                    guidance=guidance,
                    timing_acc=offspring_detail,
                    algorithm_profile=algorithm_profile,
                )
            offspring_rows.append(row)

        off_X = np.asarray(offspring_rows, dtype=float)
        sum_offspring += time.perf_counter() - t_off

        t_ev   = time.perf_counter()
        with evaluation_source("offspring_population"):
            off_F, off_G = _evaluate_population_with_decoder(off_X, decode, grid_map)
        sum_eval_off += time.perf_counter() - t_ev

        t_ms      = time.perf_counter()
        merged_X  = np.vstack([pop_X, off_X])
        merged_F  = np.vstack([pop_F, off_F])
        merged_G  = None if pop_G is None else np.vstack([pop_G, off_G])
        pop_X, pop_F, pop_G, last_environment_state = _select_population_environment(
            merged_X,
            merged_F,
            merged_G,
            pop_size=pop_size,
            guidance=guidance,
            algorithm_profile=algorithm_profile,
            vf_dominance_state=vf_dominance_state,
            environment_selector=environment_selector,
            generation=int(_gen_idx) + 1,
        )
        sum_merge_select += time.perf_counter() - t_ms

        if generation_observer is not None:
            current_state = _compute_population_state(
                pop_F,
                pop_G,
                guidance=guidance,
                algorithm_profile=algorithm_profile,
                vf_dominance_state=vf_dominance_state,
            )
            observer_result = generation_observer(
                generation=int(_gen_idx) + 1,
                pop_X=pop_X,
                pop_F=pop_F,
                pop_G=pop_G,
                population_state=current_state,
                previous_population={
                    "pop_X": prev_pop_X,
                    "pop_F": prev_pop_F,
                    "pop_G": prev_pop_G,
                },
            )
            if observer_result:
                pop_X = np.asarray(observer_result.get("pop_X", pop_X), dtype=float)
                pop_F = np.asarray(observer_result.get("pop_F", pop_F), dtype=float)
                obs_G = observer_result.get("pop_G", pop_G)
                pop_G = None if obs_G is None else np.asarray(obs_G, dtype=float)

        t_loc = time.perf_counter()
        if (not _is_pinsga2_official_strict_profile(algorithm_profile)) and _gen_idx % LOCAL_SEARCH_INTERVAL == 0:
            with evaluation_source("explicit_local_search"):
                pop_X, pop_F, pop_G, local_state = _apply_local_search_population(
                    pop_X, pop_F, pop_G,
                    start=start, end=end, grid_map=grid_map,
                    pop_size=pop_size,
                    guidance=guidance,
                    algorithm_profile=algorithm_profile,
                    vf_dominance_state=vf_dominance_state,
                    environment_selector=environment_selector,
                    generation=int(_gen_idx) + 1,
                    return_state=True,
                )
            if local_state is not None:
                last_environment_state = local_state
        sum_local += time.perf_counter() - t_loc

        t_glb = time.perf_counter()
        with evaluation_source("hybrid_global_search"):
            pop_X, pop_F, pop_G, global_state = _apply_hybrid_global_search_population(
                pop_X, pop_F, pop_G,
                start=start, end=end, grid_map=grid_map,
                pop_size=pop_size,
                stagnation_counts=stagnation_counts,
                guidance=guidance,
                algorithm_profile=algorithm_profile,
                vf_dominance_state=vf_dominance_state,
                environment_selector=environment_selector,
                generation=int(_gen_idx) + 1,
                return_state=True,
            )
        if global_state is not None:
            last_environment_state = global_state
        sum_global += time.perf_counter() - t_glb

        t_tl = time.perf_counter()
        stagnation_counts = _update_stagnation_counts(pop_X, prev_counts=stagnation_counts)
        _record_convergence_snapshot(callback, pop_F, pop_G)
        sum_tail += time.perf_counter() - t_tl

    if perf:
        perf.note(f"_insga4_generations={n_gen_i} pop_size={pop_size}")
        if n_gen_i > 0:
            perf.log("_insga4_sum_gen_offspring_build",        sum_offspring)
            perf.log("_insga4_sum_gen_evaluate_offspring",     sum_eval_off)
            perf.log("_insga4_sum_gen_merge_and_select",       sum_merge_select)
            perf.log("_insga4_sum_gen_local_search_population", sum_local)
            perf.log("_insga4_sum_gen_hybrid_global_search",   sum_global)
            perf.log("_insga4_sum_gen_stagnation_and_snapshot", sum_tail)
            perf.log(
                "_insga4_sum_gen_loop_total",
                sum_offspring + sum_eval_off + sum_merge_select + sum_local + sum_global + sum_tail,
            )
        if offspring_detail:
            perf.note("offspring_build_breakdown (cumulative, seconds; largest first):")
            for _k, _v in sorted(offspring_detail.items(), key=lambda kv: -kv[1]):
                perf.log(f"offs_break::{_k}", _v)
            _bd_sum = float(sum(offspring_detail.values()))
            perf.log("_insga4_offspring_breakdown_sum_parts",        _bd_sum)
            perf.log("_insga4_offspring_breakdown_vs_sum_offspring_delta", sum_offspring - _bd_sum)

    return {
        "pop_X": pop_X,
        "pop_F": pop_F,
        "pop_G": pop_G,
        "history": None,
        "callback": callback,
        "last_environment_state": last_environment_state,
    }


# ─────────────────────────────────────────────
# Local debug harness (run: python -m dsop.population)
# ─────────────────────────────────────────────

_ENV_SELECT_DEBUG_EVENTS: List[Dict[str, Any]] = []
_ENV_SELECT_ORIGINAL: Optional[Callable[..., Any]] = None


def _env_select_debug_reset() -> None:
    _ENV_SELECT_DEBUG_EVENTS.clear()


def _env_select_debug_install() -> None:
    """Monkey-patch `_select_population_environment` to record call statistics.

    This is only intended for the module's `__main__` harness; it restores the
    original implementation when `_env_select_debug_uninstall()` runs.
    """
    global _ENV_SELECT_ORIGINAL  # noqa: PLW0603
    if _ENV_SELECT_ORIGINAL is not None:
        return

    _ENV_SELECT_ORIGINAL = _select_population_environment  # type: ignore[assignment]

    def _wrapped(
        X_batch: Sequence[Sequence[float]],
        F_batch: Sequence[Sequence[float]],
        G_batch: Optional[Sequence[Sequence[float]]],
        pop_size: int,
        guidance: Optional[PreferenceGuidance] = None,
        algorithm_profile: Optional[str] = None,
        vf_dominance_state: Optional[dict] = None,
        environment_selector: Optional[Any] = None,
        generation: Optional[int] = None,
    ):
        assert _ENV_SELECT_ORIGINAL is not None
        X_raw = np.asarray(X_batch, dtype=float)
        if X_raw.ndim == 1:
            X_raw = X_raw[None, :]
        F_raw = np.asarray(F_batch, dtype=float)
        if F_raw.ndim == 1:
            F_raw = F_raw[None, :]
        G_raw = None if G_batch is None else np.asarray(G_batch, dtype=float)
        if G_raw is not None and G_raw.ndim == 1:
            G_raw = G_raw[None, :]

        n_in = int(len(X_raw))
        X_dedup, _, _ = _deduplicate_population_rows(
            X_raw,
            F_raw,
            G_raw,
            guidance=guidance,
            algorithm_profile=algorithm_profile,
        )
        n_dedup = int(len(X_dedup))
        if n_dedup < int(pop_size):
            n_dedup_effective = n_in  # matches `_select_population_environment` rollback branch
        else:
            n_dedup_effective = n_dedup

        sig_in = Counter(_row_signature(r) for r in X_raw)

        t0 = time.perf_counter()
        X_sel, F_sel, G_sel, state = _ENV_SELECT_ORIGINAL(
            X_batch,
            F_batch,
            G_batch,
            pop_size=pop_size,
            guidance=guidance,
            algorithm_profile=algorithm_profile,
            vf_dominance_state=vf_dominance_state,
            environment_selector=environment_selector,
            generation=generation,
        )
        dt = time.perf_counter() - t0

        X_sel = np.asarray(X_sel, dtype=float)
        if X_sel.ndim == 1:
            X_sel = X_sel[None, :]
        n_out = int(len(X_sel))
        sig_out = Counter(_row_signature(r) for r in X_sel)

        _ENV_SELECT_DEBUG_EVENTS.append(
            {
                "generation": None if generation is None else int(generation),
                "n_in": n_in,
                "n_dedup_unique_rows": n_dedup,
                "n_dedup_effective_for_state": n_dedup_effective,
                "n_out": n_out,
                "wall_s": float(dt),
                "multiset_changed": sig_in != sig_out,
            }
        )
        return X_sel, F_sel, G_sel, state

    globals()["_select_population_environment"] = _wrapped  # type: ignore[assignment]


def _env_select_debug_uninstall() -> None:
    global _ENV_SELECT_ORIGINAL  # noqa: PLW0603
    if _ENV_SELECT_ORIGINAL is None:
        return
    globals()["_select_population_environment"] = _ENV_SELECT_ORIGINAL  # type: ignore[assignment]
    _ENV_SELECT_ORIGINAL = None


if __name__ == "__main__":
    # Minimal, evidence-oriented checks for initial-population environmental selection.
    # Figures / printed labels are English per project convention.

    from dsop.constants import REPRO_FIXED_END, REPRO_FIXED_START, REPRO_RANDOM_SEED
    from dsop.map_cache import _get_cached_map

    def _print_case(title: str) -> None:
        print("\n" + "=" * 88)
        print(title)
        print("=" * 88)

    def _print_events() -> None:
        if not _ENV_SELECT_DEBUG_EVENTS:
            print("environment_selection_calls: 0")
            return
        print(f"environment_selection_calls: {len(_ENV_SELECT_DEBUG_EVENTS)}")
        for i, ev in enumerate(_ENV_SELECT_DEBUG_EVENTS, start=1):
            print(
                f"  call {i}: generation={ev['generation']} "
                f"n_in={ev['n_in']} n_dedup_unique_rows={ev['n_dedup_unique_rows']} "
                f"n_dedup_effective_for_state={ev['n_dedup_effective_for_state']} "
                f"n_out={ev['n_out']} multiset_changed={ev['multiset_changed']} "
                f"wall_s={ev['wall_s']:.6f}"
            )

    pop_size = 8
    start = tuple(REPRO_FIXED_START)  # type: ignore[arg-type]
    end = tuple(REPRO_FIXED_END)  # type: ignore[arg-type]
    grid_map = _get_cached_map()

    print("Initial population / environmental selection probe")
    print(f"pop_size={pop_size} seed={REPRO_RANDOM_SEED}")
    print("Call-chain facts (read from this module):")
    print(
        "  - `_prepare_initial_population`: calls `_select_population_environment` "
        "only when `initial_population` is not None (external / partial seed path)."
    )
    print(
        "  - `_run_insga4_core`: always calls `_select_population_environment` once "
        "right after initial evaluation, with `generation=0`."
    )

    _env_select_debug_install()
    try:
        random.seed(REPRO_RANDOM_SEED)
        np.random.seed(REPRO_RANDOM_SEED)

        # Case A: internal builder (`initial_population=None`) -> no env-select inside prepare.
        _print_case("Case A: internal init (`initial_population=None`) -> `_prepare_initial_population`")
        _env_select_debug_reset()
        raw_A = _build_astar_rrt_population(start, end, grid_map, pop_size=pop_size)
        print(f"astar_rrt_rows={len(raw_A)}")
        prep_A = _prepare_initial_population(
            None, pop_size, start, end, grid_map,
            guidance=None, algorithm_profile=None, vf_dominance_state=None,
        )
        print(f"prepare_out_rows={len(prep_A)} (expected == pop_size)")
        _print_events()

        # Case B: external seed with exactly pop_size rows -> env-select runs once in prepare.
        _print_case("Case B: external seed len==pop_size -> env-select in `_prepare_initial_population`")
        _env_select_debug_reset()
        base_B = _build_astar_rrt_population(start, end, grid_map, pop_size=pop_size)
        sig_base = Counter(_row_signature(r) for r in base_B)
        prep_B = _prepare_initial_population(
            base_B, pop_size, start, end, grid_map,
            guidance=None, algorithm_profile=None, vf_dominance_state=None,
        )
        sig_prep = Counter(_row_signature(r) for r in prep_B)
        print(f"external_rows={len(base_B)} prepare_out_rows={len(prep_B)}")
        print(f"multiset_changed_prepare_vs_external={sig_base != sig_prep}")
        _print_events()

        # Case C: external seed with heavy duplicate rows (still len==pop_size).
        _print_case("Case C: external seed with duplicate rows (len still == pop_size)")
        _env_select_debug_reset()
        dup = np.asarray(base_B, dtype=float).copy()
        dup[:] = dup[0]
        sig_dup_in = Counter(_row_signature(r) for r in dup)
        prep_C = _prepare_initial_population(
            dup, pop_size, start, end, grid_map,
            guidance=None, algorithm_profile=None, vf_dominance_state=None,
        )
        sig_dup_out = Counter(_row_signature(r) for r in prep_C)
        print(
            f"external_dup_unique_signatures={len(sig_dup_in)} "
            f"prepare_out_unique_signatures={len(sig_dup_out)} "
            f"multiset_changed={sig_dup_in != sig_dup_out}"
        )
        _print_events()

        # Case D: `_run_insga4_core` with n_gen=0 still performs generation-0 environmental selection.
        _print_case("Case D1: `_run_insga4_core` n_gen=0, internal init (prepare has no env-select)")
        _env_select_debug_reset()
        out_D1 = _run_insga4_core(
            start=start,
            end=end,
            grid_map=grid_map,
            pop_size=pop_size,
            n_gen=0,
            initial_population=None,
            guidance=None,
            callback=None,
            perf_session=None,
            algorithm_profile=None,
            vf_dominance_state=None,
            generation_observer=None,
            environment_selector=None,
        )
        print(f"final_rows={len(out_D1['pop_X'])}")
        _print_events()

        _print_case("Case D2: `_run_insga4_core` n_gen=0, external init (prepare + gen0 env-select)")
        _env_select_debug_reset()
        base_D = _build_astar_rrt_population(start, end, grid_map, pop_size=pop_size)
        out_D2 = _run_insga4_core(
            start=start,
            end=end,
            grid_map=grid_map,
            pop_size=pop_size,
            n_gen=0,
            initial_population=base_D,
            guidance=None,
            callback=None,
            perf_session=None,
            algorithm_profile=None,
            vf_dominance_state=None,
            generation_observer=None,
            environment_selector=None,
        )
        print(f"final_rows={len(out_D2['pop_X'])}")
        _print_events()

        print("\nHow to interpret 'environmental selection actually ran':")
        print("  - Any recorded call above means `_select_population_environment` executed.")
        print("  - `multiset_changed=True` means the returned population multiset of row-signatures differs.")
        print("  - `n_dedup_unique_rows < n_in` shows duplicate collapsing before selection state is built.")
        print("  - If `n_dedup_unique_rows < pop_size`, this implementation rolls back to the raw batch for sorting.")

    finally:
        _env_select_debug_uninstall()
