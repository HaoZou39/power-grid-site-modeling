"""Real Redis plus a separate worker process. Skipped unless P2H2_REDIS_URL answers PING."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from tests.integration.p2h2.api_process import REPO, ApiProcess, python_executable
from tests.integration.p2h2.scenes import routing, site, write_scene

PASSWORD = "user-pass-9f3c"
ADMIN_PASSWORD = "p2h2-admin-pass-9f3c"
RUN = {"device": "cpu", "popsize": 4, "generations": 1}


def _redis_url() -> str:
    url = os.getenv("P2H2_REDIS_URL", "")
    parsed = urlparse(url)
    if parsed.scheme != "redis" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.skip("需要本机隔离的 Redis")
    import redis

    client = redis.Redis.from_url(url, socket_connect_timeout=1)
    try:
        if client.ping() is not True:
            pytest.skip("Redis 没有响应")
    except redis.RedisError:
        pytest.skip("Redis 没有响应")
    return url


def _database_url() -> str:
    url = os.getenv("P2H2_DATABASE_URL", "")
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path.lstrip("/") != "p2h2":
        pytest.skip("需要本机隔离的 PostgreSQL")
    return url


def _login(client: httpx.Client, username: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def _events(gate: Path) -> list[dict]:
    path = gate / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _wait_event(gate: Path, count: int, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(1 for row in _events(gate) if row["event"] == "enter") >= count:
            return
        time.sleep(0.05)
    raise AssertionError(_events(gate))


def _wait_status(client: httpx.Client, job_id: str, status: str, timeout: float = 90) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] == status:
            return last
        time.sleep(0.05)
    raise AssertionError(last)


class WorkerProcess:
    def __init__(self, root: Path, database_url: str, redis_url: str, gate: Path) -> None:
        self.root = root
        self.database_url = database_url
        self.redis_url = redis_url
        self.gate = gate
        self.process: subprocess.Popen[bytes] | None = None
        self.log = root / "worker.log"

    def start(self) -> None:
        env = os.environ.copy()
        env.update({
            "DATABASE_URL": self.database_url,
            "REDIS_URL": self.redis_url,
            "SCENE_ROOT": str(self.root / "scenes"),
            "EXPERIMENT_OUTPUT_ROOT": str(self.root / "outputs"),
            "BASE_SNAPSHOT_ROOT": str(self.root / "snapshots"),
            "AGENT_MEMORY_ROOT": str(self.root / "memory"),
            "P2H2_GATE_DIR": str(self.gate),
            "PYTHONUNBUFFERED": "1",
        })
        log = open(self.log, "ab")
        self.process = subprocess.Popen(
            [python_executable(), "-m", "tests.integration.p2h2.worker_main"],
            cwd=REPO, env=env, stdout=log, stderr=log,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(self.log.read_text(encoding="utf-8", errors="replace")[-2000:])
            if (self.gate / "worker.pid").is_file():
                return
            time.sleep(0.1)
        raise RuntimeError("Worker 在 60 秒内没有写下进程号")

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def pid(self) -> int:
        text = (self.gate / "worker.pid").read_text(encoding="utf-8").strip()
        pid = int(text)
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode()
        environ = Path(f"/proc/{pid}/environ").read_bytes().replace(b"\x00", b"\n").decode(errors="replace")
        if "tests.integration.p2h2.worker_main" not in command or f"P2H2_GATE_DIR={self.gate}" not in environ:
            raise RuntimeError(f"拒绝终止非本次测试的进程 {pid}")
        return pid


def _reset(url: str, redis_url: str) -> None:
    import psycopg
    import redis

    with psycopg.connect(url) as connection:
        connection.execute(
            """DROP TABLE IF EXISTS
            base_snapshot_references, base_scene_snapshots, planning_workspace_revisions,
            planning_workspaces, sessions, login_attempts, users, jobs"""
        )
    redis.Redis.from_url(redis_url).flushdb()


def _prepare(tmp_path: Path):
    url, redis_url = _database_url(), _redis_url()
    _reset(url, redis_url)
    write_scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    write_scene(tmp_path / "scenes", "scene-y", 230000, "rev-y1")
    gate = tmp_path / "gate"
    gate.mkdir()
    api = ApiProcess(tmp_path, url, redis_url)
    worker = WorkerProcess(tmp_path, url, redis_url, gate)
    return api, worker, gate


def test_redis_worker_runs_two_users_serially_and_keeps_results(tmp_path: Path) -> None:
    api, worker, gate = _prepare(tmp_path)
    (gate / "hold").write_text("1", encoding="utf-8")
    api.start(bootstrap=True)
    worker.start()
    try:
        assert api.process is not None and worker.process is not None
        assert api.process.pid != worker.process.pid
        with api.client() as admin, api.client() as alice, api.client() as bob:
            _login(admin, "p2h2-admin", ADMIN_PASSWORD)
            owner_a = admin.post("/api/v1/admin/users", json={"username": "user-a", "password": PASSWORD, "role": "user"}).json()["id"]
            admin.post("/api/v1/admin/users", json={"username": "user-b", "password": PASSWORD, "role": "user"})
            _login(alice, "user-a", PASSWORD)
            _login(bob, "user-b", PASSWORD)
            ax = alice.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "AX"}).json()
            bx = bob.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "BX"}).json()
            alice.put(f"/api/v1/workspaces/{ax['workspace_id']}/plan/site", json={"expected_workspace_revision": ax["workspace_revision"], "site": site(20, 1, 0.4, "blocked")})
            ax["workspace_revision"] = alice.get(f"/api/v1/workspaces/{ax['workspace_id']}").json()["workspace_revision"]
            bob.put(f"/api/v1/workspaces/{bx['workspace_id']}/plan/site", json={"expected_workspace_revision": bx["workspace_revision"], "site": site(28, 4, 2.0, "allowed")})
            bx["workspace_revision"] = bob.get(f"/api/v1/workspaces/{bx['workspace_id']}").json()["workspace_revision"]
            first = alice.post(f"/api/v1/workspaces/{ax['workspace_id']}/jobs", json={"plugin_id": "site.guided_search", "expected_workspace_revision": ax["workspace_revision"], "experiment_name": "serial-a", "overwrite_existing": False, "run_options": RUN})
            assert first.status_code == 202, first.text
            _wait_event(gate, 1)
            assert alice.get(f"/api/v1/jobs/{first.json()['job_id']}").json()["status"] == "running"
            second = bob.post(f"/api/v1/workspaces/{bx['workspace_id']}/jobs", json={"plugin_id": "site.guided_search", "expected_workspace_revision": bx["workspace_revision"], "experiment_name": "serial-b", "overwrite_existing": False, "run_options": RUN})
            assert second.status_code == 202, second.text
            assert bob.get(f"/api/v1/jobs/{second.json()['job_id']}").json()["status"] == "queued"
            assert sum(1 for row in _events(gate) if row["event"] == "enter") == 1
            (gate / "release").write_text("1", encoding="utf-8")
            done_a = _wait_status(alice, first.json()["job_id"], "succeeded")
            done_b = _wait_status(bob, second.json()["job_id"], "succeeded")
            enters = [row["t"] for row in _events(gate) if row["event"] == "enter"]
            exits = [row["t"] for row in _events(gate) if row["event"] == "exit"]
            assert len(enters) == 2 and exits[0] <= enters[1]
            assert bob.get(f"/api/v1/jobs/{done_a['job_id']}").status_code == 404
            assert bob.get(f"/api/v1/jobs/{done_a['job_id']}/result").status_code == 404
            assert alice.get(f"/api/v1/jobs/{done_a['job_id']}/result").status_code == 200
            assert alice.get(f"/api/v1/experiments/{done_b['result']['data']['experiment_id']}").status_code == 404
            own = alice.get(f"/api/v1/experiments/{done_a['result']['data']['experiment_id']}")
            assert own.status_code == 200 and str(tmp_path) not in own.text
            assert "resolved_config_json" not in own.text
            summary = own.json()["summary"]
            assert summary["owner_id"] == owner_a and summary["workspace_id"] == ax["workspace_id"]
            assert summary["job_id"] == done_a["job_id"] and summary["base_snapshot_id"] == done_a["base_snapshot_id"]
            artifacts = own.json()["artifacts"]
            assert artifacts
            assert bob.get(f"/api/v1/experiments/{done_a['result']['data']['experiment_id']}/artifacts/{artifacts[0]['id']}").status_code == 404
    finally:
        worker.stop()
        api.stop()


def test_worker_process_crash_does_not_rerun_the_interrupted_job(tmp_path: Path) -> None:
    api, worker, gate = _prepare(tmp_path)
    (gate / "hold").write_text("1", encoding="utf-8")
    api.start(bootstrap=True)
    worker.start()
    try:
        with api.client() as admin, api.client() as alice, api.client() as bob:
            _login(admin, "p2h2-admin", ADMIN_PASSWORD)
            admin.post("/api/v1/admin/users", json={"username": "user-a", "password": PASSWORD, "role": "user"})
            admin.post("/api/v1/admin/users", json={"username": "user-b", "password": PASSWORD, "role": "user"})
            _login(alice, "user-a", PASSWORD)
            _login(bob, "user-b", PASSWORD)
            ax = alice.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "AX"}).json()
            bx = bob.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "BX"}).json()
            saved_a = alice.put(f"/api/v1/workspaces/{ax['workspace_id']}/plan/site", json={"expected_workspace_revision": ax["workspace_revision"], "site": site(20, 1, 0.4, "blocked")})
            saved_b = bob.put(f"/api/v1/workspaces/{bx['workspace_id']}/plan/site", json={"expected_workspace_revision": bx["workspace_revision"], "site": site(28, 4, 2.0, "allowed")})
            ax["workspace_revision"] = saved_a.json()["workspace_revision"]
            bx["workspace_revision"] = saved_b.json()["workspace_revision"]
            running = alice.post(f"/api/v1/workspaces/{ax['workspace_id']}/jobs", json={"plugin_id": "site.guided_search", "expected_workspace_revision": ax["workspace_revision"], "experiment_name": "crash-a", "overwrite_existing": False, "run_options": RUN}).json()
            _wait_event(gate, 1)
            queued = bob.post(f"/api/v1/workspaces/{bx['workspace_id']}/jobs", json={"plugin_id": "site.guided_search", "expected_workspace_revision": bx["workspace_revision"], "experiment_name": "crash-b", "overwrite_existing": False, "run_options": RUN}).json()
            os.kill(worker.pid(), signal.SIGKILL)
            worker.process.wait(timeout=10)
            worker.process = None
            (gate / "worker.pid").unlink()
            (gate / "release").write_text("1", encoding="utf-8")
            worker.start()
            failed = _wait_status(alice, running["job_id"], "failed")
            assert "Worker 已中断" in failed["error"]["message"] and "未自动重跑" in failed["error"]["message"]
            assert _wait_status(bob, queued["job_id"], "succeeded")["status"] == "succeeded"
            assert alice.get(f"/api/v1/jobs/{running['job_id']}").json()["status"] == "failed"
            assert sum(1 for row in _events(gate) if row["event"] == "enter" and row["marker"] == "site") == 2
    finally:
        worker.stop()
        api.stop()


def test_duplicate_redis_message_does_not_run_twice(tmp_path: Path) -> None:
    api, worker, gate = _prepare(tmp_path)
    api.start(bootstrap=True)
    worker.start()
    try:
        with api.client() as admin, api.client() as alice:
            _login(admin, "p2h2-admin", ADMIN_PASSWORD)
            admin.post("/api/v1/admin/users", json={"username": "user-a", "password": PASSWORD, "role": "user"})
            _login(alice, "user-a", PASSWORD)
            workspace = alice.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "AX"}).json()
            saved = alice.put(f"/api/v1/workspaces/{workspace['workspace_id']}/plan/site", json={"expected_workspace_revision": workspace["workspace_revision"], "site": site(20, 1, 0.4, "allowed")})
            created = alice.post(f"/api/v1/workspaces/{workspace['workspace_id']}/jobs", json={"plugin_id": "site.guided_search", "expected_workspace_revision": saved.json()["workspace_revision"], "experiment_name": "once", "overwrite_existing": False, "run_options": RUN})
            assert created.status_code == 202, created.text
            done = _wait_status(alice, created.json()["job_id"], "succeeded")
            import redis

            redis.Redis.from_url(_redis_url()).lpush("site-modeling:v0:jobs", json.dumps({"job_id": done["job_id"]}))
            time.sleep(1)
            assert sum(1 for row in _events(gate) if row["event"] == "enter") == 1
            assert alice.get(f"/api/v1/jobs/{done['job_id']}").json()["status"] == "succeeded"
    finally:
        worker.stop()
        api.stop()


def test_cancel_queued_and_running_jobs(tmp_path: Path) -> None:
    api, worker, gate = _prepare(tmp_path)
    (gate / "hold").write_text("1", encoding="utf-8")
    api.start(bootstrap=True)
    worker.start()
    try:
        with api.client() as admin, api.client() as alice, api.client() as bob:
            _login(admin, "p2h2-admin", ADMIN_PASSWORD)
            admin.post("/api/v1/admin/users", json={"username": "user-a", "password": PASSWORD, "role": "user"})
            admin.post("/api/v1/admin/users", json={"username": "user-b", "password": PASSWORD, "role": "user"})
            _login(alice, "user-a", PASSWORD)
            _login(bob, "user-b", PASSWORD)
            ax = alice.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "AX"}).json()
            bx = bob.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "BX"}).json()
            saved_a = alice.put(f"/api/v1/workspaces/{ax['workspace_id']}/plan/site", json={"expected_workspace_revision": ax["workspace_revision"], "site": site(20, 1, 0.4, "blocked")})
            saved_b = bob.put(f"/api/v1/workspaces/{bx['workspace_id']}/plan/site", json={"expected_workspace_revision": bx["workspace_revision"], "site": site(28, 4, 2.0, "allowed")})
            running = alice.post(f"/api/v1/workspaces/{ax['workspace_id']}/jobs", json={"plugin_id": "site.guided_search", "expected_workspace_revision": saved_a.json()["workspace_revision"], "experiment_name": "live", "overwrite_existing": False, "run_options": RUN}).json()
            _wait_event(gate, 1)
            queued = bob.post(f"/api/v1/workspaces/{bx['workspace_id']}/jobs", json={"plugin_id": "site.guided_search", "expected_workspace_revision": saved_b.json()["workspace_revision"], "experiment_name": "queued", "overwrite_existing": False, "run_options": RUN}).json()
            assert alice.post(f"/api/v1/jobs/{queued['job_id']}/cancel").status_code == 404
            cancelled = bob.post(f"/api/v1/jobs/{queued['job_id']}/cancel")
            assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
            stopping = alice.post(f"/api/v1/jobs/{running['job_id']}/cancel")
            assert stopping.json()["status"] == "cancelling"
            assert _wait_status(alice, running["job_id"], "cancelled")["status"] == "cancelled"
            (gate / "release").write_text("1", encoding="utf-8")
            assert bob.get(f"/api/v1/jobs/{queued['job_id']}").json()["status"] == "cancelled"
            assert not (tmp_path / "outputs" / "queued").exists()
    finally:
        worker.stop()
        api.stop()


def test_cross_scene_jobs_keep_their_snapshot_identity(tmp_path: Path) -> None:
    api, worker, _gate = _prepare(tmp_path)
    api.start(bootstrap=True)
    worker.start()
    try:
        with api.client() as admin, api.client() as alice, api.client() as bob:
            _login(admin, "p2h2-admin", ADMIN_PASSWORD)
            admin.post("/api/v1/admin/users", json={"username": "user-a", "password": PASSWORD, "role": "user"})
            admin.post("/api/v1/admin/users", json={"username": "user-b", "password": PASSWORD, "role": "user"})
            _login(alice, "user-a", PASSWORD)
            _login(bob, "user-b", PASSWORD)
            ax = alice.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "AX"}).json()
            by = bob.post("/api/v1/workspaces", json={"base_scene_id": "scene-y", "display_name": "BY"}).json()
            saved = alice.put(f"/api/v1/workspaces/{ax['workspace_id']}/plan/site", json={"expected_workspace_revision": ax["workspace_revision"], "site": site(22, 1, 0.6, "blocked")})
            routed = bob.put(f"/api/v1/workspaces/{by['workspace_id']}/plan/routing", json={"expected_workspace_revision": by["workspace_revision"], "routing": routing(230000, [1, 2], [6, 3], "40")})
            job_a = alice.post(f"/api/v1/workspaces/{ax['workspace_id']}/jobs", json={"plugin_id": "site.guided_search", "expected_workspace_revision": saved.json()["workspace_revision"], "experiment_name": "cross-site", "overwrite_existing": False, "run_options": RUN}).json()
            job_b = bob.post(f"/api/v1/workspaces/{by['workspace_id']}/jobs", json={"plugin_id": "routing.nsga2", "expected_workspace_revision": routed.json()["workspace_revision"], "experiment_name": "cross-route", "overwrite_existing": False, "run_options": {}}).json()
            assert job_a["base_scene_id"] == "scene-x" and job_b["base_scene_id"] == "scene-y"
            assert job_a["base_snapshot_id"] != job_b["base_snapshot_id"]
            assert job_a["base_frame_id"] != job_b["base_frame_id"]
            _wait_status(alice, job_a["job_id"], "succeeded")
            _wait_status(bob, job_b["job_id"], "succeeded")
    finally:
        worker.stop()
        api.stop()
