"""Utility learned from past choices: linear + quadratic + random-ReLU terms (an SLFN).

Inputs are rows already normalized to [0, 1], every objective minimized. Scores are
disutility: lower is better. Each choice becomes pairs "chosen beats every other
candidate in its menu", fitted with a logistic loss around the prior linear weights.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


@dataclass(frozen=True)
class SlfnConfig:
    n_hidden: int = 16
    lambda_delta: float = 0.5  # pulls linear weights back to the prior
    lambda_quad: float = 0.1  # on squared terms and ReLU outputs; cross terms are not penalized
    single_choice_quad_multiplier: float = 16.0  # with one choice, squared terms stay near zero
    delta_cap: float = 2.0
    max_iter: int = 200
    seed: int = 42


class SlfnUtility:
    def __init__(self, prior: np.ndarray, config: SlfnConfig) -> None:
        """`prior`: non-negative linear weights, one per objective; scaled to sum 1."""
        prior = np.asarray(prior, dtype=float)
        if prior.ndim != 1 or prior.size < 1 or np.any(prior < 0) or prior.sum() <= 0:
            raise ValueError("prior must be non-negative weights with a positive sum")
        n_obj = prior.size
        self.n_obj = n_obj
        self.config = config
        rng = np.random.RandomState(config.seed)
        self._w0 = prior / prior.sum()
        self._hidden_w = rng.standard_normal((n_obj, config.n_hidden)) / np.sqrt(n_obj)
        self._hidden_b = rng.uniform(-1.0, 1.0, size=config.n_hidden)
        self._cross = [(i, j) for i in range(n_obj) for j in range(i + 1, n_obj)]
        self._theta = np.zeros(2 * n_obj + len(self._cross) + config.n_hidden)

    def _features(self, rows: np.ndarray) -> np.ndarray:
        """[linear | squared | cross | ReLU] columns; theta is laid out the same way."""
        rows = np.atleast_2d(rows)
        cross = [rows[:, i] * rows[:, j] for i, j in self._cross]
        hidden = np.maximum(0.0, rows @ self._hidden_w + self._hidden_b)
        return np.column_stack([rows, rows**2, *cross, hidden])

    def fit(self, menus: list[np.ndarray], chosen: list[int]) -> None:
        if len(menus) != len(chosen) or not menus:
            raise ValueError("menus and chosen must be non-empty and aligned")
        diffs = []
        for menu, index in zip(menus, chosen):
            features = self._features(menu)
            diffs.append(np.delete(features, index, axis=0) - features[index])
        diff = np.vstack(diffs)

        n, cfg = self.n_obj, self.config
        n_cross = len(self._cross)
        quad = cfg.lambda_quad * (cfg.single_choice_quad_multiplier if len(menus) == 1 else 1.0)
        penalty = np.concatenate([
            np.full(n, cfg.lambda_delta),
            np.full(n, quad),
            np.zeros(n_cross),
            np.full(cfg.n_hidden, cfg.lambda_quad),
        ])
        offset = np.concatenate([self._w0, np.zeros(n + n_cross + cfg.n_hidden)])

        def loss(theta: np.ndarray) -> tuple[float, np.ndarray]:
            logits = diff @ (theta + offset)
            value = -np.sum(np.log(expit(logits) + 1e-12)) + np.sum(penalty * theta**2)
            grad = -diff.T @ (1.0 - expit(logits)) + 2.0 * penalty * theta
            return float(value), grad

        bounds = [(-w + 1e-6, cfg.delta_cap) for w in self._w0] + [(None, None)] * (len(offset) - n)
        result = minimize(loss, self._theta, jac=True, method="L-BFGS-B", bounds=bounds,
                          options={"maxiter": cfg.max_iter, "ftol": 1e-10})
        self._theta = result.x

    def score(self, rows: np.ndarray) -> np.ndarray:
        offset = np.concatenate([self._w0, np.zeros(len(self._theta) - self.n_obj)])
        return self._features(rows) @ (self._theta + offset)

    def importance(self, rows: np.ndarray, eps: float = 1e-4) -> np.ndarray:
        """Mean slope of the score per objective over `rows`, negatives dropped, summing to 1.

        Covers the quadratic and ReLU terms too, which carry most of what one or two choices teach.
        """
        base = self.score(rows)
        slopes = np.array([(self.score(rows + eps * np.eye(self.n_obj)[i]) - base).mean() / eps for i in range(self.n_obj)])
        slopes = np.clip(slopes, 0.0, None)
        return slopes / slopes.sum() if slopes.sum() > 0 else self._w0.copy()
