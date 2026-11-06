"""Keep the two newest completed automatic results for one scene and problem type.

Manual cases, unidentified directories, and results still in use stay on disk.
Cleanup runs only after a result has been published. A cleanup error is logged
and does not change the optimization result.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Iterator

from experiments.scene_lock import file_lock

AUTO_RESULT_KEEP_COUNT = 2
_USE_FILE = ".auto-result-use.json"
_SITE_ALGORITHMS = {
    "guided_search",
    "nsga2",
    "cma_es",
    "multistart_adam",
    "vae_like_multihead",
    "partitioned_guided_search",
}
_MANUAL_ALGORITHMS = {"routing_workspace", "workspace_snapshot"}
logger = logging.getLogger("site-modeling.auto-retention")
_active_names: Callable[[], set[str]] | None = None


def set_active_experiment_provider(provider: Callable[[], set[str]] | None) -> None:
    """Names of experiments owned by queued, running, or cancelling jobs."""

    global _active_names
    _active_names = provider


def auto_marker_fields(scene_name: str | None, problem_type: str) -> dict[str, str]:
    """Classification fields stored in run_summary.json. The catalog hides them on read."""

    from experiments.ownership import owner_fields

    fields = {
        "result_origin": "auto",
        "problem_type": problem_type,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        **owner_fields(),
    }
    if _scene_name(scene_name):
        fields["scene_name"] = scene_name
    return fields


def snapshot_scene_name(directory: Path) -> str | None:
    return _scene_name(_object(directory / "site_form_snapshot.json").get("scene_name"))


def retain_published_auto_result(directory: Path, problem_type: str) -> None:
    """Prune one published result's group. Never raises into the optimization."""

    try:
        summary = _object(directory / "run_summary.json")
        scene_name = _scene_name(summary.get("scene_name")) or snapshot_scene_name(directory)
        owner_id = summary.get("owner_id")
        if scene_name is None or not isinstance(owner_id, str) or not owner_id:
            logger.error(
                "auto result retention skipped; published result %s has no scene or owner",
                directory.name,
            )
            return
        retain_auto_results(
            directory.parent,
            scene_name=scene_name,
            problem_type=problem_type,
            trigger_id=directory.name,
            owner_id=owner_id,
        )
    except Exception:
        logger.exception("auto result retention failed after %s", directory.name)


@contextmanager
def pin_auto_result(root: Path, experiment_id: str | None) -> Iterator[None]:
    """Hold a result while a manual case is saved from it."""

    if not experiment_id:
        yield
        return

    def add(state: dict[str, Any]) -> None:
        state["pins"] = _pin_ids(state) | {experiment_id}

    def remove(state: dict[str, Any]) -> None:
        state["pins"] = _pin_ids(state) - {experiment_id}

    _change_use(root, add)
    try:
        yield
    finally:
        try:
            _change_use(root, remove)
        except Exception:
            logger.exception("could not release auto result pin %s", experiment_id)


def note_displayed_auto_result(root: Path, experiment_id: str) -> None:
    """Remember the automatic result the map just opened. Failures stay on the read path."""

    try:
        inspected = _inspect(root, root / experiment_id)
        if inspected is None or inspected["scene"] is None or inspected["problem_type"] is None or not inspected.get("owner"):
            return
        key = _group_key(inspected["owner"], inspected["scene"], inspected["problem_type"])

        def change(state: dict[str, Any]) -> None:
            current = state.setdefault("current", {})
            if inspected["kind"] == "auto":
                current[key] = experiment_id
            elif inspected["kind"] == "manual":
                current.pop(key, None)

        _change_use(root, change)
    except Exception:
        logger.exception("could not record displayed auto result %s", experiment_id)


def retain_auto_results(
    root: str | Path,
    *,
    scene_name: str,
    owner_id: str,
    problem_type: str,
    trigger_id: str,
) -> dict[str, Any]:
    """Delete automatic results beyond the two newest for this owner, scene and type."""

    root = Path(root).expanduser().resolve()
    report: dict[str, Any] = {
        "trigger_id": trigger_id,
        "scene_id": scene_name,
        "problem_type": problem_type,
        "auto_count": 0,
        "kept": [],
        "deleted": [],
        "skipped": [],
        "deleted_count": 0,
        "freed_bytes": 0,
        "failures": [],
    }
    if problem_type not in {"site", "routing"} or _scene_name(scene_name) is None:
        report["failures"].append("invalid retention group")
        _log(report)
        return report
    if not root.is_dir():
        _log(report)
        return report
    try:
        protected = _protected_ids(root, trigger_id)
    except Exception as exc:
        report["failures"].append(f"could not read protection state: {exc}")
        _log(report)
        return report
    grouped: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".") or not path.is_dir():
            continue
        if path.is_symlink():
            report["skipped"].append({"id": path.name, "reason": "symlink"})
            continue
        summary_path = path / "run_summary.json"
        if not summary_path.is_file():
            continue
        try:
            inspected = _inspect(root, path)
        except Exception as exc:
            report["skipped"].append({"id": path.name, "reason": "inspect_failed", "detail": str(exc)})
            continue
        if inspected is None:
            report["skipped"].append({"id": path.name, "reason": "invalid_summary"})
            continue
        if inspected["kind"] == "manual":
            report["skipped"].append({"id": path.name, "reason": "manual_case"})
            continue
        if (
            inspected["kind"] != "auto"
            or inspected["scene"] != scene_name
            or inspected["problem_type"] != problem_type
            or inspected.get("owner") != owner_id
        ):
            if inspected["kind"] != "auto" or inspected["scene"] is None or inspected["problem_type"] is None or not inspected.get("owner"):
                report["skipped"].append({"id": path.name, "reason": inspected["reason"]})
            continue
        reason = _protection_reason(path.name, protected)
        grouped.append({**inspected, "protection": reason})
    grouped.sort(key=lambda item: (-item["completed"], item["id"]))
    report["auto_count"] = len(grouped)
    keep = {item["id"] for item in grouped[:AUTO_RESULT_KEEP_COUNT]}
    keep.update(item["id"] for item in grouped if item["protection"])
    report["kept"] = [item["id"] for item in grouped if item["id"] in keep]
    for item in grouped:
        if item["protection"] and item["id"] not in set(item["id"] for item in grouped[:AUTO_RESULT_KEEP_COUNT]):
            report["skipped"].append({"id": item["id"], "reason": item["protection"]})
    from backend.app.infrastructure.experiment_catalog import ExperimentCatalog

    catalog = ExperimentCatalog(root)
    freed = 0
    for item in grouped:
        if item["id"] in keep:
            continue
        try:
            still_protected = _protection_reason(item["id"], _protected_ids(root, trigger_id))
        except Exception as exc:
            report["failures"].append(f"could not recheck protection: {exc}")
            break
        if still_protected:
            report["skipped"].append({"id": item["id"], "reason": "became_protected"})
            report["kept"].append(item["id"])
            continue
        size = _directory_bytes(root / item["id"])
        try:
            if (root / item["id"]).is_symlink():
                raise OSError("refusing to delete a symlink")
            catalog.delete_experiment(item["id"])
        except Exception as exc:
            report["failures"].append(f"{item['id']}: {exc}")
            logger.exception("auto result retention could not delete %s", item["id"])
            continue
        report["deleted"].append(item["id"])
        if size is not None:
            freed += size
    report["deleted_count"] = len(report["deleted"])
    report["freed_bytes"] = freed
    report["kept"] = sorted(set(report["kept"]))
    _log(report)
    return report


def _protected_ids(root: Path, trigger_id: str) -> dict[str, str]:
    protected = {trigger_id: "trigger"}
    state = _read_use(root)
    for experiment_id in _pin_ids(state):
        protected.setdefault(experiment_id, "pinned")
    for experiment_id in state.get("current", {}).values():
        if isinstance(experiment_id, str) and experiment_id:
            protected.setdefault(experiment_id, "in_use")
    provider = _active_names
    if provider is not None:
        for name in provider():
            if isinstance(name, str) and name:
                protected.setdefault(name, "active_job")
    return protected


def _protection_reason(experiment_id: str, protected: dict[str, str]) -> str | None:
    return protected.get(experiment_id)


def _inspect(root: Path, path: Path) -> dict[str, Any] | None:
    if path.name.startswith(".") or not path.is_dir() or path.is_symlink():
        return None
    if path.resolve().parent != root.resolve():
        return {"id": path.name, "kind": "unknown", "scene": None, "problem_type": None,
                "reason": "outside_root", "completed": 0.0}
    summary_path = path / "run_summary.json"
    if not summary_path.is_file():
        return None
    summary = _object(summary_path)
    if not summary and summary_path.stat().st_size > 0 and summary_path.read_text(encoding="utf-8").strip() not in {"", "{}"}:
        try:
            json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    algorithm = _algorithm(path, summary)
    scene = _scene_name(summary.get("scene_name")) or snapshot_scene_name(path)
    problem_type = _problem_type(summary, algorithm)
    completed = _completed_at(summary_path, summary)
    owner = summary.get("owner_id") if isinstance(summary.get("owner_id"), str) and summary.get("owner_id") else None
    if _is_manual(path, summary, algorithm):
        return {"id": path.name, "kind": "manual", "scene": scene, "problem_type": problem_type,
                "owner": owner, "reason": "manual_case", "completed": completed}
    origin = summary.get("result_origin")
    reliable = origin == "auto" or (origin is None and _legacy_auto(algorithm, problem_type, scene, summary))
    if not reliable or scene is None or problem_type is None or owner is None:
        reason = (
            "unknown_scene" if scene is None
            else "unknown_type" if problem_type is None
            else "unknown_owner" if owner is None
            else "unknown_origin"
        )
        return {"id": path.name, "kind": "unknown", "scene": scene, "problem_type": problem_type,
                "owner": owner, "reason": reason, "completed": completed}
    return {"id": path.name, "kind": "auto", "scene": scene, "problem_type": problem_type,
            "owner": owner, "reason": "auto", "completed": completed}


def _is_manual(path: Path, summary: dict[str, Any], algorithm: str | None) -> bool:
    return summary.get("is_case") is True or (path / "workspace_solutions.json").is_file() or algorithm in _MANUAL_ALGORITHMS


def _legacy_auto(algorithm: str | None, problem_type: str | None, scene: str | None, summary: dict[str, Any]) -> bool:
    if scene is None or problem_type is None or summary.get("is_case") is True:
        return False
    if problem_type == "routing":
        return algorithm == "routing_nsga2" and _scene_name(summary.get("scene_name")) == scene
    return algorithm in _SITE_ALGORITHMS


def _problem_type(summary: dict[str, Any], algorithm: str | None) -> str | None:
    declared = summary.get("problem_type")
    if declared in {"site", "routing"}:
        return declared
    if declared not in (None, ""):
        return None
    if algorithm in {"routing_nsga2", "routing_workspace"}:
        return "routing"
    if algorithm in _SITE_ALGORITHMS or algorithm == "workspace_snapshot":
        return "site"
    return None


def _algorithm(path: Path, summary: dict[str, Any]) -> str | None:
    for key in ("algorithm", "algorithm_name"):
        value = summary.get(key)
        if isinstance(value, str) and value:
            return value
    config = _object(path / "resolved_config.json")
    for section in ("guided_search", "cma_es", "multistart_adam", "vae_like_multihead"):
        value = config.get(section, {}).get("algorithm_name") if isinstance(config.get(section), dict) else None
        if isinstance(value, str) and value:
            return value
    return None


def _completed_at(summary_path: Path, summary: dict[str, Any]) -> float:
    raw = summary.get("completed_at")
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
    return summary_path.stat().st_mtime


def _scene_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return None
    return name


def _object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _group_key(owner_id: str, scene_name: str, problem_type: str) -> str:
    return f"{owner_id}\t{scene_name}\t{problem_type}"


def _use_lock(root: Path) -> Path:
    return root / ".auto-result-use.lock"


def _read_use(root: Path) -> dict[str, Any]:
    path = root / _USE_FILE
    if not path.is_file():
        return {"current": {}, "pins": []}
    with file_lock(_use_lock(root), blocking=True, timeout=5):
        state = _object(path)
    state.setdefault("current", {})
    state.setdefault("pins", [])
    return state


def _pin_ids(state: dict[str, Any]) -> set[str]:
    pins = state.get("pins", [])
    if isinstance(pins, set):
        return {item for item in pins if isinstance(item, str)}
    if not isinstance(pins, list):
        return set()
    return {item for item in pins if isinstance(item, str)}


def _change_use(root: Path, change: Callable[[dict[str, Any]], None]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / _USE_FILE
    lock = _use_lock(root)
    empty = False
    with file_lock(lock, blocking=True, timeout=5):
        state = _object(path) if path.is_file() else {"current": {}, "pins": []}
        if not isinstance(state.get("current"), dict):
            state["current"] = {}
        change(state)
        current = state.get("current")
        if not isinstance(current, dict):
            current = {}
        current = {key: value for key, value in current.items() if isinstance(value, str)}
        pins = sorted(_pin_ids(state))
        empty = not current and not pins
        if empty:
            path.unlink(missing_ok=True)
        else:
            path.write_text(json.dumps({"current": current, "pins": pins}, ensure_ascii=False, indent=2), encoding="utf-8")
    if empty:
        lock.unlink(missing_ok=True)


def _directory_bytes(path: Path) -> int | None:
    total = 0
    try:
        for directory, dirnames, filenames in os.walk(path, followlinks=False):
            current = Path(directory)
            dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
            for name in filenames:
                file = current / name
                if file.is_symlink():
                    continue
                total += file.stat().st_size
    except OSError:
        return None
    return total


def _log(report: dict[str, Any]) -> None:
    logger.info("auto result retention %s", json.dumps(report, ensure_ascii=False, sort_keys=True))
