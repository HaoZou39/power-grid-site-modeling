"""Password-gated fast-forward update.

The password stays in this process; `UPDATE_PASSWORD` is read from the environment,
which the app fills from the repo-root `.env` at start. The restart script runs in its
own session and skips itself when it stops the API, so the update survives the restart.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import fcntl

_FAILURES = 0
_LOCKOUT_UNTIL = 0.0
_LOCKOUT_AFTER = 5
_LOCKOUT_S = 60.0

Spawn = Callable[[Path, str], None]


class UpdateRejected(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


def reset_for_tests() -> None:
    global _FAILURES, _LOCKOUT_UNTIL
    _FAILURES = 0
    _LOCKOUT_UNTIL = 0.0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def update_configured() -> bool:
    return os.getenv("UPDATE_PASSWORD", "") != ""


def spawn_detached(root: Path, update_id: str) -> None:
    script = root / "restart.sh"
    if not os.access(script, os.X_OK):
        raise UpdateRejected(500, "update_script_missing", "找不到可执行的 restart.sh。")
    log_dir = root / "outputs" / "dev-servers"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "update.log", "ab") as log:
        subprocess.Popen(
            [str(script)],
            cwd=root,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "UPDATE_ID": update_id, "SOFTWARE_UPDATE_FROM_API": "1"},
        )


def update_in_progress(root: Path) -> bool:
    lock = root / "outputs" / "dev-servers" / "update.lock"
    if not lock.exists():
        return False
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def read_status(root: Path | None = None) -> dict[str, object]:
    root = root or repo_root()
    payload = _status_file(root)
    updating = update_in_progress(root)
    phase = str(payload.get("phase") or "")
    message = str(payload.get("message") or "")
    result: str | None = None
    if not updating:
        if phase in {"succeeded", "rolled_back", "failed"}:
            result = phase
        elif phase in {"pulling", "restarting"}:
            result = "failed"
            message = message or "更新中断。"
    head = _git(root, "rev-parse", "--short", "HEAD")
    return {
        "configured": update_configured(),
        "updating": updating,
        "id": str(payload.get("id") or ""),
        "result": result,
        "message": message,
        "commit": head.stdout.strip() if head.returncode == 0 else "",
    }


def begin_update(
    password: str,
    *,
    root: Path | None = None,
    spawn: Spawn = spawn_detached,
    now: float | None = None,
) -> dict[str, str]:
    verify_admin_password(password, purpose="update", now=now)
    root = root or repo_root()
    if update_in_progress(root):
        raise UpdateRejected(409, "update_busy", "已有更新在进行。")
    _ensure_fast_forward(root)
    update_id = uuid.uuid4().hex
    spawn(root, update_id)
    return {"id": update_id, "message": "即将更新，页面会断开。内存中的任务会被清空。"}


def verify_admin_password(
    password: str,
    *,
    purpose: str = "settings",
    now: float | None = None,
) -> None:
    """Verify UPDATE_PASSWORD with the same process-wide failure limiter."""

    global _FAILURES, _LOCKOUT_UNTIL
    prefix = "update" if purpose == "update" else "agent_settings"
    subject = "更新" if purpose == "update" else "管理员"
    clock = time.time() if now is None else now
    if clock < _LOCKOUT_UNTIL:
        raise UpdateRejected(429, f"{prefix}_locked", "密码错误次数过多，请稍后再试。")
    expected = os.getenv("UPDATE_PASSWORD", "")
    if expected == "":
        message = "这台机器还没设置更新密码。" if purpose == "update" else "这台机器还没配置管理员密码。"
        raise UpdateRejected(503, f"{prefix}_not_configured", message)
    if not _password_matches(password, expected):
        _FAILURES += 1
        if _FAILURES >= _LOCKOUT_AFTER:
            _LOCKOUT_UNTIL = clock + _LOCKOUT_S
            _FAILURES = 0
        raise UpdateRejected(401, f"{prefix}_password", f"{subject}密码不正确。")
    _FAILURES = 0


def _password_matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(given.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


def _ensure_fast_forward(root: Path) -> None:
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise UpdateRejected(409, "update_not_a_repo", "这里不是 git 仓库，无法拉取。")
    dirty = _git(root, "status", "--porcelain")
    if dirty.returncode != 0:
        raise UpdateRejected(409, "update_git_status", "无法读取工作区状态，没有更新。")
    if dirty.stdout.strip():
        raise UpdateRejected(409, "update_dirty", "工作区有未提交的修改，已拒绝更新。")
    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream.returncode != 0 or not upstream.stdout.strip():
        raise UpdateRejected(409, "update_no_upstream", "当前分支没有上游，无法拉取。")


def _status_file(root: Path) -> dict[str, object]:
    path = root / "outputs" / "dev-servers" / "update-status.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
