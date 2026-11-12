"""Real CUDA site and routing jobs through PostgreSQL, Redis, and one worker."""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import numpy as np
import pytest

from tests.integration.p2h2.api_process import REPO, ApiProcess, python_executable
from tests.integration.p2i.gpu_monitor import GpuSampler
from tests.integration.p2i.scene import SIZE, frame, routing_algorithm, routing_plan, site_plan, write_scene

PASSWORD = "user-pass-9f3c"
ADMIN_PASSWORD = "p2h2-admin-pass-9f3c"
SCENE = "scene-gpu"
SITE_RUN = {
    "device": "cuda:0", "evolution_backend": "tensor", "initialization": "uniform",
    "popsize": 64, "generations": 3, "evaluation_batch_size": 64, "seed": 7,
}
PRODUCTION_LOCK = REPO / "outputs/user-state/worker.lock"


def _required(name: str) -> str:
    if os.getenv("P2I_REQUIRED") != "1":
        pytest.skip("由 tests/integration/p2i/run.py 启动")
    value = os.getenv(name, "")
    if not value:
        pytest.fail(f"缺少 {name}")
    return value


def _login(client: httpx.Client, username: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def _wait(client: httpx.Client, job_id: str, statuses: set[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in statuses:
            return last
        time.sleep(0.5)
    raise AssertionError(last)


def _artifact(client: httpx.Client, experiment: dict, name: str) -> str:
    match = next(item for item in experiment["artifacts"] if item["name"] == name)
    response = client.get(match["url"])
    assert response.status_code == 200, response.text[:500]
    return response.text


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _seconds(job: dict) -> float:
    from datetime import datetime

    started = datetime.fromisoformat(job["created_at"])
    finished = datetime.fromisoformat(job["updated_at"])
    return (finished - started).total_seconds()


def _finite(value: str) -> float:
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise AssertionError(value)
    return number


class RealWorker:
    def __init__(self, root: Path, database_url: str, redis_url: str, gpu: str) -> None:
        self.root = root
        self.database_url = database_url
        self.redis_url = redis_url
        self.gpu = gpu
        self.probe = root / "probe"
        self.log = root / "worker.log"
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> dict:
        env = os.environ.copy()
        for name in ("DATABASE_URL", "REDIS_URL", "TEST_ACCOUNT_DATABASE_URL", "TEST_JOB_DATABASE_URL"):
            env.pop(name, None)
        env.update({
            "DATABASE_URL": self.database_url,
            "REDIS_URL": self.redis_url,
            "SCENE_ROOT": str(self.root / "scenes"),
            "EXPERIMENT_OUTPUT_ROOT": str(self.root / "outputs"),
            "BASE_SNAPSHOT_ROOT": str(self.root / "snapshots"),
            "AGENT_MEMORY_ROOT": str(self.root / "memory"),
            "FAVORITES_DB_PATH": str(self.root / "favorites.sqlite3"),
            "CUDA_VISIBLE_DEVICES": self.gpu,
            "P2I_PROBE_DIR": str(self.probe),
            "PYTHONUNBUFFERED": "1",
        })
        self.probe.mkdir(parents=True)
        log = open(self.log, "ab")
        self.process = subprocess.Popen(
            [python_executable(), "-m", "tests.integration.p2i.worker_main"],
            cwd=REPO, env=env, stdout=log, stderr=log,
        )
        deadline = time.monotonic() + 180
        probe_path = self.probe / "gpu_probe.json"
        while time.monotonic() < deadline:
            if self.process.poll() is not None and probe_path.is_file():
                break
            if probe_path.is_file() and (self.probe / "worker.pid").is_file():
                probe = json.loads(probe_path.read_text(encoding="utf-8"))
                if probe["available"] and probe["device_count"] == 1:
                    return probe
            time.sleep(0.2)
        raise RuntimeError(self.log.read_text(encoding="utf-8", errors="replace")[-3000:])

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def pid(self) -> int:
        pid = int((self.probe / "worker.pid").read_text(encoding="utf-8").strip())
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode()
        environ = Path(f"/proc/{pid}/environ").read_bytes().replace(b"\x00", b"\n").decode(errors="replace")
        if "tests.integration.p2i.worker_main" not in command or f"P2I_PROBE_DIR={self.probe}" not in environ:
            raise RuntimeError(f"拒绝操作非本次测试的进程 {pid}")
        return pid


def _frontend(tmp: Path, site_csv: Path, pareto: Path, routes: Path, summary: Path, grid: dict) -> None:
    compiled = tmp / "frontend-check"
    tsc = REPO / "frontend/node_modules/.bin/tsc"
    subprocess.run(
        [
            str(tsc), "--skipLibCheck", "--target", "ES2022", "--module", "nodenext",
            "--moduleResolution", "nodenext", "--strict", "--outDir", str(compiled),
            "--rootDir", str(REPO / "frontend/src"),
            str(REPO / "frontend/src/solution_record.ts"),
            str(REPO / "frontend/src/routing/routing_result.ts"),
            str(REPO / "frontend/src/map/site_frame.ts"),
        ],
        cwd=REPO / "frontend", check=True,
    )
    frame_path = tmp / "frame.json"
    frame_path.write_text(json.dumps(grid), encoding="utf-8")
    subprocess.run(
        [
            "node", str(REPO / "tests/integration/p2i/read_artifacts.mjs"),
            str(compiled), str(site_csv), str(pareto), str(routes), str(summary), str(frame_path), SCENE,
        ],
        check=True,
    )


def test_real_cuda_site_and_routing_stay_serial(tmp_path: Path) -> None:
    database_url = _required("P2I_DATABASE_URL")
    redis_url = _required("P2I_REDIS_URL")
    gpu_index = _required("P2I_GPU_INDEX")
    started = time.time()
    lock_before = PRODUCTION_LOCK.stat().st_mtime_ns if PRODUCTION_LOCK.is_file() else None
    scene = write_scene(tmp_path / "scenes", SCENE, "rev-gpu-1")
    original_corner = float(np.load(scene / "dem_1m.npy")[0, 0])
    api = ApiProcess(tmp_path, database_url, redis_url)
    worker = RealWorker(tmp_path, database_url, redis_url, gpu_index)
    sampler = GpuSampler(int(gpu_index))
    report: dict = {"gpu_index": gpu_index, "gpu_uuid": os.environ.get("P2I_GPU_UUID"), "started": started}
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    try:
        api.start(bootstrap=True)
        assert api.port not in {8010, 5176, 5432, 6379}
        with api.client() as admin, api.client() as alice, api.client() as bob:
            _login(admin, "p2h2-admin", ADMIN_PASSWORD)
            owner_a = admin.post("/api/v1/admin/users", json={"username": "user-a", "password": PASSWORD, "role": "user"}).json()["id"]
            owner_b = admin.post("/api/v1/admin/users", json={"username": "user-b", "password": PASSWORD, "role": "user"}).json()["id"]
            _login(alice, "user-a", PASSWORD)
            _login(bob, "user-b", PASSWORD)
            workspace_a = alice.post("/api/v1/workspaces", json={"base_scene_id": SCENE, "display_name": "选址"}).json()
            workspace_b = bob.post("/api/v1/workspaces", json={"base_scene_id": SCENE, "display_name": "选线"}).json()
            saved = alice.put(
                f"/api/v1/workspaces/{workspace_a['workspace_id']}/plan/site",
                json={"expected_workspace_revision": workspace_a["workspace_revision"], "site": site_plan(0)},
            )
            assert saved.status_code == 200, saved.text
            revision_v1 = saved.json()["workspace_revision"]
            submitted = alice.post(
                f"/api/v1/workspaces/{workspace_a['workspace_id']}/jobs",
                json={
                    "plugin_id": "site.guided_search", "expected_workspace_revision": revision_v1,
                    "experiment_name": "gpu-site", "overwrite_existing": False, "run_options": SITE_RUN,
                },
            )
            assert submitted.status_code == 202, submitted.text
            site_job = submitted.json()
            assert site_job["status"] == "queued"
            changed = alice.put(
                f"/api/v1/workspaces/{workspace_a['workspace_id']}/plan/site",
                json={"expected_workspace_revision": revision_v1, "site": site_plan(8)},
            )
            assert changed.status_code == 200 and changed.json()["workspace_revision"] != revision_v1
            dem = np.load(scene / "dem_1m.npy")
            dem[0, 0] = original_corner + 50
            np.save(scene / "dem_1m.npy", dem)
            probe = worker.start()
            report["probe"] = probe
            assert probe["cuda_visible_devices"] == gpu_index and probe["device_count"] == 1
            sampler.start(worker.pid())
            assert api.process is not None and worker.process is not None
            assert api.process.pid != worker.process.pid
            running = _wait(alice, site_job["job_id"], {"running", "failed", "succeeded"}, 180)
            assert running["status"] == "running", running
            route_saved = bob.put(
                f"/api/v1/workspaces/{workspace_b['workspace_id']}/plan/routing",
                json={"expected_workspace_revision": workspace_b["workspace_revision"], "routing": routing_plan()},
            )
            assert route_saved.status_code == 200, route_saved.text
            route_submit = bob.post(
                f"/api/v1/workspaces/{workspace_b['workspace_id']}/jobs",
                json={
                    "plugin_id": "routing.nsga2",
                    "expected_workspace_revision": route_saved.json()["workspace_revision"],
                    "experiment_name": "gpu-routing", "overwrite_existing": False,
                    "run_options": {"algorithm": routing_algorithm()},
                },
            )
            assert route_submit.status_code == 202, route_submit.text
            route_job = route_submit.json()
            saw_queued = False
            overlap = False
            site_done = None
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline and (site_done is None or site_done["status"] == "running"):
                current_site = alice.get(f"/api/v1/jobs/{site_job['job_id']}").json()
                current_route = bob.get(f"/api/v1/jobs/{route_job['job_id']}").json()
                if current_site["status"] == "running" and current_route["status"] == "queued":
                    saw_queued = True
                if current_site["status"] == "running" and current_route["status"] == "running":
                    overlap = True
                if current_site["status"] != "running":
                    site_done = current_site
                    break
                time.sleep(0.5)
            assert saw_queued and not overlap
            assert site_done is not None and site_done["status"] == "succeeded", site_done
            route_done = _wait(bob, route_job["job_id"], {"succeeded", "failed"}, 1200)
            assert route_done["status"] == "succeeded", route_done
            _check_site(alice, bob, tmp_path, site_done, owner_a, workspace_a, revision_v1, original_corner, report)
            _check_route(alice, bob, tmp_path, route_done, owner_b, workspace_b, report)
            _frontend(
                tmp_path,
                tmp_path / "outputs" / site_done["result"]["data"]["experiment_id"] / "solutions.csv",
                tmp_path / "outputs" / site_done["result"]["data"]["experiment_id"] / "pareto_solutions.csv",
                tmp_path / "outputs" / route_done["result"]["data"]["experiment_id"] / "routes.json",
                tmp_path / "outputs" / site_done["result"]["data"]["experiment_id"] / "run_summary.json",
                {"crs": frame().crs, "transform": list(frame().transform), "width": SIZE, "height": SIZE},
            )
            report["serial"] = True
            report["site_seconds"] = _seconds(site_done)
            report["routing_seconds"] = _seconds(route_done)
            log = worker.log.read_text(encoding="utf-8", errors="replace")
            assert log.index(site_job["job_id"]) < log.index(route_job["job_id"])
    finally:
        os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        if sampler.pid is not None:
            report["gpu_process"] = sampler.stop()
        worker.stop()
        api.stop()
        if lock_before is not None and PRODUCTION_LOCK.is_file():
            assert PRODUCTION_LOCK.stat().st_mtime_ns == lock_before
        report["finished"] = time.time()
        target = os.getenv("P2I_REPORT")
        if target:
            Path(target).write_text(json.dumps(report, ensure_ascii=False, default=str), encoding="utf-8")


def _check_site(alice, bob, root: Path, job: dict, owner: str, workspace: dict, revision: str, corner: float, report: dict) -> None:
    revisions = alice.get(f"/api/v1/workspaces/{workspace['workspace_id']}/revisions").json()
    frozen = next(item for item in revisions if item["revision_id"] == revision)
    assert job["workspace_revision"] == revision
    assert job["planning_content_hash"] == frozen["content_sha256"]
    assert alice.get(f"/api/v1/workspaces/{workspace['workspace_id']}").json()["workspace_revision"] != revision
    snapshot = root / "snapshots" / job["base_snapshot_id"] / "dem_1m.npy"
    assert float(np.load(snapshot)[0, 0]) == corner
    assert float(np.load(root / "scenes" / SCENE / "dem_1m.npy")[0, 0]) == corner + 50
    assert bob.get(f"/api/v1/jobs/{job['job_id']}").status_code == 404
    assert bob.get(f"/api/v1/jobs/{job['job_id']}/result").status_code == 404
    assert alice.get(f"/api/v1/jobs/{job['job_id']}/result").status_code == 200
    experiment_id = job["result"]["data"]["experiment_id"]
    assert bob.get(f"/api/v1/experiments/{experiment_id}").status_code == 404
    own = alice.get(f"/api/v1/experiments/{experiment_id}")
    assert own.status_code == 200 and str(root) not in own.text and "resolved_config_json" not in own.text
    summary = own.json()["summary"]
    assert summary["owner_id"] == owner and summary["workspace_id"] == workspace["workspace_id"]
    assert summary["workspace_revision"] == revision and summary["job_id"] == job["job_id"]
    assert summary["base_snapshot_id"] == job["base_snapshot_id"] and summary["base_scene_id"] == SCENE
    assert summary["n_feasible"] >= 1 and summary["no_feasible_solution"] is False
    body = own.json()
    assert bob.get(f"/api/v1/experiments/{experiment_id}/artifacts/{body['artifacts'][0]['id']}").status_code == 404
    normalization = json.loads(_artifact(alice, body, "normalization.json"))
    assert normalization["device"].startswith("cuda")
    assert normalization["evolution_backend"] == "tensor" and normalization["requested_evolution_backend"] == "tensor"
    assert normalization["backend_fallback_reason"] is None
    assert normalization["requested_initialization"] == "uniform"
    solutions = _rows(_artifact(alice, body, "solutions.csv"))
    pareto = _rows(_artifact(alice, body, "pareto_solutions.csv"))
    assert solutions and pareto
    feasible = [row for row in solutions if row["is_feasible"].lower() == "true"]
    assert feasible
    for row in feasible:
        assert 0 <= _finite(row["x"]) <= SIZE and 0 <= _finite(row["y"]) <= SIZE
        assert _finite(row["dem_soft"]) == _finite(row["dem_soft"])
    form = json.loads((root / "outputs" / experiment_id / "site_form_snapshot.json").read_text(encoding="utf-8"))
    assert form["rect_w_m"] == 77.0 and form["rect_h_m"] == 51.5 and form["road_setback_m"] == 0
    metadata = json.loads((root / "outputs" / experiment_id / "data_metadata.json").read_text(encoding="utf-8"))
    assert metadata["scene_dir"] == job["base_snapshot_id"]
    report["site"] = {
        "n_feasible": summary["n_feasible"], "n_pareto": summary["n_pareto"],
        "device": normalization["device"], "execution": normalization.get("execution_description"),
        "batch": normalization.get("evaluation_batch_size"),
    }


def _check_route(alice, bob, root: Path, job: dict, owner: str, workspace: dict, report: dict) -> None:
    assert job["config"]["algorithm"]["devices"] == ["cuda:0"]
    assert job["config"]["algorithm"]["evolution_backend"] == "tensor"
    assert job["config"]["algorithm"]["evaluation_backend"] == "tensor"
    assert alice.get(f"/api/v1/jobs/{job['job_id']}").status_code == 404
    experiment_id = job["result"]["data"]["experiment_id"]
    assert alice.get(f"/api/v1/experiments/{experiment_id}").status_code == 404
    own = bob.get(f"/api/v1/experiments/{experiment_id}")
    assert own.status_code == 200 and str(root) not in own.text and "resolved_config_json" not in own.text
    summary = own.json()["summary"]
    assert summary["owner_id"] == owner and summary["workspace_id"] == workspace["workspace_id"]
    assert summary["job_id"] == job["job_id"] and summary["base_snapshot_id"] == job["base_snapshot_id"]
    assert summary["n_feasible"] >= 1 and summary["execution"].startswith("CUDA")
    details = summary["execution_details"]
    assert details["devices"] == ["cuda:0"] and details["requested_devices"] == ["cuda:0"]
    memory = details["gpu_memory"]["cuda:0"]
    assert memory["peak_allocated_mib"] > 0
    body = own.json()
    routes = json.loads(_artifact(bob, body, "routes.json"))
    assert routes["scene_name"] == SCENE and routes["problem_type"] == "routing"
    feasible = [route for route in routes["routes"] if route["is_feasible"]]
    assert feasible
    for route in feasible:
        assert route["points"][0]["role"] == "start" and route["points"][-1]["role"] == "end"
        assert abs(route["points"][0]["x"] - 30) <= 1 and abs(route["points"][0]["y"] - 128) <= 1
        assert abs(route["points"][-1]["x"] - 220) <= 1 and abs(route["points"][-1]["y"] - 128) <= 1
        for point in route["points"]:
            assert 0 <= point["x"] <= SIZE and 0 <= point["y"] <= SIZE
        for span in route["spans"]:
            assert span["horizontal_m"] <= 250 + 1e-6
    copied = float(np.load(root / "outputs" / experiment_id / "scene_snapshot" / "dem_1m.npy")[0, 0])
    live = float(np.load(root / "scenes" / SCENE / "dem_1m.npy")[0, 0])
    assert float(np.load(root / "snapshots" / job["base_snapshot_id"] / "dem_1m.npy")[0, 0]) == copied == live
    report["routing"] = {
        "n_feasible": summary["n_feasible"], "execution": summary["execution"],
        "gpu_memory": memory, "devices": details["devices"],
    }
