"""Domain models for preference learning and site recommendations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

Direction = Literal["min", "max"]


@dataclass(frozen=True)
class ObjectiveSpec:
    name: str
    direction: Direction = "min"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("objective name must be non-empty")
        if self.direction not in ("min", "max"):
            raise ValueError("objective direction must be 'min' or 'max'")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    objectives: Mapping[str, float]
    variables: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty")
        normalized = {str(key): float(value) for key, value in self.objectives.items()}
        if not normalized:
            raise ValueError("candidate must have at least one objective")
        object.__setattr__(self, "objectives", normalized)
        object.__setattr__(self, "variables", {str(k): float(v) for k, v in self.variables.items()})
        object.__setattr__(self, "metadata", dict(self.metadata))

    def vector(self, objective_specs: Sequence[ObjectiveSpec]) -> list[float]:
        try:
            return [float(self.objectives[spec.name]) for spec in objective_specs]
        except KeyError as exc:
            raise ValueError(f"candidate {self.candidate_id} is missing objective {exc.args[0]}") from exc


@dataclass(frozen=True)
class PreferenceChoice:
    scene_id: str
    candidates: tuple[Candidate, ...]
    chosen_id: str
    reason: str = ""
    experiment_id: str | None = None
    timestamp: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scene_id.strip():
            raise ValueError("scene_id must be non-empty")
        candidates = tuple(self.candidates)
        if not candidates:
            raise ValueError("choice must contain candidates")
        ids = [candidate.candidate_id for candidate in candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("choice candidates must have unique ids")
        if self.chosen_id not in ids:
            raise ValueError("chosen_id must refer to one of the candidates")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "reason", str(self.reason or ""))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "experiment_id": self.experiment_id,
            "timestamp": self.timestamp,
            "chosen_id": self.chosen_id,
            "reason": self.reason,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "objectives": dict(candidate.objectives),
                    "variables": dict(candidate.variables),
                    "metadata": dict(candidate.metadata),
                }
                for candidate in self.candidates
            ],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class Recommendation:
    candidate: Candidate
    rank: int
    utility_score: float
    diversity_distance: float | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate.candidate_id,
            "rank": self.rank,
            "utility_score": self.utility_score,
            "diversity_distance": self.diversity_distance,
            "reason": self.reason,
            "objectives": dict(self.candidate.objectives),
            "variables": dict(self.candidate.variables),
            "metadata": dict(self.candidate.metadata),
        }
