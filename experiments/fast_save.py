"""Copy an unmodified automatic site result into a new case.

The caller keeps the re-evaluation save. This module returns a reason instead of
writing when any check fails, and it does not load scene rasters or rebuild a front.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.app.infrastructure.experiment_catalog import ExperimentCatalog, ExperimentNotFound

logger = logging.getLogger("site-modeling.fast-save")

_REQUIRED_FILES = (
    "solutions.csv",
    "pareto_solutions.csv",
    "site_form_snapshot.json",
    "resolved_config.json",
    "data_metadata.json",
    "run_summary.json",
)
_METRIC_FIELDS = (
    "dem_soft",
    "obstacle_soft",
    "road_distance",
    "demand_distance",
    "offroad_haul_m",
    "haul_rise_m",
    "obstacle_hard_count",
)
_LAYER_FIELDS = ("dem_soft", "offroad_haul_m", "haul_rise_m")
_COLUMNS = (
    "run_id", "weight_dem", "weight_road", "weight_demand", "raw_x", "raw_y", "raw_theta",
    "x", "y", "theta", "scalar", "dem_soft", "obstacle_soft", "road_distance", "demand_distance",
    "road_haul_m", "offroad_haul_m", "haul_rise_m", "dem_hard_var", "dem_hard_range",
    "obstacle_hard_count", "obstacle_hard_ratio", "is_feasible", "id", "manual",
    "pareto_layer", "derived_from", "is_pareto",
)
_SETBACKS = ("road_setback_m", "water_setback_m", "highway_setback_m")


class FastSaveAttempt:
    def __init__(self, experiment_id: str | None, reason: str, validation_s: float, write_s: float) -> None:
        self.experiment_id = experiment_id
        self.reason = reason
        self.validation_s = validation_s
        self.write_s = write_s


def try_fast_save(
    catalog: ExperimentCatalog,
    name: str,
    form: dict[str, Any],
    poses: list[dict[str, Any]],
    source_experiment_id: str | None,
    fast_source_experiment_id: str,
) -> FastSaveAttempt:
    """Write one case when the request is the unmodified source, otherwise explain why not."""

    from time import perf_counter

    started = perf_counter()
    try:
        ready = _verified_case(catalog, name, form, poses, source_experiment_id, fast_source_experiment_id)
    except Exception:
        logger.exception("fast save verification failed")
        return FastSaveAttempt(None, "verification_error", perf_counter() - started, 0.0)
    validation_s = perf_counter() - started
    if isinstance(ready, str):
        return FastSaveAttempt(None, ready, validation_s, 0.0)
    write_started = perf_counter()
    experiment_id = _publish(catalog.root, ready)
    return FastSaveAttempt(experiment_id, "", validation_s, perf_counter() - write_started)


def log_save_path(
    mode: str,
    source_experiment_id: str | None,
    saved_experiment_id: str | None,
    pose_count: int,
    fallback_reason: str,
    validation_s: float,
    evaluate_s: float,
    pareto_s: float,
    write_s: float,
    total_s: float,
) -> None:
    logger.info(
        "fast_save=%s source_experiment_id=%s saved_experiment_id=%s pose_count=%d "
        "fallback_reason=%s validation_s=%.6f evaluate_s=%.6f pareto_s=%.6f write_s=%.6f total_s=%.6f",
        mode,
        source_experiment_id or "-",
        saved_experiment_id or "-",
        pose_count,
        fallback_reason or "-",
        validation_s,
        evaluate_s,
        pareto_s,
        write_s,
        total_s,
    )


def _verified_case(
    catalog: ExperimentCatalog,
    name: str,
    form: dict[str, Any],
    poses: list[dict[str, Any]],
    source_experiment_id: str | None,
    fast_source_experiment_id: str,
) -> dict[str, Any] | str:
    if fast_source_experiment_id != source_experiment_id:
        return "source_mismatch"
    try:
        files = {filename: catalog.resolve_artifact(fast_source_experiment_id, filename)[0] for filename in _REQUIRED_FILES}
    except ExperimentNotFound:
        return "missing_file"
    directory = files["run_summary.json"].parent
    if (directory / "workspace_solutions.json").is_file():
        return "manual_case"
    summary = _object(files["run_summary.json"])
    snapshot = _object(files["site_form_snapshot.json"])
    resolved = _object(files["resolved_config.json"])
    source_metadata = _object(files["data_metadata.json"])
    if summary is None or snapshot is None or resolved is None or source_metadata is None:
        return "missing_file"
    trusted = _trusted_auto_source(directory, summary, snapshot)
    if trusted:
        return trusted
    if _config_mismatch(form, snapshot, resolved):
        return "config_mismatch"
    version = _scene_version(form, source_metadata)
    if isinstance(version, str):
        return version
    table = _solution_table(files["solutions.csv"], files["pareto_solutions.csv"], form)
    if isinstance(table, str):
        return table
    rows, layers, pareto_ids = table
    selected = _selected_rows(poses, rows, layers, pareto_ids, form)
    if isinstance(selected, str):
        return selected
    from algorithms.guided_search.search import guided_objective_names

    names = guided_objective_names(form.get("origin_x") is not None, bool(form.get("include_demand")))
    return {
        "name": name,
        "form": form,
        "source_experiment_id": source_experiment_id,
        "metadata": _case_metadata(form, version),
        "version": version,
        "rows": selected,
        "objective_names": list(names),
    }


def _trusted_auto_source(directory: Path, summary: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    if summary.get("is_case") is True:
        return "manual_case"
    algorithm = summary.get("algorithm")
    if algorithm == "nsga2":
        algorithm = "guided_search"
    if algorithm != "guided_search" or summary.get("result_origin") != "auto" or summary.get("problem_type") != "site":
        return "untrusted_source"
    label = " ".join(str(summary.get(key) or "") for key in ("display_name", "experiment_name"))
    label = f"{label} {snapshot.get('experiment_name') or ''} {directory.name}"
    if "局部优化" in label:
        return "local_refine"
    return None


def _config_mismatch(form: dict[str, Any], snapshot: dict[str, Any], resolved: dict[str, Any]) -> bool:
    modeling = resolved.get("modeling")
    if not isinstance(modeling, dict):
        return True
    for key in ("rect_w_m", "rect_h_m"):
        if not _same_value(form.get(key), snapshot.get(key)) or not _same_value(form.get(key), modeling.get(key)):
            return True
    for key in _SETBACKS:
        expected = snapshot[key] if key in snapshot else modeling.get(key)
        if not _same_value(form.get(key), expected) or not _same_value(form.get(key), modeling.get(key)):
            return True
    for key in ("scene_name", "mountain_policy", "field_policy", "field_cost", "exclusion_zones",
                "feasible_zones", "include_demand", "max_elevation_m", "origin_x", "origin_y"):
        if not _same_value(form.get(key), snapshot.get(key)):
            return True
    recorded = snapshot.get("diagonal_access", True)
    return recorded is not True or form.get("diagonal_access") is not True


def _scene_version(form: dict[str, Any], source_metadata: dict[str, Any]) -> dict[str, Any] | str:
    from experiments.scene_store import ensure_scene_readable, scene_directory, scenes_root
    from experiments.scene_version import scene_data_version

    stored = source_metadata.get("data_version")
    if not isinstance(stored, dict):
        return "scene_version"
    try:
        scene = scene_directory(scenes_root(None), str(form["scene_name"]))
        ensure_scene_readable(scene)
        current = scene_data_version(scene)
    except (FileNotFoundError, RuntimeError, ValueError):
        return "scene_version"
    if not stored.get("frame_id") or not stored.get("scene_revision"):
        return "scene_version"
    if stored.get("frame_id") != current.get("frame_id") or stored.get("scene_revision") != current.get("scene_revision"):
        return "scene_version"
    return current


def _case_metadata(form: dict[str, Any], version: dict[str, Any]) -> dict[str, Any]:
    from experiments.scene_store import scene_directory, scenes_root

    scene = scene_directory(scenes_root(None), str(form["scene_name"]))
    metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
    metadata["data_version"] = version
    return metadata


def _solution_table(
    solutions_path: Path,
    pareto_path: Path,
    form: dict[str, Any],
) -> tuple[dict[str, dict[str, str]], dict[str, int], set[str]] | str:
    rows = _csv_rows(solutions_path)
    pareto_rows = _csv_rows(pareto_path)
    if rows is None or pareto_rows is None or not rows or not pareto_rows:
        return "missing_file"
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        pose_id = (row.get("run_id") or row.get("solution_id") or "").strip()
        if not pose_id or pose_id in by_id:
            return "incomplete_metrics"
        by_id[pose_id] = row
    pareto_ids: set[str] = set()
    for row in pareto_rows:
        pose_id = (row.get("run_id") or row.get("solution_id") or "").strip()
        if not pose_id or pose_id in pareto_ids or pose_id not in by_id:
            return "layer_unconfirmed"
        if _flag(by_id[pose_id].get("is_feasible", "")) is not True:
            return "layer_unconfirmed"
        pareto_ids.add(pose_id)
    layers = _layers(by_id, pareto_ids, form)
    if layers is None:
        return "layer_unconfirmed"
    return by_id, layers, pareto_ids


def _objective_fields(form: dict[str, Any]) -> tuple[str, ...]:
    # Same columns and order as frontend solutionLayers. Layer 1 still comes from the Pareto file.
    fields = list(_LAYER_FIELDS)
    if form.get("include_demand"):
        fields.append("demand_distance")
    if form.get("origin_x") is not None and form.get("origin_y") is not None:
        fields.append("road_haul_m")
    return tuple(fields)


def _layers(rows: dict[str, dict[str, str]], pareto_ids: set[str], form: dict[str, Any]) -> dict[str, int] | None:
    """Layer 1 is the source Pareto file. Layers 2 and 3 peel the remaining feasible rows."""

    fields = _objective_fields(form)
    feasible = []
    values: dict[str, list[float]] = {}
    for pose_id, row in rows.items():
        if _flag(row.get("is_feasible", "")) is not True:
            continue
        point = []
        for field in fields:
            number = _finite(row.get(field, ""))
            if number is None:
                return None
            point.append(number)
        feasible.append(pose_id)
        values[pose_id] = point
    if not pareto_ids or not pareto_ids <= set(feasible):
        return None
    layers = {pose_id: 1 for pose_id in pareto_ids}
    remaining = [pose_id for pose_id in feasible if pose_id not in layers]
    for layer in (2, 3):
        front = []
        for pose_id in remaining:
            right = values[pose_id]
            dominated = False
            for other in remaining:
                left = values[other]
                if all(item <= right[index] for index, item in enumerate(left)) and any(
                    item < right[index] for index, item in enumerate(left)
                ):
                    dominated = True
                    break
            if not dominated:
                front.append(pose_id)
        for pose_id in front:
            layers[pose_id] = layer
        front_ids = set(front)
        remaining = [pose_id for pose_id in remaining if pose_id not in front_ids]
    return layers


def _selected_rows(
    poses: list[dict[str, Any]],
    rows: dict[str, dict[str, str]],
    layers: dict[str, int],
    pareto_ids: set[str],
    form: dict[str, Any],
) -> list[dict[str, Any]] | str:
    expected = {pose_id for pose_id, layer in layers.items() if layer in {1, 2, 3}}
    requested = [str(pose.get("id") or "") for pose in poses]
    if len(requested) != len(set(requested)) or set(requested) != expected:
        return "pose_mismatch"
    selected = []
    origin = form.get("origin_x") is not None and form.get("origin_y") is not None
    for pose in poses:
        pose_id = str(pose["id"])
        source = rows[pose_id]
        if pose.get("manual") is True or pose.get("derived_from"):
            return "pose_mismatch"
        if int(pose.get("pareto_layer") or 0) != layers[pose_id]:
            return "layer_unconfirmed"
        for key in ("x", "y", "theta"):
            number = _finite(source.get(key, ""))
            if number is None or number != pose[key]:
                return "pose_mismatch"
        record = _metric_record(source, origin)
        if record is None:
            return "incomplete_metrics"
        record.update({
            "run_id": pose_id,
            "x": _finite(source["x"]),
            "y": _finite(source["y"]),
            "theta": _finite(source["theta"]),
            "id": pose_id,
            "manual": False,
            "pareto_layer": layers[pose_id],
            "derived_from": "",
            "is_pareto": pose_id in pareto_ids,
        })
        if record["is_pareto"] is not (layers[pose_id] == 1):
            return "layer_unconfirmed"
        selected.append(record)
    return selected


def _metric_record(source: dict[str, str], origin: bool) -> dict[str, Any] | None:
    record: dict[str, Any] = {}
    for field in _METRIC_FIELDS:
        number = _finite(source.get(field, ""))
        if number is None:
            return None
        record[field] = number
    haul = source.get("road_haul_m", "")
    haul_number = _finite(haul) if str(haul).strip() else None
    if origin and haul_number is None:
        return None
    if str(haul).strip() and haul_number is None:
        return None
    record["road_haul_m"] = "" if haul_number is None else haul_number
    feasible = _flag(source.get("is_feasible", ""))
    if feasible is None:
        return None
    record["is_feasible"] = feasible
    for field in ("weight_dem", "weight_road", "weight_demand", "raw_x", "raw_y", "raw_theta", "scalar",
                  "dem_hard_var", "dem_hard_range", "obstacle_hard_ratio"):
        text = source.get(field, "")
        number = _finite(text) if str(text).strip() else None
        record[field] = "" if number is None and not str(text).strip() else number
        if str(text).strip() and number is None:
            return None
    return record


def _publish(output_root: Path, case: dict[str, Any]) -> str:
    from experiments.output_writer import write_csv

    rows = case["rows"]
    pareto = [row for row in rows if row["is_pareto"]]
    summary = {
        "is_case": True, "algorithm": "workspace_snapshot", "display_name": case["name"],
        "scene_name": case["form"]["scene_name"], "source_experiment_id": case["source_experiment_id"],
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "n_runs": len(rows), "n_feasible": sum(bool(row["is_feasible"]) for row in rows),
        "n_pareto": len(pareto), "objective_names": case["objective_names"],
        "data_version": case["version"],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    experiment_id = f"saved-{uuid4().hex}"
    temporary = Path(tempfile.mkdtemp(prefix=".saving-", dir=output_root))
    try:
        write_csv(temporary / "solutions.csv", rows, _COLUMNS)
        write_csv(temporary / "pareto_solutions.csv", pareto, _COLUMNS)
        form = case["form"]
        documents = {
            "site_form_snapshot.json": form,
            "resolved_config.json": {"scene_name": form["scene_name"], "modeling": {
                "rect_w_m": form["rect_w_m"], "rect_h_m": form["rect_h_m"],
            }},
            "data_metadata.json": case["metadata"],
            "workspace_solutions.json": {"format": "workspace-solutions-v1", "solutions": rows},
            "run_summary.json": summary,
        }
        for filename, value in documents.items():
            (temporary / filename).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8",
            )
        temporary.rename(output_root / experiment_id)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return experiment_id


def _object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _csv_rows(path: Path) -> list[dict[str, str]] | None:
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))
    except OSError:
        return None


def _flag(value: str) -> bool | None:
    text = value.strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    return None


def _finite(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(float(left)) and float(left) == float(right)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_value(left[key], right[key]) for key in left)
    return left == right
