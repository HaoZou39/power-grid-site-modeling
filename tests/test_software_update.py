"""Password gate and restart guard. These tests do not pull or restart the live servers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from backend.app.software_update import UpdateRejected, begin_update, read_status, reset_for_tests

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_lockout(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_for_tests()
    monkeypatch.setenv("UPDATE_PASSWORD", "s3cret")


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_TERMINAL_PROMPT": "0",
    })
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True, text=True)


def _repo(tmp_path: Path, *, upstream: bool) -> Path:
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init")
    (repo / "README").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")
    if upstream:
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-u", "origin", "HEAD")
    return repo


def test_correct_password_spawns_without_putting_it_on_the_command(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=True)
    seen: list[tuple[Path, str]] = []

    def spawn(root: Path, update_id: str) -> None:
        seen.append((root, update_id))

    accepted = begin_update("s3cret", root=repo, spawn=spawn)
    assert seen == [(repo, accepted["id"])]
    assert "s3cret" not in accepted["id"]
    assert "s3cret" not in accepted["message"]
    assert "断开" in accepted["message"]


def test_missing_password_config_does_not_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPDATE_PASSWORD")
    repo = _repo(tmp_path, upstream=True)

    def spawn(_root: Path, _update_id: str) -> None:
        raise AssertionError("spawned")

    with pytest.raises(UpdateRejected) as caught:
        begin_update("s3cret", root=repo, spawn=spawn)
    assert caught.value.status == 503


def test_wrong_password_does_not_spawn(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=True)

    def spawn(_root: Path, _update_id: str) -> None:
        raise AssertionError("spawned")

    with pytest.raises(UpdateRejected) as caught:
        begin_update("nope", root=repo, spawn=spawn)
    assert caught.value.status == 401


def test_five_failures_lock_the_next_attempt(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=True)

    def spawn(_root: Path, _update_id: str) -> None:
        raise AssertionError("spawned")

    for _ in range(5):
        with pytest.raises(UpdateRejected) as caught:
            begin_update("nope", root=repo, spawn=spawn, now=1_000.0)
        assert caught.value.status == 401
    with pytest.raises(UpdateRejected) as locked:
        begin_update("s3cret", root=repo, spawn=spawn, now=1_010.0)
    assert locked.value.status == 429
    begin_update("s3cret", root=repo, spawn=lambda _root, _update_id: None, now=1_061.0)


def test_dirty_worktree_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=True)
    (repo / "local.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(UpdateRejected) as caught:
        begin_update("s3cret", root=repo, spawn=lambda _root, _update_id: None)
    assert caught.value.status == 409
    assert caught.value.code == "update_dirty"


def test_missing_upstream_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=False)
    with pytest.raises(UpdateRejected) as caught:
        begin_update("s3cret", root=repo, spawn=lambda _root, _update_id: None)
    assert caught.value.code == "update_no_upstream"


def test_a_held_lock_rejects_a_second_update(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=True)
    lock = repo / "outputs" / "dev-servers" / "update.lock"
    lock.parent.mkdir(parents=True)
    ready = tmp_path / "ready"
    holder = subprocess.Popen(
        ["bash", "-c", 'exec 9>"$1"; flock 9; echo ready > "$2"; sleep 30', "bash", str(lock), str(ready)],
        start_new_session=True,
    )
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not ready.exists():
            time.sleep(0.05)
        assert ready.exists()
        with pytest.raises(UpdateRejected) as caught:
            begin_update("s3cret", root=repo, spawn=lambda _root, _update_id: None)
        assert caught.value.status == 409
        assert caught.value.code == "update_busy"
    finally:
        holder.send_signal(signal.SIGTERM)
        holder.wait(timeout=5)


def test_status_hides_the_password_and_reports_a_finished_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=False)
    status_path = repo / "outputs" / "dev-servers" / "update-status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(
        '{"id":"run-1","phase":"rolled_back","before":"abc","commit":"abc","message":"已退回"}',
        encoding="utf-8",
    )
    status = read_status(repo)
    assert status["configured"] is True
    assert status["updating"] is False
    assert status["result"] == "rolled_back"
    assert status["id"] == "run-1"
    assert "s3cret" not in str(status)


def test_status_message_with_quotes_stays_readable(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=False)
    message = 'pid 1 "python" a\\b'
    log_dir = repo / "outputs" / "dev-servers"
    subprocess.run(
        ["bash", "-c", 'source "$1"; ROOT="$2"; LOG_DIR="$3"; STATUS_FILE="$3/update-status.json"; UPDATE_ID=run-2 write_status failed "$4"',
         "bash", str(ROOT / "restart.sh"), str(repo), str(log_dir), message],
        check=True,
    )
    status = read_status(repo)
    assert (status["id"], status["result"], status["message"]) == ("run-2", "failed", message)


def test_started_servers_do_not_keep_the_update_lock(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream=False)
    log_dir = repo / "outputs" / "dev-servers"
    started = subprocess.run(
        ["bash", "-c", 'source "$1"; LOG_DIR="$2"; hold_lock; detach "$2/server.log" sleep 30; echo $!',
         "bash", str(ROOT / "restart.sh"), str(log_dir)],
        check=True, capture_output=True, text=True,
    )
    server = int(started.stdout.strip())
    try:
        assert read_status(repo)["updating"] is False
    finally:
        os.kill(server, signal.SIGTERM)


def test_restart_kill_tree_skips_its_own_process(tmp_path: Path) -> None:
    marker = tmp_path / "alive"
    parent = textwrap.dedent(
        """
        import os, subprocess, sys, time
        marker, script = sys.argv[1], sys.argv[2]
        subprocess.Popen(
            ["bash", "-c", 'source "$1"; kill_tree "$2"; echo alive > "$3"', "bash", script, str(os.getpid()), marker],
            start_new_session=True,
        )
        time.sleep(5)
        sys.exit(0)
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", parent, str(marker), str(ROOT / "restart.sh")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == -signal.SIGTERM, proc.stderr
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.read_text(encoding="utf-8").strip() == "alive"
