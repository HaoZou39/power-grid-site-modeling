from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactRecord:
    """A safe, read-only reference to one experiment output file."""

    id: str
    name: str
    kind: str
    media_type: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentRecord:
    id: str
    name: str
    algorithm: str
    summary: dict[str, Any]
    artifacts: list[ArtifactRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "algorithm": self.algorithm,
            "summary": self.summary,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }
