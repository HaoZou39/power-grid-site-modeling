"""Publish a road bundle with a recoverable backup and a reader guard."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from experiments.scene_files import (
    ROAD_PRODUCT_FILES, ROAD_REBUILD_MARKER, SCENE_METADATA, ensure_scene_readable, ensure_scene_writable, read_scene_json,
)


def detach_shared_file(path: Path) -> None:
    """Keep the bytes and permissions, but isolate a file shared with an experiment."""

    if not path.exists() or path.stat().st_nlink <= 1:
        return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(path, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_road_file(source: Path, destination: Path) -> None:
    detach_shared_file(destination)
    # Copy over the existing inode/file so Windows bind-mount ACLs remain readable by Docker.
    shutil.copyfile(source, destination)


def publish_road_bundle(scene: Path, staged: Path, backup_root: Path, product_id: str, *,
                        files: tuple[str, ...] = ROAD_PRODUCT_FILES, remove_files: tuple[str, ...] = ()) -> Path:
    """Publish while the caller holds scene_write_lock; failed recovery stays blocked."""

    ensure_scene_readable(scene)
    ensure_scene_writable(scene)
    from experiments.scene_version import write_scene_revision
    if SCENE_METADATA not in files:
        files = (*files, SCENE_METADATA)
    version_source = staged / SCENE_METADATA
    metadata = read_scene_json(version_source if version_source.is_file() else scene / SCENE_METADATA)
    write_scene_revision(staged, metadata)
    missing = [name for name in files if name not in remove_files and not (staged / name).is_file()]
    if missing:
        raise FileNotFoundError(f"road publication is missing candidate files: {', '.join(missing)}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_root.expanduser().resolve() / scene.name / f"{stamp}-{uuid4().hex[:8]}"
    backup.mkdir(parents=True, exist_ok=False)
    absent = [name for name in files if not (scene / name).is_file()]
    for name in files:
        if name not in absent:
            shutil.copy2(scene / name, backup / name)

    marker = scene / ROAD_REBUILD_MARKER
    with marker.open("x", encoding="utf-8") as stream:
        json.dump({"road_product_id": product_id, "backup": str(backup), "absent_files": absent, "files": list(files)}, stream)
    try:
        for name in files:
            if name in remove_files:
                (scene / name).unlink(missing_ok=True)
            else:
                _publish_road_file(staged / name, scene / name)
    except Exception as publication_error:
        try:
            for name in files:
                if name in absent:
                    (scene / name).unlink(missing_ok=True)
                else:
                    _publish_road_file(backup / name, scene / name)
        except Exception as rollback_error:
            raise RuntimeError(
                f"道路发布失败且回滚失败，场景保持不可读。备份目录：{backup}；保护标记：{marker}。"
                f"发布错误：{publication_error}；回滚错误：{rollback_error}"
            ) from rollback_error
        marker.unlink()
        raise
    else:
        marker.unlink()
    from experiments.import_retention import record_successful_backup
    record_successful_backup(backup, scene)
    return backup
