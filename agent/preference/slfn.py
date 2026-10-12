"""Structure-augmented SLFN utility learner used by PILOT.

Supports both the original pairwise-expanded objective and menu-aware losses
for short-list interactions.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import minimize as sp_minimize
from scipy.special import expit as sigmoid


def _build_cross_features(features: np.ndarray) -> np.ndarray:
    if features.ndim == 1:
        features = features[None, :]
    pairs = [
        features[:, i] * features[:, j]
        for i in range(features.shape[1])
        for j in range(i + 1, features.shape[1])
    ]
    if not pairs:
        return np.zeros((features.shape[0], 0), dtype=float)
    return np.column_stack(pairs)


def _build_quadratic_features(features: np.ndarray) -> np.ndarray:
    """Full second-order features: diagonal (f_i^2) + cross (f_i * f_j)."""
    if features.ndim == 1:
        features = features[None, :]
    diag = features ** 2
    cross = _build_cross_features(features)
    return np.column_stack([diag, cross]) if cross.size > 0 else diag


def _logsumexp(values: np.ndarray) -> float:
    vmax = float(np.max(values))
    return vmax + float(np.log(np.sum(np.exp(values - vmax))))


class FCPEUtilityLearner:
    """Anchored-residual utility learner with menu-aware losses.

    Scores represent disutility: lower is better.
    """

    def __init__(
        self,
        n_obj: int = 3,
        lambda_cross: float = 0.1,
        lambda_delta: float = 0.5,
        delta_cap: float = 2.0,
        min_rounds_for_residual: int = 1,
        interaction_loss: str = "pairwise_expand",
        n_hidden: Optional[int] = None,
        rng_seed: int = 42,
        use_full_quad: bool = True,
        early_cross_multiplier: float = 8.0,
        cross_unlock_round: int = 1,
        lambda_nl: Optional[float] = None,
        lambda_uninformed_cross: float = 0.0,
    ) -> None:
        self.n_obj = n_obj
        self.n_cross = n_obj * (n_obj - 1) // 2
        self.use_full_quad = use_full_quad
        self.n_quad = (n_obj + self.n_cross) if use_full_quad else self.n_cross
        self.lambda_cross = float(lambda_cross)
        self.lambda_delta = float(lambda_delta)
        self.delta_cap = float(delta_cap)
        self.min_rounds_for_residual = int(min_rounds_for_residual)
        self.interaction_loss = interaction_loss
        self.early_cross_multiplier = float(max(1.0, early_cross_multiplier))
        self.cross_unlock_round = int(max(0, cross_unlock_round))

        self._uniform_w = np.ones(n_obj, dtype=float) / n_obj
        self._base_w = self._uniform_w.copy()
        self._delta_w = np.zeros(n_obj, dtype=float)
        self._a = np.zeros(self.n_quad, dtype=float)

        self.n_hidden = n_hidden if n_hidden is not None else 2 * n_obj
        rng = np.random.RandomState(rng_seed)
        self._W_nl = rng.standard_normal((n_obj, self.n_hidden)) / np.sqrt(n_obj)
        self._b_nl = rng.uniform(-1.0, 1.0, size=self.n_hidden)
        self._a_nl = np.zeros(self.n_hidden, dtype=float)
        self.lambda_nl = float(self.lambda_cross if lambda_nl is None else lambda_nl)
        if not np.isfinite(self.lambda_nl) or self.lambda_nl < 0.0:
            raise ValueError("lambda_nl must be a finite non-negative value")
        self.lambda_uninformed_cross = float(lambda_uninformed_cross)
        if not np.isfinite(self.lambda_uninformed_cross) or self.lambda_uninformed_cross < 0.0:
            raise ValueError("lambda_uninformed_cross must be a finite non-negative value")

        self._ref_min: Optional[np.ndarray] = None
        self._ref_max: Optional[np.ndarray] = None

        self._structure_prior_target = np.zeros(self.n_cross, dtype=float)
        self._structure_confidence: float = 0.0
        self._importance_pairs: List[Tuple[int, int]] = []
        self._order_confidence: float = 0.0
        self.lambda_order: float = 2.0

    # ------------------------------------------------------------------
    # Reference: register once from the first consultation's population
    # ------------------------------------------------------------------
    def set_reference(self, F: np.ndarray) -> None:
        if self._ref_min is not None:
            return
        arr = np.atleast_2d(np.asarray(F, dtype=float))
        self._ref_min = arr.min(axis=0)
        self._ref_max = arr.max(axis=0)

    def set_base_weight_prior(
        self,
        weights: Optional[Sequence[float]],
        *,
        strength: float = 0.0,
    ) -> None:
        if weights is None:
            self._base_w = self._uniform_w.copy()
            return
        arr = np.clip(np.asarray(weights, dtype=float), 0.0, None)
        if arr.size != self.n_obj:
            raise ValueError("base weight prior size does not match n_obj")
        total = float(np.sum(arr))
        if total <= 0:
            self._base_w = self._uniform_w.copy()
            return
        alpha = float(np.clip(strength, 0.0, 1.0))
        prior = arr / total
        self._base_w = (1.0 - alpha) * self._uniform_w + alpha * prior

    def set_structure_prior(
        self,
        pair_priors: Optional[Sequence[float]] = None,
        confidence: float = 0.0,
        pair_prior_scale: float = 0.15,
    ) -> None:
        """Inject cross-term prior targets from LLM structural analysis."""
        prior = np.zeros(self.n_cross, dtype=float)
        if pair_priors is not None:
            arr = np.asarray(pair_priors, dtype=float).ravel()
            if arr.size == self.n_cross:
                prior = np.clip(arr, 0.0, None)
        self._structure_confidence = float(np.clip(confidence, 0.0, 1.0))
        self._structure_prior_target = pair_prior_scale * prior

    def set_importance_order(
        self,
        order_pairs: Sequence[Tuple[int, int]],
        confidence: float = 0.5,
    ) -> None:
        """Soft ordering: each (hi, lo) means w[hi] should be > w[lo]."""
        self._importance_pairs = [
            (int(h), int(l)) for h, l in order_pairs
            if 0 <= int(h) < self.n_obj and 0 <= int(l) < self.n_obj
        ]
        self._order_confidence = float(np.clip(confidence, 0.0, 1.0))

    def _to_pref_space(self, F: np.ndarray) -> np.ndarray:
        arr = np.atleast_2d(np.asarray(F, dtype=float))
        if self._ref_min is not None:
            normalized = (arr - self._ref_min) / (self._ref_max - self._ref_min + 1e-8)
            return np.clip(normalized, 0.0, 1.0)
        return arr

    def _build_quad(self, pref: np.ndarray) -> np.ndarray:
        if self.use_full_quad:
            return _build_quadratic_features(pref)
        return _build_cross_features(pref)

    def _build_nl_features(self, pref: np.ndarray) -> np.ndarray:
        """Random ReLU features: ReLU(pref @ W_fixed + b_fixed)."""
        return np.maximum(0.0, np.atleast_2d(pref) @ self._W_nl + self._b_nl)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def update(
        self,
        F_rounds: List[np.ndarray],
        chosen_indices: List[int],
        round_idx: int = 0,
        worst_indices: Optional[List[Optional[int]]] = None,
        round_weights: Optional[Sequence[float]] = None,
    ) -> None:
        n_obj = self.n_obj
        n_quad = self.n_quad
        n_hidden = self.n_hidden
        cross_offset = n_obj if self.use_full_quad else 0
        n_cross = self.n_cross

        if len(F_rounds) < self.min_rounds_for_residual:
            self._delta_w = np.zeros(n_obj, dtype=float)
            self._a = np.zeros(n_quad, dtype=float)
            self._a[cross_offset:cross_offset + n_cross] = (
                self._structure_prior_target.copy()
            )
            self._a_nl = np.zeros(n_hidden, dtype=float)
            return

        pref_rounds = [self._to_pref_space(fr) for fr in F_rounds]
        quad_rounds = [self._build_quad(fr) for fr in pref_rounds]
        nl_rounds = [self._build_nl_features(fr) for fr in pref_rounds]
        if round_weights is None:
            fit_round_weights = np.ones(len(pref_rounds), dtype=float)
        else:
            fit_round_weights = np.asarray(round_weights, dtype=float).reshape(-1)
            if len(fit_round_weights) != len(pref_rounds):
                raise ValueError("round_weights must align with F_rounds")
            if not np.all(np.isfinite(fit_round_weights)) or np.any(fit_round_weights < 0.0):
                raise ValueError("round_weights must be finite and non-negative")
            if not np.any(fit_round_weights > 0.0):
                raise ValueError("round_weights must contain a positive value")
        padded_worst = list(worst_indices or [])
        if len(padded_worst) < len(pref_rounds):
            padded_worst.extend([None] * (len(pref_rounds) - len(padded_worst)))

        prior_w = self._base_w.copy()
        theta0 = np.concatenate([self._delta_w, self._a, self._a_nl])
        bounds = (
            [(-prior_w[i] + 1e-6, self.delta_cap) for i in range(n_obj)]
            + [(None, None)] * n_quad
            + [(None, None)] * n_hidden
        )
        lam_d = self.lambda_delta

        cross_scale = (
            self.early_cross_multiplier
            if round_idx < self.cross_unlock_round
            else 1.0
        )
        if len(F_rounds) <= 1:
            cross_scale *= 2.0
        lam_c = self.lambda_cross * cross_scale
        lam_nl = self.lambda_nl
        lam_uninformed_cross = self.lambda_uninformed_cross * cross_scale

        struct_conf = self._structure_confidence
        struct_target = self._structure_prior_target
        imp_pairs = self._importance_pairs
        lam_order = self.lambda_order * self._order_confidence
        order_margin = 0.02

        def _reg_and_grad(
            delta: np.ndarray,
            q: np.ndarray,
            a_nl: np.ndarray,
            w: np.ndarray,
        ) -> Tuple[float, np.ndarray, np.ndarray, np.ndarray]:
            q_diag = q[:cross_offset]
            q_cross = q[cross_offset:cross_offset + n_cross]
            diff_cross = q_cross - struct_target

            reg = float(
                lam_d * np.sum(delta ** 2)
                + lam_c * np.sum(q_diag ** 2)
                + lam_c * struct_conf * np.sum(diff_cross ** 2)
                + lam_uninformed_cross * (1.0 - struct_conf) * np.sum(q_cross ** 2)
                + lam_nl * np.sum(a_nl ** 2)
            )
            g_d = 2.0 * lam_d * delta.copy()
            g_q = np.zeros(n_quad, dtype=float)
            g_q[:cross_offset] = 2.0 * lam_c * q_diag
            g_q[cross_offset:cross_offset + n_cross] = (
                2.0 * lam_c * struct_conf * diff_cross
                + 2.0 * lam_uninformed_cross * (1.0 - struct_conf) * q_cross
            )
            g_nl = 2.0 * lam_nl * a_nl.copy()

            if lam_order > 0.0:
                for hi, lo in imp_pairs:
                    violation = w[lo] - w[hi] + order_margin
                    if violation > 0.0:
                        pen = violation * violation
                        reg += float(lam_order * pen)
                        g_d[lo] += 2.0 * lam_order * violation
                        g_d[hi] -= 2.0 * lam_order * violation
            return reg, g_d, g_q, g_nl

        if self.interaction_loss == "pairwise_expand":
            pair_data = self._build_pairwise_training_data(
                pref_rounds,
                chosen_indices,
                fit_round_weights,
            )
            if pair_data is None:
                return
            diff_linear, diff_quad, diff_nl, pair_weights = pair_data

            def objective(theta: np.ndarray) -> float:
                delta = theta[:n_obj]
                q = theta[n_obj:n_obj + n_quad]
                a_nl = theta[n_obj + n_quad:]
                w = prior_w + delta
                logits = diff_linear @ w + diff_quad @ q + diff_nl @ a_nl
                rank_loss = -np.sum(pair_weights * np.log(sigmoid(logits) + 1e-12))
                reg, _, _, _ = _reg_and_grad(delta, q, a_nl, w)
                return float(rank_loss + reg)

            def gradient(theta: np.ndarray) -> np.ndarray:
                delta = theta[:n_obj]
                q = theta[n_obj:n_obj + n_quad]
                a_nl = theta[n_obj + n_quad:]
                w = prior_w + delta
                logits = diff_linear @ w + diff_quad @ q + diff_nl @ a_nl
                resid = pair_weights * (1.0 - sigmoid(logits))
                _, g_d, g_q, g_nl = _reg_and_grad(delta, q, a_nl, w)
                g_d -= diff_linear.T @ resid
                g_q -= diff_quad.T @ resid
                g_nl -= diff_nl.T @ resid
                return np.concatenate([g_d, g_q, g_nl])
        else:
            slate_rounds = self._build_slate_training_data(
                pref_rounds,
                quad_rounds,
                nl_rounds,
                chosen_indices,
                padded_worst,
                fit_round_weights,
            )
            if not slate_rounds:
                return

            def objective(theta: np.ndarray) -> float:
                delta = theta[:n_obj]
                q = theta[n_obj:n_obj + n_quad]
                a_nl = theta[n_obj + n_quad:]
                w = prior_w + delta
                total = 0.0
                for pr, qr, nlr, ci, wi, round_weight in slate_rounds:
                    scores = pr @ w + qr @ q + nlr @ a_nl
                    total += round_weight * self._top1_slate_loss(scores, ci)
                    if self.interaction_loss == "top1_worst1_slate" and wi is not None:
                        total += round_weight * self._worst1_slate_loss(scores, wi)
                reg, _, _, _ = _reg_and_grad(delta, q, a_nl, w)
                return float(total + reg)

            def gradient(theta: np.ndarray) -> np.ndarray:
                delta = theta[:n_obj]
                q = theta[n_obj:n_obj + n_quad]
                a_nl = theta[n_obj + n_quad:]
                w = prior_w + delta
                _, g_d, g_q, g_nl = _reg_and_grad(delta, q, a_nl, w)
                for pr, qr, nlr, ci, wi, round_weight in slate_rounds:
                    scores = pr @ w + qr @ q + nlr @ a_nl
                    top1_probs = self._softmax(-scores)
                    g_d += round_weight * (pr[ci] - top1_probs @ pr)
                    g_q += round_weight * (qr[ci] - top1_probs @ qr)
                    g_nl += round_weight * (nlr[ci] - top1_probs @ nlr)
                    if self.interaction_loss == "top1_worst1_slate" and wi is not None:
                        worst_probs = self._softmax(scores)
                        g_d += round_weight * (-pr[wi] + worst_probs @ pr)
                        g_q += round_weight * (-qr[wi] + worst_probs @ qr)
                        g_nl += round_weight * (-nlr[wi] + worst_probs @ nlr)
                return np.concatenate([g_d, g_q, g_nl])

        result = sp_minimize(
            objective,
            theta0,
            jac=gradient,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 200, "ftol": 1e-10},
        )
        self._delta_w = result.x[:n_obj].copy()
        self._a = result.x[n_obj:n_obj + n_quad].copy()
        self._a_nl = result.x[n_obj + n_quad:].copy()

    def _build_pairwise_training_data(
        self,
        pref_rounds: List[np.ndarray],
        chosen_indices: List[int],
        round_weights: np.ndarray,
    ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
        pairs: List[Tuple[np.ndarray, np.ndarray]] = []
        pair_weights: List[float] = []
        for pref_round, chosen_idx, round_weight in zip(
            pref_rounds, chosen_indices, round_weights
        ):
            if not (0 <= int(chosen_idx) < len(pref_round)):
                continue
            chosen = pref_round[int(chosen_idx)]
            for idx in range(len(pref_round)):
                if idx != chosen_idx:
                    pairs.append((chosen, pref_round[idx]))
                    pair_weights.append(float(round_weight))
        if not pairs:
            return None
        chosen_arr = np.stack([c for c, _ in pairs])
        rejected_arr = np.stack([r for _, r in pairs])
        diff_linear = rejected_arr - chosen_arr
        diff_quad = self._build_quad(rejected_arr) - self._build_quad(chosen_arr)
        diff_nl = self._build_nl_features(rejected_arr) - self._build_nl_features(chosen_arr)
        return diff_linear, diff_quad, diff_nl, np.asarray(pair_weights, dtype=float)

    def _build_slate_training_data(
        self,
        pref_rounds: List[np.ndarray],
        quad_rounds: List[np.ndarray],
        nl_rounds: List[np.ndarray],
        chosen_indices: List[int],
        worst_indices: List[Optional[int]],
        round_weights: np.ndarray,
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray, int, Optional[int], float]]:
        rounds: List[
            Tuple[np.ndarray, np.ndarray, np.ndarray, int, Optional[int], float]
        ] = []
        for pref_round, quad_round, nl_round, chosen_idx, worst_idx, round_weight in zip(
            pref_rounds,
            quad_rounds,
            nl_rounds,
            chosen_indices,
            worst_indices,
            round_weights,
        ):
            chosen = int(chosen_idx)
            if not (0 <= chosen < len(pref_round)):
                continue
            worst: Optional[int] = None
            if worst_idx is not None:
                worst_val = int(worst_idx)
                if 0 <= worst_val < len(pref_round) and worst_val != chosen:
                    worst = worst_val
            rounds.append(
                (pref_round, quad_round, nl_round, chosen, worst, float(round_weight))
            )
        return rounds

    @staticmethod
    def _softmax(values: np.ndarray) -> np.ndarray:
        shifted = values - np.max(values)
        exp_values = np.exp(shifted)
        return exp_values / np.sum(exp_values)

    @staticmethod
    def _top1_slate_loss(scores: np.ndarray, chosen_idx: int) -> float:
        return float(scores[chosen_idx] + _logsumexp(-scores))

    @staticmethod
    def _worst1_slate_loss(scores: np.ndarray, worst_idx: int) -> float:
        return float(-scores[worst_idx] + _logsumexp(scores))

    # ------------------------------------------------------------------
    # Scoring (lower = better)
    # ------------------------------------------------------------------
    def _effective_w(self) -> np.ndarray:
        return self._base_w + self._delta_w

    def score(self, F: np.ndarray) -> np.ndarray:
        """Return disutility scores for each row of *F*. Lower is better."""
        pref = self._to_pref_space(F)
        linear = pref @ self._effective_w()
        quad = self._build_quad(pref) @ self._a
        nl = self._build_nl_features(pref) @ self._a_nl
        return linear + quad + nl

    def score_batch(self, F: np.ndarray) -> np.ndarray:
        """Batch scoring name used by the Agent preference interface."""
        return self.score(F)

    def get_linear_weights(self) -> np.ndarray:
        w = np.clip(self._effective_w(), 0.0, None)
        total = w.sum()
        return w / total if total > 0 else np.ones(self.n_obj) / self.n_obj


class FCPEUtilityEnsemble:
    """Same-config SLFN members with normalized-rank consensus scoring."""

    def __init__(
        self,
        *,
        member_seeds: Sequence[int] = (42, 43, 44, 45, 46),
        **learner_kwargs,
    ) -> None:
        self.member_seeds = tuple(int(seed) for seed in member_seeds)
        if not self.member_seeds:
            raise ValueError("member_seeds must not be empty")
        self.members = [
            FCPEUtilityLearner(rng_seed=seed, **learner_kwargs)
            for seed in self.member_seeds
        ]
        self.n_obj = self.members[0].n_obj
        self.interaction_loss = self.members[0].interaction_loss

    def set_reference(self, F: np.ndarray) -> None:
        for member in self.members:
            member.set_reference(F)

    def set_structure_prior(self, *args, **kwargs) -> None:
        for member in self.members:
            member.set_structure_prior(*args, **kwargs)

    def set_importance_order(self, *args, **kwargs) -> None:
        for member in self.members:
            member.set_importance_order(*args, **kwargs)

    def update(self, *args, **kwargs) -> None:
        for member in self.members:
            member.update(*args, **kwargs)

    def _to_pref_space(self, F: np.ndarray) -> np.ndarray:
        return self.members[0]._to_pref_space(F)

    def get_linear_weights(self) -> np.ndarray:
        return np.mean(
            np.vstack([member.get_linear_weights() for member in self.members]),
            axis=0,
        )

    def score(self, F: np.ndarray) -> np.ndarray:
        return self.posterior_rank_scores(F)

    def posterior_rank_scores(self, F: np.ndarray) -> np.ndarray:
        """Average normalized member ranks; lower is better."""
        rows = np.atleast_2d(np.asarray(F, dtype=float))
        if not len(rows):
            return np.empty(0, dtype=float)
        denominator = max(1, len(rows) - 1)
        member_ranks = []
        for member in self.members:
            order = np.argsort(member.score(rows), kind="stable")
            ranks = np.empty(len(rows), dtype=float)
            ranks[order] = np.arange(len(rows), dtype=float) / denominator
            member_ranks.append(ranks)
        return np.mean(np.vstack(member_ranks), axis=0)
