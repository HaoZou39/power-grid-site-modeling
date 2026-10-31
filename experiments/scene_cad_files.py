"""Store CAD scene attachments without interpreting drawing contents."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from experiments.scene_lock import scene_write_lock
from experiments.scene_store import ensure_scene_readable, ensure_scene_writable, missing_scene_files

CAD_DIRECTORY = "cad_files"
MAX_CAD_BYTES = 80 * 1024 * 1024


def _require_scene(scene: Path) -> None:
    if missing_scene_files(scene):
        raise FileNotFoundError("场景尚未准备，无法添加或读取 CAD 文件")
    ensure_scene_readable(scene)


def list_cad_files(scene: Path) -> list[dict]:
    with scene_write_lock(scene.name, scene.parent, blocking=True):
        _require_scene(scene)
        records = [json.loads(path.read_text(encoding="utf-8"))
                   for path in (scene / CAD_DIRECTORY).glob("*/metadata.json")
                   if not path.parent.name.startswith(".")]
        active_path = scene / "cad_landuse_import.json"
        active_id = json.loads(active_path.read_text(encoding="utf-8")).get("cad_id") if active_path.is_file() else None
        for record in records:
            record["active"] = record["id"] == active_id
    return sorted(records, key=lambda record: (record["uploaded_at"], record["id"]), reverse=True)


def add_cad_file(scene: Path, filename: str, payload: bytes) -> dict:
    source_name = Path(filename.replace("\\", "/")).name
    suffix = Path(source_name).suffix.lower()
    if suffix not in {".dwg", ".dxf"}:
        raise ValueError("CAD 文件必须为 DWG 或 DXF")
    if not payload:
        raise ValueError("CAD 文件不能为空")
    if len(payload) > MAX_CAD_BYTES:
        raise ValueError("CAD 文件不能超过 80 MiB")
    record = {"id": uuid4().hex, "source_name": source_name, "size_bytes": len(payload),
              "uploaded_at": datetime.now(timezone.utc).isoformat(), "active": False}
    with scene_write_lock(scene.name, scene.parent):
        _require_scene(scene)
        ensure_scene_writable(scene)
        directory = scene / CAD_DIRECTORY
        directory.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".upload-", dir=directory) as temporary:
            staged = Path(temporary) / record["id"]
            staged.mkdir()
            (staged / ("source" + suffix)).write_bytes(payload)
            (staged / "metadata.json").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
            staged.replace(directory / record["id"])
    return record
