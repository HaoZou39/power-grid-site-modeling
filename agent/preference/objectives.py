"""Objective validation and fixed-envelope normalization."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from agent.preference.models import Candidate, ObjectiveSpec


@dataclass(frozen=True)
class ObjectiveEnvelope:
    specs: tuple[ObjectiveSpec, ...]
    minimums: tuple[float, ...]
    maximums: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.specs:
            raise ValueError("at least one objective is required")
        if len(self.specs) != len(self.minimums) or len(self.specs) != len(self.maximums):
            raise ValueError("objective envelope dimensions do not match")
        if any(not np.isfinite(value) for value in (*self.minimums, *self.maximums)):
            raise ValueError("objective envelope must be finite")
        if any(lo >= hi for lo, hi in zip(self.minimums, self.maximums)):
            raise ValueError("objective envelope minimums must be below maximums")

    @classmethod
    def from_candidates(
        cls,
        candidates: Sequence[Candidate],
        specs: Sequence[ObjectiveSpec],
        *,
        padding_ratio: float = 0.0,
    ) -> "ObjectiveEnvelope":
        if not candidates:
            raise ValueError("cannot infer envelope from empty candidates")
        if padding_ratio < 0:
            raise ValueError("padding_ratio must be non-negative")
        matrix = np.asarray([candidate.vector(specs) for candidate in candidates], dtype=float)
        minimums = matrix.min(axis=0)
        maximums = matrix.max(axis=0)
        span = np.maximum(maximums - minimums, 1e-8)
        minimums = minimums - span * padding_ratio
        maximums = maximums + span * padding_ratio
        return cls(tuple(specs), tuple(minimums.tolist()), tuple(maximums.tolist()))

    @classmethod
    def from_mapping(
        cls,
        specs: Sequence[ObjectiveSpec],
        minimums: Iterable[float],
        maximums: Iterable[float],
    ) -> "ObjectiveEnvelope":
        return cls(tuple(specs), tuple(float(x) for x in minimums), tuple(float(x) for x in maximums))

    def normalize(self, candidates: Sequence[Candidate]) -> np.ndarray:
        if not candidates:
            return np.empty((0, len(self.specs)), dtype=float)
        values = np.asarray([candidate.vector(self.specs) for candidate in candidates], dtype=float)
        minimums = np.asarray(self.minimums)
        maximums = np.asarray(self.maximums)
        normalized = (values - minimums) / (maximums - minimums + 1e-12)
        normalized = np.clip(normalized, 0.0, 1.0)
        for index, spec in enumerate(self.specs):
            if spec.direction == "max":
                normalized[:, index] = 1.0 - normalized[:, index]
        return normalized

    def to_dict(self) -> dict[str, object]:
        return {
            "objectives": [{"name": spec.name, "direction": spec.direction} for spec in self.specs],
            "minimums": list(self.minimums),
            "maximums": list(self.maximums),
        }
