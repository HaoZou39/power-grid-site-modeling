"""Immutable, content-addressed copies of one public scene's optimization inputs.

The snapshot is a byte copy under the experiment output root, not a hard link
and not an experiment directory. ``snapshot_id`` is the SHA-256 of the canonical
identity below. That identity excludes ``snapshot_id``, timestamps, absolute
paths and staging directory names. ``READY`` and ``manifest.json`` are not inputs.

Lock order is the scene write lock, then ``base-snapshots/.locks/{snapshot_id}.lock``.
Callers must not acquire the scene lock while holding a snapshot lock.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from experiments.protected_farmland import MASK_NAME as FARMLAND_MASK, META_NAME as FARMLAND_METADATA
from experiments.scene_lock import SceneBusyError, file_lock, scene_write_lock
from experiments.scene_store import (
    SCENE_ARRAYS,
    SCENE_METADATA,
    ensure_scene_readable,
    missing_scene_files,
    scene_directory,
    scene_frame_info,
    scenes_root,
)
from experiments.scene_version import scene_data_version

SCHEMA_VERSION = 1
REQUIRED_FILES = (*SCENE_ARRAYS, SCENE_METADATA)
OPTIONAL_FILES = (FARMLAND_MASK, FARMLAND_METADATA)
ALLOWED_FILES = set(REQUIRED_FILES) | set(OPTIONAL_FILES)
GRID_ARRAYS = ("dem_1m.npy", "landuse_1m.npy", "obstacle_mask_1m.npy", "road_voronoi_1m.npy")
_CHUNK = 1024 * 1024


class SnapshotError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedSnapshot:
    snapshot_id: str
    manifest: dict
    snapshot_path: Path
    reused: bool


def snapshot_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    override = os.environ.get("BASE_SNAPSHOT_ROOT")
    if override:
        return Path(override)
    return Path(os.environ.get("EXPERIMENT_OUTPUT_ROOT", "outputs")) / "base-snapshots"


def prepare_base_snapshot(
    scene_id: str,
    *,
    snapshot_root: str | Path | None = None,
    scene_root: str | Path | None = None,
    timeout: float | None = None,
) -> PreparedSnapshot:
    """Copy the current public scene and publish or reuse one verified snapshot."""

    try:
        scene = scene_directory(scenes_root(scene_root), scene_id)
    except ValueError as exc:
        raise SnapshotError("scene_invalid", str(exc)) from exc
    root = _controlled_root(snapshot_root)
    staging_root = _real_directory(root / ".staging")
    _real_directory(root / ".locks")
    staging = staging_root / uuid.uuid4().hex
    staging.mkdir()
    _reject_symlink(staging)
    cleanup = True
    try:
        with scene_write_lock(scene.name, scene.parent, blocking=timeout is None, timeout=timeout):
            copied = _copy_scene(scene, staging)
            snapshot_id = _identity_id(copied["identity"])
            lock_path = root / ".locks" / f"{snapshot_id}.lock"
            _reject_symlink(lock_path.parent)
            _reject_symlink(lock_path)
            with file_lock(lock_path, blocking=timeout is None, timeout=timeout):
                target = _snapshot_dir(root, snapshot_id)
                if target.exists() or target.is_symlink():
                    _require_verified(target, snapshot_id)
                    shutil.rmtree(staging)
                    cleanup = False
                    return PreparedSnapshot(snapshot_id, _read_manifest(target), target, True)
                manifest = {**copied["identity"], "snapshot_id": snapshot_id}
                _write_json(staging / "manifest.json", manifest)
                _write_text(staging / "READY", snapshot_id + "\n")
                for child in staging.iterdir():
                    os.chmod(child, 0o444)
                os.replace(staging, target)
                cleanup = False
                return PreparedSnapshot(snapshot_id, manifest, target, False)
    except SceneBusyError as exc:
        raise SnapshotError("scene_busy", str(exc)) from exc
    except OSError as exc:
        raise SnapshotError("snapshot_io", f"基础场景快照写入失败：{exc.strerror or exc}") from exc
    finally:
        if cleanup and staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def manifest_sha256(manifest: dict) -> str:
    return hashlib.sha256(_canonical(manifest).encode("utf-8")).hexdigest()


def register_ready_snapshot(repository, snapshot_id: str, *, snapshot_root: str | Path | None = None) -> bool:
    """Record a snapshot that already verifies. A database failure leaves the files in place."""

    manifest = verify_base_snapshot(snapshot_id, snapshot_root=snapshot_root)
    return repository.register_snapshot(manifest, manifest_sha256(manifest))


def verify_base_snapshot(snapshot_id: str, *, snapshot_root: str | Path | None = None) -> dict:
    """Read a published snapshot. Never falls back to the live public scene."""

    target = _snapshot_dir(_resolve_root(snapshot_root), snapshot_id)
    _require_verified(target, snapshot_id)
    return _read_manifest(target)


def snapshot_usage_report(
    *,
    snapshot_root: str | Path | None = None,
    references: dict[str, int] | None = None,
) -> dict:
    """Count READY candidates. This does not hash files and is not a trust decision."""

    root = _resolve_root(snapshot_root)
    ready: list[str] = []
    bytes_used = 0
    if root.is_dir() and not root.is_symlink():
        for child in root.iterdir():
            if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
                continue
            if not (child / "READY").is_file():
                continue
            ready.append(child.name)
            for path in child.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                bytes_used += path.stat().st_size
    staging = root / ".staging"
    staging_count = 0
    if staging.is_dir() and not staging.is_symlink():
        staging_count = sum(1 for child in staging.iterdir() if child.is_dir() and not child.is_symlink())
    reference_count = None if references is None else sum(references.values())
    unreferenced = None if references is None else sum(1 for item in ready if references.get(item, 0) == 0)
    return {
        "ready_candidate_count": len(ready),
        "ready_candidate_ids": sorted(ready),
        "integrity_checked": False,
        "total_bytes": bytes_used,
        "reference_count": reference_count,
        "unreferenced_candidate_count": unreferenced,
        "staging_count": staging_count,
    }


def _copy_scene(scene: Path, staging: Path) -> dict:
    if not scene.is_dir():
        raise SnapshotError("scene_not_found", f"公共场景不存在：{scene.name}")
    try:
        ensure_scene_readable(scene)
    except RuntimeError as exc:
        raise SnapshotError("scene_rebuilding", str(exc)) from exc
    missing = missing_scene_files(scene)
    if missing:
        raise SnapshotError("scene_not_ready", "公共场景尚未构建完成，缺少：" + ", ".join(missing))
    try:
        metadata = json.loads((scene / SCENE_METADATA).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotError("scene_not_ready", "公共场景元数据无法解析") from exc
    if not isinstance(metadata.get("scene_revision"), str) or not metadata["scene_revision"]:
        raise SnapshotError("scene_grid_invalid", "公共场景没有已发布的 scene_revision，不能用文件时间充当快照身份")
    frame = scene_frame_info(scene)
    if frame is None:
        raise SnapshotError("scene_grid_invalid", "公共场景缺少可校验的网格、坐标系或修订")
    version = scene_data_version(scene, metadata)
    # frame_id follows the published metadata numbers, matching planning workspaces.
    # scene_frame_info floats the transform before hashing, so the two digests can differ.
    if not version.get("frame_id") or version.get("scene_revision") != metadata["scene_revision"]:
        raise SnapshotError("scene_grid_invalid", "公共场景的 frame_id 或 scene_revision 无效")
    names = list(REQUIRED_FILES)
    farmland = scene / FARMLAND_MASK
    farmland_meta = scene / FARMLAND_METADATA
    registered = bool(metadata.get("protected_farmland")) or farmland_meta.exists()
    if registered and not farmland.is_file():
        raise SnapshotError("farmland_incomplete", "场景声明了永久基本农田，但掩膜文件不存在")
    if farmland.is_file():
        names.append(FARMLAND_MASK)
    if farmland_meta.is_file():
        names.append(FARMLAND_METADATA)
    files = []
    for name in names:
        source = scene / name
        size, digest = _copy_hashed(source, staging / name)
        dtype, shape = _array_header(staging / name) if name.endswith(".npy") else (None, None)
        files.append({
            "relative_path": name,
            "size_bytes": size,
            "sha256": digest,
            "dtype": dtype,
            "shape": shape,
        })
    files.sort(key=lambda item: item["relative_path"])
    grid_shape = [int(frame["height"]), int(frame["width"])]
    _check_grid(files, grid_shape)
    identity = {
        "schema_version": SCHEMA_VERSION,
        "base_scene_id": scene.name,
        "base_frame_id": version["frame_id"],
        "base_revision": version["scene_revision"],
        "source_scene_revision": version["scene_revision"],
        "source_crs": frame["crs"],
        "grid_shape": grid_shape,
        "grid_transform": [float(value) for value in frame["transform"]],
        "total_bytes": sum(item["size_bytes"] for item in files),
        "files": files,
    }
    return {"identity": identity}


def _check_grid(files: list[dict], grid_shape: list[int]) -> None:
    found = {item["relative_path"]: item for item in files}
    for name in (*GRID_ARRAYS, FARMLAND_MASK):
        item = found.get(name)
        if item is not None and item["shape"] != grid_shape:
            raise SnapshotError("snapshot_shape_mismatch", f"{name} 的网格与场景元数据不一致")
    segments, kinds = found.get("road_segments_local.npy"), found.get("road_segment_kind.npy")
    if segments and kinds and segments["shape"][:1] != kinds["shape"][:1]:
        raise SnapshotError("snapshot_shape_mismatch", "道路线段与道路类别数量不一致")


def _require_verified(directory: Path, snapshot_id: str) -> None:
    if directory.is_symlink():
        raise SnapshotError("snapshot_symlink", "快照目录不能是符号链接")
    if not directory.is_dir() or not (directory / "READY").is_file():
        raise SnapshotError("snapshot_not_ready", "快照目录不存在或尚未发布 READY")
    if not (directory / "manifest.json").is_file():
        raise SnapshotError("snapshot_incomplete", "READY 快照缺少 manifest.json")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise SnapshotError("snapshot_symlink", f"快照内含符号链接：{path.name}")
    manifest = _read_manifest(directory)
    if manifest.get("snapshot_id") != snapshot_id or _identity_id(_identity_of(manifest)) != snapshot_id:
        raise SnapshotError("snapshot_identity_mismatch", "manifest 与 snapshot_id 不一致")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError("snapshot_integrity", "快照格式版本不受支持")
    for key in ("base_scene_id", "base_frame_id", "base_revision", "source_scene_revision", "source_crs"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise SnapshotError("snapshot_integrity", f"快照缺少有效字段 {key}")
    if manifest["base_frame_id"] and manifest["base_revision"] != manifest["source_scene_revision"]:
        raise SnapshotError("snapshot_integrity", "基础修订与来源场景修订不一致")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SnapshotError("snapshot_integrity", "快照文件清单无效")
    declared = []
    for item in files:
        name = item.get("relative_path") if isinstance(item, dict) else None
        if not isinstance(name, str) or name not in ALLOWED_FILES or Path(name).name != name:
            raise SnapshotError("snapshot_integrity", "快照清单含非法路径")
        if name in declared:
            raise SnapshotError("snapshot_integrity", f"快照清单重复声明文件：{name}")
        declared.append(name)
    if any(name not in declared for name in REQUIRED_FILES):
        raise SnapshotError("snapshot_incomplete", "快照缺少优化必需的基础文件")
    if FARMLAND_METADATA in declared and FARMLAND_MASK not in declared:
        raise SnapshotError("farmland_incomplete", "快照登记了永久基本农田说明，但没有掩膜")
    metadata_file = directory / SCENE_METADATA
    if metadata_file.is_file() and not metadata_file.is_symlink():
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        if metadata.get("protected_farmland") and FARMLAND_MASK not in declared:
            raise SnapshotError("farmland_incomplete", "快照元数据声明了永久基本农田，但没有掩膜")
    expected = set(declared) | {"manifest.json", "READY"}
    actual = {path.name for path in directory.iterdir()}
    if actual != expected:
        raise SnapshotError("snapshot_integrity", "快照目录含未登记文件或缺少清单文件")
    ready = (directory / "READY").read_text(encoding="utf-8").strip()
    if ready != snapshot_id:
        raise SnapshotError("snapshot_not_ready", "READY 标记与 snapshot_id 不一致")
    total = 0
    for item in files:
        path = directory / item["relative_path"]
        if not path.is_file() or path.is_symlink():
            raise SnapshotError("snapshot_incomplete", f"快照文件缺失：{item['relative_path']}")
        size, digest = _hash_file(path)
        total += size
        if size != item.get("size_bytes") or digest != item.get("sha256"):
            raise SnapshotError("snapshot_hash_mismatch", f"快照文件哈希不一致：{item['relative_path']}")
        if str(item["relative_path"]).endswith(".npy"):
            dtype, shape = _array_header(path)
            if dtype != item.get("dtype") or shape != item.get("shape"):
                raise SnapshotError("snapshot_integrity", f"快照数组头与清单不一致：{item['relative_path']}")
    if total != manifest.get("total_bytes"):
        raise SnapshotError("snapshot_integrity", "快照总字节数与文件清单不一致")


def _identity_of(manifest: dict) -> dict:
    return {key: value for key, value in manifest.items() if key != "snapshot_id"}


def _identity_id(identity: dict) -> str:
    return hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise SnapshotError("snapshot_symlink", f"快照路径含符号链接：{path}")


def _assert_no_symlink(path: Path) -> Path:
    """Reject existing symlink components. A missing tail is allowed.

    The check happens before use. Replacing a path component afterwards is a
    filesystem race; this does not claim to close that race.
    """

    raw = Path(os.path.abspath(Path(path).expanduser()))
    current = Path(raw.anchor)
    for part in raw.parts[1:]:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return raw
        if stat.S_ISLNK(mode):
            raise SnapshotError("snapshot_symlink", f"快照路径含符号链接：{current}")
    return raw


def _real_directory(path: Path) -> Path:
    _reject_symlink(path)
    path.mkdir(exist_ok=True)
    _reject_symlink(path)
    if not path.is_dir():
        raise SnapshotError("snapshot_path_invalid", f"快照目录不是普通目录：{path}")
    return path


def _resolve_root(root: str | Path | None) -> Path:
    return _assert_no_symlink(snapshot_root(root))


def _controlled_root(root: str | Path | None) -> Path:
    path = _resolve_root(root)
    path.mkdir(parents=True, exist_ok=True)
    checked = _assert_no_symlink(path)
    _reject_symlink(checked)
    if not checked.is_dir():
        raise SnapshotError("snapshot_path_invalid", f"快照根目录不是普通目录：{checked}")
    return checked


def _snapshot_dir(root: Path, snapshot_id: str) -> Path:
    if len(snapshot_id) != 64 or any(character not in "0123456789abcdef" for character in snapshot_id):
        raise SnapshotError("snapshot_path_invalid", "snapshot_id 必须是 64 位小写十六进制")
    _reject_symlink(root)
    path = root / snapshot_id
    _reject_symlink(path)
    if path.parent != root:
        raise SnapshotError("snapshot_path_invalid", "snapshot_id 不能逃逸快照根目录")
    return path


def _copy_hashed(source: Path, target: Path) -> tuple[int, str]:
    if source.is_symlink() or not source.is_file():
        raise SnapshotError("snapshot_input_invalid", f"基础输入必须是普通文件：{source.name}")
    digest = hashlib.sha256()
    total = 0
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        while chunk := incoming.read(_CHUNK):
            outgoing.write(chunk)
            digest.update(chunk)
            total += len(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    return total, digest.hexdigest()


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as incoming:
        while chunk := incoming.read(_CHUNK):
            digest.update(chunk)
            total += len(chunk)
    return total, digest.hexdigest()


def _array_header(path: Path) -> tuple[str, list[int]]:
    with path.open("rb") as stream:
        if stream.read(6) != b"\x93NUMPY":
            raise SnapshotError("snapshot_integrity", f"不是 npy 文件：{path.name}")
        major = stream.read(2)[0]
        length = int.from_bytes(stream.read(2 if major == 1 else 4), "little")
        header = ast.literal_eval(stream.read(length).decode("latin1").strip())
    return str(header["descr"]), [int(value) for value in header["shape"]]


def _read_manifest(directory: Path) -> dict:
    path = directory / "manifest.json"
    if path.is_symlink() or not path.is_file():
        raise SnapshotError("snapshot_incomplete", "manifest.json 缺失或不是普通文件")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotError("snapshot_integrity", "manifest.json 无法解析") from exc


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, _canonical(payload) + "\n")


def _write_text(path: Path, text: str) -> None:
    with path.open("xb") as outgoing:
        outgoing.write(text.encode("utf-8"))
        outgoing.flush()
        os.fsync(outgoing.fileno())
