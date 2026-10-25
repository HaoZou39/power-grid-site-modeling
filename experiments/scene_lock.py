"""A kernel-owned scene lock, shared by local threads, API and worker processes."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class CoordinateSceneError(ValueError):
    """A scene request conflicts with the published data contract."""


_HELD = threading.local()


@contextmanager
def file_lock(path: Path, *, blocking: bool = False) -> Iterator[None]:
    path = path.resolve()
    held = getattr(_HELD, "paths", None)
    if held is None:
        held = _HELD.paths = set()
    if path in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except (BlockingIOError, PermissionError, OSError) as exc:
            if isinstance(exc, OSError) and exc.errno not in {11, 13, 35, 36}:
                raise
            raise CoordinateSceneError(f"已有任务正在写入同一目录：{path.stem}") from exc
        held.add(path)
        try:
            yield
        finally:
            held.remove(path)
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def scene_write_lock(site_id: str, root: Path, *, blocking: bool = False) -> Iterator[None]:
    if not site_id or site_id in {".", ".."} or "/" in site_id or "\\" in site_id:
        raise ValueError("scene lock requires a single scene name")
    with file_lock(Path(root) / ".locks" / f"{site_id}.lock", blocking=blocking):
        yield
