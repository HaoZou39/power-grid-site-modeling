"""Bound imported-data scratch files and verified successful scene backups."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import time

from experiments.scene_lock import CoordinateSceneError, file_lock

PREVIEW_TTL_SECONDS = 24 * 60 * 60
BACKUP_KEEP = 5
RECEIPT = "publication.json"


def _read_receipt(path: Path) -> dict:
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return record if isinstance(record, dict) else {}


@contextmanager
def preview_lock(scene: Path, token: str, *, blocking=False):
    with file_lock(scene.parent / ".locks" / "previews" / scene.name / (token + ".lock"), blocking=blocking):
        yield


def release_preview_payload(directory: Path) -> None:
    for path in directory.iterdir():
        if path.name == "summary.json":
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def prune_previews(scene: Path, *, now: float | None = None) -> list[str]:
    root = scene.parent / ".import-previews" / scene.name
    if not root.is_dir():
        return []
    removed = []
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        summary = directory / "summary.json"
        if not summary.is_file():
            continue
        try:
            with preview_lock(scene, directory.name):
                record = _read_receipt(summary)
                # Legacy receipts may be the only remaining source evidence; audit them first.
                if not record.get("created_at"):
                    continue
                try:
                    created = datetime.fromisoformat(record["created_at"]).timestamp()
                except (TypeError, ValueError):
                    continue
                if record.get("saved"):
                    release_preview_payload(directory)
                elif (time.time() if now is None else now) - created > PREVIEW_TTL_SECONDS:
                    shutil.rmtree(directory)
                    removed.append(directory.name)
        except CoordinateSceneError:
            continue
    return removed


def record_successful_backup(backup: Path, scene: Path) -> None:
    try:
        (backup / RECEIPT).write_text(json.dumps({"scene_id":scene.name, "status":"succeeded",
            "completed_at":datetime.now(timezone.utc).isoformat()}, indent=2)+"\n")
        prune_backups(backup.parent, scene)
    except OSError:
        logging.getLogger(__name__).exception("Scene was published; backup retention failed for %s", backup)


def audit_backups(root: Path, scene: Path) -> list[dict]:
    marker = scene / ".roads-rebuilding"
    referenced = json.loads(marker.read_text()).get("backup") if marker.is_file() else None
    entries = []
    if not root.is_dir():
        return entries
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        receipt = directory / RECEIPT
        record = _read_receipt(receipt)
        entries.append({"path":str(directory), "verified_success":record.get("status") == "succeeded"
            and record.get("scene_id") == scene.name, "completed_at":record.get("completed_at", ""),
            "protected":bool(record.get("protected")) or (directory/".protected").exists()
                or (referenced is not None and Path(referenced).resolve() == directory.resolve())})
    return entries


def prune_backups(root: Path, scene: Path) -> list[str]:
    eligible = [row for row in audit_backups(root, scene) if row["verified_success"] and not row["protected"]]
    eligible.sort(key=lambda row: (row["completed_at"], row["path"]), reverse=True)
    removed = []
    for row in eligible[BACKUP_KEEP:]:
        shutil.rmtree(row["path"])
        removed.append(row["path"])
    return removed
