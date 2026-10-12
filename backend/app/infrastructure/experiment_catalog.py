"""Adapter that lists completed output folders and deletes one of them."""

from __future__ import annotations

import json
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.domain.experiments import ArtifactRecord, ExperimentRecord


class ExperimentNotFound(FileNotFoundError):
    """Raised when an experiment or artifact is not in the configured catalog."""


_KIND_BY_SUFFIX = {
    ".png": "image",
    ".html": "html",
    ".json": "json",
    ".csv": "table",
}
_MEDIA_TYPE_BY_SUFFIX = {
    ".png": "image/png",
    ".html": "text/html",
    ".json": "application/json",
    ".csv": "text/csv",
}


class ExperimentCatalog:
    """Catalog for completed experiment directories.

    Only direct child directories containing ``run_summary.json`` are exposed.
    Artifact names are resolved against the selected directory, so callers
    cannot use this adapter to read arbitrary files outside the configured root.
    Deletion removes one of those completed directories and cannot leave the root.
    """

    def __init__(self, root: str | Path = "outputs") -> None:
        self.root = Path(root).expanduser().resolve()

    def list_experiments(self) -> list[ExperimentRecord]:
        """List only directories with a completed ``run_summary.json``."""
        if not self.root.is_dir():
            return []
        records = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if path.is_dir() and (path / "run_summary.json").is_file():
                records.append(self._read_experiment(path))
        return records

    def get_experiment(self, experiment_id: str) -> ExperimentRecord:
        path = self._completed_directory(experiment_id)
        return self._read_experiment(path)

    def delete_experiment(self, experiment_id: str) -> None:
        """Remove one completed experiment directory under the catalog root."""

        path = self._completed_directory(experiment_id)
        shutil.rmtree(path)

    def resolve_artifact(self, experiment_id: str, artifact_id: str) -> tuple[Path, ArtifactRecord]:
        """Resolve an allow-listed artifact without leaving the output root."""
        experiment = self.get_experiment(experiment_id)
        artifact = next((item for item in experiment.artifacts if item.id == artifact_id), None)
        if artifact is None:
            raise ExperimentNotFound(f"{experiment_id}/{artifact_id}")
        path = self._experiment_path(experiment_id) / artifact.id
        if not path.is_file():
            raise ExperimentNotFound(f"{experiment_id}/{artifact_id}")
        return path, artifact

    def _experiment_path(self, experiment_id: str) -> Path:
        if not experiment_id or experiment_id in {".", ".."} or "/" in experiment_id or "\\" in experiment_id:
            raise ExperimentNotFound(experiment_id)
        candidate = (self.root / experiment_id).resolve()
        if candidate.parent != self.root:
            raise ExperimentNotFound(experiment_id)
        return candidate

    def _completed_directory(self, experiment_id: str) -> Path:
        path = self._experiment_path(experiment_id)
        if not path.is_dir() or not (path / "run_summary.json").is_file():
            raise ExperimentNotFound(experiment_id)
        return path

    def _read_experiment(self, path: Path) -> ExperimentRecord:
        summary = self._read_json(path / "run_summary.json")
        algorithm = self._algorithm_name(path, summary)
        artifacts = [
            self._artifact(file_path)
            for file_path in sorted(path.iterdir(), key=lambda item: item.name)
            if file_path.is_file() and file_path.suffix.lower() in _KIND_BY_SUFFIX
        ]
        summary_path = path / "run_summary.json"
        return ExperimentRecord(
            id=path.name,
            name=path.name,
            algorithm=algorithm,
            summary=summary,
            artifacts=artifacts,
            modified_at=datetime.fromtimestamp(summary_path.stat().st_mtime, timezone.utc).isoformat(),
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid experiment summary: {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"experiment summary must be an object: {path}")
        return value

    @staticmethod
    def _algorithm_name(path: Path, summary: dict[str, Any]) -> str:
        for key in ("algorithm", "algorithm_name"):
            value = summary.get(key)
            if isinstance(value, str) and value:
                return value
        resolved_config = path / "resolved_config.json"
        if resolved_config.is_file():
            try:
                config = json.loads(resolved_config.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                config = {}
            for section in ("cma_es", "multistart_adam", "vae_like_multihead"):
                value = (
                    config.get(section, {}).get("algorithm_name")
                    if isinstance(config, dict)
                    else None
                )
                if isinstance(value, str) and value:
                    return value
        return "unknown"

    @staticmethod
    def _artifact(path: Path) -> ArtifactRecord:
        suffix = path.suffix.lower()
        return ArtifactRecord(
            id=path.name,
            name=path.name,
            kind=_KIND_BY_SUFFIX[suffix],
            media_type=_MEDIA_TYPE_BY_SUFFIX[suffix],
            size_bytes=path.stat().st_size,
        )


def media_type_for(path: Path) -> str:
    """Return a safe media type for a catalog-validated artifact path."""

    return _MEDIA_TYPE_BY_SUFFIX.get(
        path.suffix.lower(),
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )
