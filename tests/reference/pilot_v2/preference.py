# -*- coding: utf-8 -*-
"""
dsop/preference.py
──────────────────
Preference-space transforms, PreferenceGuidance data-class, utility-model
scoring, and the core candidate-comparison function.

Design principle
----------------
All preference guidance flows exclusively through a `utility_model` stored
inside a `PreferenceGuidance` instance.  If no utility model is provided the
algorithm runs as pure NSGA-II with no extra preference information.

Public API
----------
PreferenceGuidance              dataclass encapsulating learned preference
_UtilityModelAdapter            wraps older utility models to match n_obj
_raw_objectives_to_preference_space(F)  -> np.ndarray  [0,1], lower=better
_utility_model_scores(F, G, guidance)   -> Optional[np.ndarray]
_candidate_is_better(...)               -> bool
_guidance_has_utility_model(guidance)   -> bool
_select_convergence_pool(F, G)          -> np.ndarray  feasible/near-feasible F
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from benchmark_defaults import FORMAL_PROPOSED_SESSION_KWARGS


def _formal_guidance_ratio() -> float:
    return float(FORMAL_PROPOSED_SESSION_KWARGS["guidance_ratio"])

from dsop.constants import (
    DEFAULT_N_OBJ, DEFAULT_REF_DIR_PARTITIONS, DEFAULT_WEIGHTS,
    PREFERENCE_MAXIMIZE_IDXS, _flip_higher_is_better_columns,
)
from dsop.map_cache import _constraint_violation, _is_feasible_from_G

# ─────────────────────────────────────────────
# Preference-space transform
# ─────────────────────────────────────────────

_PENALTY_THRESHOLD = 1e5


def _raw_objectives_to_preference_space(
    F: np.ndarray,
    is_infeasible: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Convert raw minimisation objectives → preference space [0,1], lower=better.

    Readable coordinates (before final flip):
      cost, length  : lower is better
      safety        : higher raw → lower in pref-space (flipped)
      smoothness    : higher raw → lower in pref-space (flipped)
    """
    arr = np.asarray(F, dtype=float)
    if arr.ndim == 1:
        arr = arr[None, :]

    if is_infeasible is None:
        is_infeasible = np.any(np.abs(arr) > _PENALTY_THRESHOLD, axis=1)

    if arr.shape[1] >= 4:
        readable = np.column_stack((arr[:, 0], arr[:, 1], -arr[:, 2], -arr[:, 3]))
    elif arr.shape[1] == 3:
        readable = np.column_stack((arr[:, 0], arr[:, 1], -arr[:, 2]))
    else:
        readable = arr.copy()

    feasible_mask = ~is_infeasible
    ref = readable[feasible_mask] if np.any(feasible_mask) else readable

    mins  = ref.min(axis=0)
    maxs  = ref.max(axis=0)
    denom = maxs - mins + 1e-8

    normed = (readable - mins) / denom
    normed = np.clip(normed, 0.0, 1.0)
    normed = _flip_higher_is_better_columns(normed)

    normed[is_infeasible] = 1.0
    return normed


# ─────────────────────────────────────────────
# Utility model adapter
# ─────────────────────────────────────────────

class _UtilityModelAdapter:
    """Adapt an older utility model to the current objective dimensionality."""

    def __init__(self, base_model: Any, n_obj: int):
        self.base_model = base_model
        self.n_obj = int(max(1, n_obj))

    def score_batch(self, F_norm: np.ndarray) -> np.ndarray:
        arr = np.asarray(F_norm, dtype=float)
        if arr.ndim == 1:
            arr = arr[None, :]
        if arr.shape[1] < self.n_obj:
            raise ValueError(
                f"Utility model expects at least {self.n_obj} objectives, got {arr.shape[1]}"
            )
        return np.asarray(self.base_model.score_batch(arr[:, :self.n_obj]), dtype=float)

    def get_linear_weights(self, *args, **kwargs):
        return self.base_model.get_linear_weights(*args, **kwargs)


# ─────────────────────────────────────────────
# PreferenceGuidance dataclass
# ─────────────────────────────────────────────

@dataclass
class PreferenceGuidance:
    """Encapsulates learned preference for injection into the evolutionary search.

    Fields
    ------
    preference_vector   normalised weight vector retained for metadata / compatibility;
                        current search guidance is driven by utility_model
    guidance_strength   blending coefficient [0, 0.50]
    n_obj               number of objectives
    utility_model       black-box model with `score_batch(F_norm) -> scores`
    utility_only        if True, linear weights are ignored
    """
    preference_vector: Optional[np.ndarray] = None
    guidance_strength: float = 0.10
    n_obj: int = DEFAULT_N_OBJ
    n_partitions: int = DEFAULT_REF_DIR_PARTITIONS
    utility_model: Optional[Any] = None
    utility_only: bool = False
    utility_as_objective: bool = False
    guidance_ratio: float = field(
        default_factory=_formal_guidance_ratio,
    )  # fraction of truncation slots filled by preference; rest by crowding

    @staticmethod
    def _ensure_min_weight(w: np.ndarray, floor: float = 0.05) -> np.ndarray:
        arr = np.asarray(w, dtype=float).reshape(-1)
        arr = np.clip(np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0), 0.0, None)

        if arr.size == 0:
            return np.ones(DEFAULT_N_OBJ, dtype=float) / DEFAULT_N_OBJ

        active_len = min(arr.size, DEFAULT_N_OBJ)
        active = arr[:active_len].copy()
        if float(active.sum()) <= 1e-12:
            active = np.ones(active_len, dtype=float)
        active = active / (active.sum() + 1e-12)
        active = np.maximum(active, floor)
        active = active / (active.sum() + 1e-12)

        if active_len == DEFAULT_N_OBJ:
            return active

        out = np.zeros(DEFAULT_N_OBJ, dtype=float)
        out[:active_len] = active
        return out

    @staticmethod
    def from_weights(
        weights: Sequence[float],
        iteration: int = 0,
        max_iterations: int = 3,
        pareto_F: Optional[np.ndarray] = None,
        guidance_strength: Optional[float] = None,
    ) -> "PreferenceGuidance":
        w = PreferenceGuidance._ensure_min_weight(np.asarray(weights, dtype=float))
        if guidance_strength is not None:
            strength = float(np.clip(guidance_strength, 0.0, 0.50))
        else:
            t = iteration / max(max_iterations - 1, 1)
            strength = 0.05 + 0.10 * t
        return PreferenceGuidance(preference_vector=w, guidance_strength=strength)

    @staticmethod
    def from_utility_model(
        model,
        guidance_strength: float = 0.15,
        linearize: bool = False,
        guidance_ratio: Optional[float] = None,
        utility_as_objective: bool = False,
    ) -> "PreferenceGuidance":
        if guidance_ratio is None:
            guidance_ratio = _formal_guidance_ratio()
        w = None
        model_n_obj = int(getattr(model, "n_obj", DEFAULT_N_OBJ))
        if linearize:
            w_raw = np.asarray(model.get_linear_weights(), dtype=float)
            if w_raw.size > 0:
                model_n_obj = int(getattr(model, "n_obj", w_raw.size))
            w = PreferenceGuidance._ensure_min_weight(np.asarray(w_raw, dtype=float))
        strength = float(np.clip(guidance_strength, 0.0, 0.50))
        adapted = model if model_n_obj == DEFAULT_N_OBJ else _UtilityModelAdapter(model, n_obj=model_n_obj)
        return PreferenceGuidance(
            preference_vector=w,
            guidance_strength=strength,
            utility_model=adapted,
            utility_only=not linearize,
            utility_as_objective=bool(utility_as_objective),
            guidance_ratio=float(np.clip(guidance_ratio, 0.0, 1.0)),
        )


# ─────────────────────────────────────────────
# Utility-model scoring
# ─────────────────────────────────────────────

def _guidance_has_utility_model(guidance: Optional[Any]) -> bool:
    """Return True iff guidance carries a non-None utility_model."""
    return bool(
        guidance is not None and getattr(guidance, "utility_model", None) is not None
    )


def _utility_model_scores(
    F_batch: Sequence[Sequence[float]],
    G_batch: Optional[Sequence[Sequence[float]]],
    guidance: Optional[PreferenceGuidance],
    normalize: bool = True,
) -> Optional[np.ndarray]:
    """Score solutions via the utility model in `guidance`.

    Returns None when no utility model is available.  Lower score = better.
    """
    if guidance is None or guidance.utility_model is None:
        return None

    F_arr = np.asarray(F_batch, dtype=float)
    if F_arr.ndim == 1:
        F_arr = F_arr[None, :]
    if len(F_arr) == 0:
        return np.zeros(0, dtype=float)

    infeasible = None
    if G_batch is not None:
        G_arr = np.asarray(G_batch, dtype=float)
        if G_arr.ndim == 1:
            G_arr = G_arr[None, :]
        infeasible = ~_is_feasible_from_G(G_arr)

    model = guidance.utility_model
    if hasattr(model, "score_raw_batch"):
        util = np.asarray(
            model.score_raw_batch(F_arr, is_infeasible=infeasible),
            dtype=float,
        ).reshape(-1)
    else:
        pref_space = _raw_objectives_to_preference_space(F_arr, is_infeasible=infeasible)
        util = np.asarray(model.score_batch(pref_space), dtype=float).reshape(-1)
    util = np.nan_to_num(util, nan=1e9, posinf=1e9, neginf=-1e9)
    if normalize and len(util) > 1:
        util = (util - util.min()) / (util.max() - util.min() + 1e-8)
    return util


# ─────────────────────────────────────────────
# Candidate comparison
# ─────────────────────────────────────────────

def _candidate_is_better(
    current_F: Sequence[float],
    current_G: Sequence[float],
    cand_F: Sequence[float],
    cand_G: Sequence[float],
    guidance: Optional[PreferenceGuidance] = None,
    target_idx: Optional[int] = None,
    target_margin: float = 0.0,
) -> bool:
    """Return True if the candidate is strictly preferred over the current solution.

    Decision order:
    1. Feasibility: feasible beats infeasible.
    2. Constraint violation: lower cv wins when both infeasible.
    3. Targeted-objective improvement (used by objective-specific operators).
    4. Pareto dominance.
    5. Utility model score (if available).
    """
    cur_cv  = float(np.sum(np.maximum(np.asarray(current_G, dtype=float), 0.0)))
    cand_cv = float(np.sum(np.maximum(np.asarray(cand_G,    dtype=float), 0.0)))
    cur_feas  = cur_cv  <= 1e-8
    cand_feas = cand_cv <= 1e-8

    if cand_feas and not cur_feas:
        return True
    if (not cand_feas) and cur_feas:
        return False
    if (not cand_feas) and (not cur_feas):
        return cand_cv < cur_cv - 1e-8

    cur_F  = np.asarray(current_F, dtype=float)
    cand_F = np.asarray(cand_F,    dtype=float)
    util_pref = _utility_model_scores(np.vstack([cur_F, cand_F]), None, guidance, normalize=False)

    if bool(getattr(guidance, "utility_as_objective", False)) and util_pref is not None:
        return bool(util_pref[1] < util_pref[0] - 1e-8)

    if target_idx is not None and cand_F[target_idx] < cur_F[target_idx] - float(target_margin):
        if util_pref is not None and util_pref[1] < util_pref[0] - 1e-8:
            return True
        if np.all(cand_F <= cur_F + 1e-6):   # weak non-degradation on other objectives
            return True

    cand_dom = np.all(cand_F <= cur_F + 1e-10) and np.any(cand_F < cur_F - 1e-10)
    if cand_dom:
        return True

    if util_pref is not None:
        if util_pref[1] < util_pref[0] - 1e-8:
            return True
        if util_pref[0] < util_pref[1] - 1e-8:
            return False
    return False


# ─────────────────────────────────────────────
# Convergence-pool helper
# ─────────────────────────────────────────────

def _select_convergence_pool(
    F: Sequence[Sequence[float]],
    G: Optional[Sequence[Sequence[float]]],
    fallback_k: int = 10,
) -> np.ndarray:
    """Return feasible F rows; if none feasible, return the k least-infeasible rows."""
    arr = np.asarray(F, dtype=float)
    if arr.ndim == 1:
        arr = arr[None, :]
    if len(arr) == 0:
        return arr
    if G is None:
        return arr

    G_arr = np.asarray(G, dtype=float)
    if G_arr.ndim == 1:
        G_arr = G_arr[None, :]
    feasible = _is_feasible_from_G(G_arr)
    if np.any(feasible):
        return arr[feasible]

    cv  = _constraint_violation(G_arr)
    idx = np.argsort(cv)[: min(int(fallback_k), len(arr))]
    return arr[idx]
