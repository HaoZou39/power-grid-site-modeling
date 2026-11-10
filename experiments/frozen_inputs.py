"""Rebuild a project config from the values captured when a workspace job was submitted."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

# File locations stay with the machine that executes the job. Numeric inputs stay with the submission.
_PATH_FIELDS = {
    "dem_path",
    "landuse_path",
    "osm_roads_path",
    "reference_geotiff_path",
    "output_dir",
    "validation_preferences_path",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def dump_project(config: Any) -> dict[str, Any]:
    def walk(item: Any) -> Any:
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, dict):
            return {key: walk(value) for key, value in item.items()}
        if isinstance(item, (tuple, list)):
            return [walk(value) for value in item]
        return item

    return walk(asdict(config))


def project_from_frozen(stored: dict[str, Any]):
    """Overlay a submitted project onto the current dataclass shape. Stored numbers win."""

    from config.project_config import load_default_config

    return _overlay(load_default_config(), stored)


def _overlay(instance: Any, values: dict[str, Any]) -> Any:
    kwargs = {}
    for field in fields(instance):
        if field.name not in values or field.name in _PATH_FIELDS:
            continue
        current = getattr(instance, field.name)
        value = values[field.name]
        if is_dataclass(current) and isinstance(value, dict):
            kwargs[field.name] = _overlay(current, value)
        elif isinstance(current, tuple) and isinstance(value, list):
            kwargs[field.name] = tuple(value)
        elif isinstance(current, Path):
            continue
        else:
            kwargs[field.name] = value
    return replace(instance, **kwargs)
