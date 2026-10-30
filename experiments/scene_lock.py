"""A kernel-owned scene lock, shared by local threads, API and worker processes."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class CoordinateSceneError(ValueError):
    """A scene request conflicts with the published data contract."""


class SceneBusyError(CoordinateSceneError):
    """Another thread or process holds the lock."""


_HELD = threading.local()


_RETRY_SECONDS = 0.2


def _acquire(handle, path: Path, blocking: bool) -> None:
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
        raise SceneBusyError(f"已有任务正在写入同一目录：{path.stem}") from exc


def _release(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def file_lock(path: Path, *, blocking: bool = False, timeout: float | None = None) -> Iterator[None]:
    """Exclusive lock. ``timeout`` retries for that many seconds.

    Windows' blocking mode gives up after about 10 s, so long waits use ``timeout``.
    """

    path = path.resolve()
    held = getattr(_HELD, "paths", None)
    if held is None or getattr(_HELD, "pid", None) != os.getpid():
        held = _HELD.paths = set()
        _HELD.pid = os.getpid()
    if path in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            try:
                _acquire(handle, path, blocking and deadline is None)
                break
            except SceneBusyError:
                if deadline is None or time.monotonic() >= deadline:
                    raise
                time.sleep(_RETRY_SECONDS)
        held.add(path)
        try:
            yield
        finally:
            held.remove(path)
            _release(handle)


@contextmanager
def scene_write_lock(
    site_id: str,
    root: Path,
    *,
    blocking: bool = False,
    timeout: float | None = None,
) -> Iterator[None]:
    if not site_id or site_id in {".", ".."} or "/" in site_id or "\\" in site_id:
        raise ValueError("scene lock requires a single scene name")
    with file_lock(Path(root) / ".locks" / f"{site_id}.lock", blocking=blocking, timeout=timeout):
        yield
