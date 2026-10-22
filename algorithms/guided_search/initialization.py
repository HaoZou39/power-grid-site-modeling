"""Reproducible Gaussian, uniform and Taguchi orthogonal initial poses."""

from __future__ import annotations

import math

import numpy as np


INITIALIZATION_METHODS = ("gaussian", "uniform", "taguchi")


def sample_initial_population(
    popsize: int,
    seed: int,
    method: str = "uniform",
    sigma0: float = 1.0,
) -> np.ndarray:
    """Return float32 raw poses; uniformity is defined after sigmoid decoding."""
    if popsize < 4:
        raise ValueError("popsize must be at least 4")
    if method not in INITIALIZATION_METHODS:
        raise ValueError(f"initialization must be one of {INITIALIZATION_METHODS}")
    if not math.isfinite(sigma0) or sigma0 <= 0:
        raise ValueError("sigma0 must be finite and positive")
    rng = np.random.default_rng(seed)
    if method == "gaussian":
        return rng.normal(0.0, sigma0, size=(popsize, 3)).astype(np.float32)
    if method == "uniform":
        unit = rng.random((popsize, 3))
    else:
        levels = math.isqrt(popsize)
        if levels * levels != popsize:
            raise ValueError("taguchi initialization requires a square popsize, such as 10000")
        a, b = np.indices((levels, levels)).reshape(2, -1)
        table = np.column_stack((a, b, (a + b) % levels))
        for column in range(3):
            table[:, column] = rng.permutation(levels)[table[:, column]]
        unit = (table[rng.permutation(popsize)] + 0.5) / levels
    epsilon = np.finfo(np.float32).eps
    unit = np.clip(unit, epsilon, 1.0 - epsilon)
    return (np.log(unit) - np.log1p(-unit)).astype(np.float32)
