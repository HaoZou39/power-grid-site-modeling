"""Store CAD scene attachments without interpreting drawing contents."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unicodedata
from uuid import uuid4

from experiments.landuse_edits import CAD_METADATA_FILE
from experiments.scene_lock import scene_write_lock
from experiments.scene_store import ensure_scene_readable, ensure_scene_writable, missing_scene_files

CAD_DIRECTORY = "cad_files"
MAX_CAD_BYTES = 80 * 1024 * 1024
_ACTIVE_REPLACE = "该附件是当前场景的 CAD 土地类型来源，请先撤销 CAD 分类后再替换。"
_ACTIVE_DELETE = "该附件是当前场景的 CAD 土地类型来源，请先撤销 CAD 分类后再删除。"


class CadNameConflict(Exception):
    """Same display name already exists with different bytes. The caller must choose an id."""

    def __init__(self, matches: list[dict]):
        super().__init__("同名 CAD 内容不同，请确认要替换的附件")
        self.matches = matches


def _require_scene(scene: Path) -> None:
    if missing_scene_files(scene):
        raise FileNotFoundError("场景尚未准备，无法添加或读取 CAD 文件")
    ensure_scene_readable(scene)


def display_name(filename: str) -> str:
    # Basename only, so a client path cannot leave the attachment directory.
    name = unicodedata.normalize("NFC", Path(filename.replace("\\", "/")).name)
    if name in {"", ".", ".."}:
        raise ValueError("CAD 文件名无效")
    return name


def _name_key(name: str) -> str:
    return display_name(name).casefold()


def _validate_id(cad_id: str) -> str:
    if len(cad_id) != 32 or any(character not in "0123456789abcdef" for character in cad_id):
        raise ValueError("CAD 文件 id 无效")
    return cad_id


def _checked_upload(filename: str, payload: bytes) -> tuple[str, str, str]:
    source_name = display_name(filename)
    suffix = Path(source_name).suffix.lower()
    if suffix not in {".dwg", ".dxf"}:
        raise ValueError("CAD 文件必须为 DWG 或 DXF")
    if not payload:
        raise ValueError("CAD 文件不能为空")
    if len(payload) > MAX_CAD_BYTES:
        raise ValueError("CAD 文件不能超过 80 MiB")
    return source_name, suffix, hashlib.sha256(payload).hexdigest()


def _active_id(scene: Path) -> str | None:
    path = scene / CAD_METADATA_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("cad_id")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def _record_sha256(scene: Path, record: dict) -> str:
    # Attachments saved before content hashing have no digest in metadata.
    stored = record.get("sha256")
    if isinstance(stored, str) and len(stored) == 64 and all(character in "0123456789abcdef" for character in stored):
        return stored
    directory = scene / CAD_DIRECTORY / record["id"]
    return hashlib.sha256(_source_path(directory, record).read_bytes()).hexdigest()


def _present(scene: Path, record: dict, *, reused: bool = False) -> dict:
    presented = {key: record[key] for key in ("id", "source_name", "size_bytes", "uploaded_at")}
    presented["sha256"] = _record_sha256(scene, record)
    presented["active"] = record["id"] == _active_id(scene)
    if reused:
        presented["reused"] = True
    return presented


def _iter_records(scene: Path) -> list[dict]:
    directory = scene / CAD_DIRECTORY
    if not directory.is_dir():
        return []
    records = []
    for path in directory.glob("*/metadata.json"):
        if path.parent.name.startswith("."):
            continue
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def _source_path(directory: Path, record: dict) -> Path:
    path = directory / ("source" + Path(record["source_name"]).suffix.lower())
    if not path.is_file():
        raise FileNotFoundError("CAD 附件不存在")
    return path


def _attachment_dir(scene: Path, cad_id: str) -> Path:
    directory = scene / CAD_DIRECTORY / _validate_id(cad_id)
    if not (directory / "metadata.json").is_file():
        raise FileNotFoundError("CAD 附件不存在")
    return directory


def attachment_sha256(scene: Path, cad_id: str) -> str:
    directory = _attachment_dir(scene, cad_id)
    record = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    return _record_sha256(scene, record)


def assert_preview_current(scene: Path, summary: dict) -> None:
    """Reject a preview whose bytes no longer match the attachment it names."""
    directory = _attachment_dir(scene, summary["cad_id"])
    record = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    current = attachment_sha256(scene, summary["cad_id"])
    preview_hash = summary.get("sha256")
    if record.get("sha256") and preview_hash != current:
        raise ValueError("CAD 附件已变化，请重新生成预览")


def drop_cad_previews(scene: Path, cad_id: str) -> None:
    root = scene.parent / ".import-previews" / scene.name
    if not root.is_dir():
        return
    for directory in list(root.iterdir()):
        if not directory.is_dir() or directory.is_symlink():
            continue
        summary_path = directory / "summary.json"
        if not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if summary.get("cad_id") == cad_id:
            shutil.rmtree(directory)


def _reject_active(scene: Path, cad_id: str, message: str) -> None:
    if _active_id(scene) == cad_id:
        raise ValueError(message)


def _install(parent: Path, record: dict, suffix: str, payload: bytes) -> None:
    parent.mkdir(exist_ok=True)
    target = parent / record["id"]
    with tempfile.TemporaryDirectory(prefix=".upload-", dir=parent) as temporary:
        staged = Path(temporary) / record["id"]
        staged.mkdir()
        (staged / ("source" + suffix)).write_bytes(payload)
        (staged / "metadata.json").write_text(json.dumps(
            {key: record[key] for key in ("id", "source_name", "size_bytes", "uploaded_at", "sha256", "active")},
            ensure_ascii=False) + "\n", encoding="utf-8")
        backup = parent / f".backup-{record['id']}"
        if backup.exists():
            shutil.rmtree(backup)
        moved = False
        if target.exists():
            target.replace(backup)
            moved = True
        try:
            staged.replace(target)
        except Exception:
            if moved and not target.exists():
                backup.replace(target)
            raise
        if moved:
            shutil.rmtree(backup, ignore_errors=True)


def list_cad_files(scene: Path) -> list[dict]:
    with scene_write_lock(scene.name, scene.parent, blocking=True):
        _require_scene(scene)
        records = [_present(scene, record) for record in _iter_records(scene)]
    return sorted(records, key=lambda record: (record["uploaded_at"], record["id"]), reverse=True)


def add_cad_file(scene: Path, filename: str, payload: bytes) -> dict:
    source_name, suffix, digest = _checked_upload(filename, payload)
    key = _name_key(source_name)
    with scene_write_lock(scene.name, scene.parent):
        _require_scene(scene)
        ensure_scene_writable(scene)
        same_name = [record for record in _iter_records(scene) if _name_key(record["source_name"]) == key]
        identical = [record for record in same_name if _record_sha256(scene, record) == digest]
        if identical:
            chosen = max(identical, key=lambda record: (record["uploaded_at"], record["id"]))
            return _present(scene, chosen, reused=True)
        if same_name:
            raise CadNameConflict([_present(scene, record) for record in same_name])
        record = {"id": uuid4().hex, "source_name": source_name, "size_bytes": len(payload),
                  "uploaded_at": datetime.now(timezone.utc).isoformat(), "sha256": digest, "active": False}
        _install(scene / CAD_DIRECTORY, record, suffix, payload)
        return _present(scene, record)
    raise AssertionError("unreachable")


def replace_cad_file(scene: Path, cad_id: str, filename: str, payload: bytes) -> dict:
    source_name, suffix, digest = _checked_upload(filename, payload)
    cad_id = _validate_id(cad_id)
    with scene_write_lock(scene.name, scene.parent):
        _require_scene(scene)
        ensure_scene_writable(scene)
        directory = _attachment_dir(scene, cad_id)
        record = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        if _name_key(source_name) != _name_key(record["source_name"]):
            raise ValueError("只能替换同名 CAD 附件")
        current = _record_sha256(scene, record)
        if current == digest:
            return _present(scene, record, reused=True)
        _reject_active(scene, cad_id, _ACTIVE_REPLACE)
        updated = {**record, "source_name": record["source_name"], "size_bytes": len(payload),
                   "uploaded_at": datetime.now(timezone.utc).isoformat(), "sha256": digest, "active": False}
        _install(scene / CAD_DIRECTORY, updated, suffix, payload)
        drop_cad_previews(scene, cad_id)
        return _present(scene, updated)
    raise AssertionError("unreachable")


def delete_cad_file(scene: Path, cad_id: str) -> None:
    cad_id = _validate_id(cad_id)
    with scene_write_lock(scene.name, scene.parent):
        _require_scene(scene)
        ensure_scene_writable(scene)
        directory = _attachment_dir(scene, cad_id)
        _reject_active(scene, cad_id, _ACTIVE_DELETE)
        trash = directory.with_name(f".deleting-{cad_id}")
        if trash.exists():
            shutil.rmtree(trash)
        directory.replace(trash)
        try:
            shutil.rmtree(trash)
        except Exception:
            if not directory.exists():
                trash.replace(directory)
            raise
        drop_cad_previews(scene, cad_id)
