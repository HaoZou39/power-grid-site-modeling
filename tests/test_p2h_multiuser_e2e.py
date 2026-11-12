"""Two real sessions through the API, the in-process queue, and one local worker.

The optimizer is a CPU stand-in. Queueing, workspace binding, snapshots, and
result checks are the running application. This file does not start Redis,
PostgreSQL, or a GPU.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from algorithms.routing.types import RoutingResult
from backend.app.main import create_app
from modeling.routing.types import RoutingFrame
from tests.auth_flags import skip_auto_login

PASSWORD = "user-pass-9f3c"
ADMIN_PASSWORD = os.environ["BOOTSTRAP_ADMIN_PASSWORD"]
RUN = {"device": "cpu", "popsize": 4, "generations": 1}


class ExecutionLog:
    """Counts optimizer entries so a single worker cannot hide an overlap."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.entries = 0
        self.release = threading.Event()
        self.seen: list[np.ndarray] = []
        self.spans: list[tuple[float, float]] = []

    def hold(self, problem, reporter, result):
        started = time.monotonic()
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.entries += 1
        try:
            while not self.release.is_set():
                if reporter is not None:
                    reporter(0.5, "search", "p2h-hold")
                if self.release.wait(0.05):
                    break
            self.seen.append(np.array(problem.landuse).copy())
            return result
        finally:
            with self.lock:
                self.active -= 1
            self.spans.append((started, time.monotonic()))

    def wait_entries(self, count: int, timeout: float = 90) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.entries >= count and self.active >= 1:
                    return
            time.sleep(0.02)
        raise AssertionError(f"optimizer entries={self.entries} active={self.active}")


def _frame(origin_x: float) -> RoutingFrame:
    return RoutingFrame("EPSG:32651", (1, 0, origin_x, 0, -1, 3046000), 8, 8)


def _scene(root: Path, name: str, origin_x: float, revision: str) -> Path:
    scene = root / name
    scene.mkdir(parents=True, exist_ok=True)
    shape = (8, 8)
    frame = _frame(origin_x)
    arrays = {
        "dem_1m.npy": np.ones(shape, np.float32),
        "landuse_1m.npy": np.zeros(shape, np.uint8),
        "obstacle_mask_1m.npy": np.zeros(shape, np.uint8),
        "road_segments_local.npy": np.array([[0, 1, 6, 1]], np.float32),
        "road_segment_kind.npy": np.zeros(1, np.int8),
        "road_voronoi_1m.npy": np.zeros(shape, np.int64),
        "demand_points.npy": np.array([[1.0, 1.0]], np.float32),
        "protected_farmland_mask_1m.npy": np.zeros(shape, dtype=bool),
    }
    for filename, array in arrays.items():
        np.save(scene / filename, array)
    (scene / "data_metadata.json").write_text(json.dumps({
        "scene_revision": revision,
        "dem": {"reference_crs": frame.crs, "target_transform": list(frame.transform), "shape": [8, 8]},
    }), encoding="utf-8")
    (scene / "scene.json").write_text("{}\n", encoding="utf-8")
    return scene


def _republish(scene: Path, landuse: int, revision: str) -> None:
    np.save(scene / "landuse_1m.npy", np.full((8, 8), landuse, np.uint8))
    metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
    metadata["scene_revision"] = revision
    (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def _app(tmp_path: Path):
    database = f"sqlite:///{tmp_path / 'app.sqlite3'}"
    os.environ["DATABASE_URL"] = database
    os.environ["REDIS_URL"] = ""
    os.environ["SCENE_ROOT"] = str(tmp_path / "scenes")
    os.environ["EXPERIMENT_OUTPUT_ROOT"] = str(tmp_path / "outputs")
    os.environ["BASE_SNAPSHOT_ROOT"] = str(tmp_path / "snapshots")
    os.environ["AGENT_MEMORY_ROOT"] = str(tmp_path / "memory")
    return create_app(database, "", experiment_root=tmp_path / "outputs", favorite_db_path=tmp_path / "favorites.sqlite3")


def _login(client: TestClient, username: str, password: str = PASSWORD) -> dict:
    client.cookies.clear()
    token = skip_auto_login.set(True)
    try:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    finally:
        skip_auto_login.reset(token)
    assert response.status_code == 200, response.text
    client.csrf_token = response.json()["csrf_token"]
    return response.json()


def _quiet(client: TestClient, method: str, url: str, **kwargs):
    token = skip_auto_login.set(True)
    try:
        return client.request(method, url, **kwargs)
    finally:
        skip_auto_login.reset(token)


def _user(admin: TestClient, username: str) -> str:
    response = admin.post("/api/v1/admin/users", json={"username": username, "password": PASSWORD, "role": "user"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _workspace(client: TestClient, scene_id: str, name: str) -> dict:
    response = client.post("/api/v1/workspaces", json={"base_scene_id": scene_id, "display_name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _site(width: float, setback: float, zone: float, policy: str) -> dict:
    return {
        "rect_w_m": width, "rect_h_m": 18, "field_policy": policy, "mountain_policy": "allowed",
        "field_cost": 0.5, "include_demand": False, "diagonal_access": True,
        "road_setback_m": setback, "water_setback_m": 0, "highway_setback_m": 0,
        "elevation_enabled": False, "elevation_draft": "",
        "exclusion_zones": [{"id": f"z{int(zone * 10)}", "points": [[zone, zone], [zone + 1, zone], [zone + 1, zone + 1]]}],
        "feasible_zones": [], "origin": {"x": zone, "y": 1.5},
    }


def _routing(frame: RoutingFrame, start: list[float], end: list[float], span: str) -> dict:
    start_wgs, end_wgs = frame.to_wgs84(start), frame.to_wgs84(end)
    return {
        "start": {"lng": f"{start_wgs[0]:.8f}", "lat": f"{start_wgs[1]:.8f}"},
        "end": {"lng": f"{end_wgs[0]:.8f}", "lat": f"{end_wgs[1]:.8f}"},
        "max_span_m": span, "tower_radius_m": "0.4", "max_turn_deg": "90",
        "road_setback_m": "0", "highway_setback_m": "0", "no_tower_zones": [], "no_cross_zones": [],
        "algorithm_overrides": {"popsize": 8, "max_generations": 1, "max_evaluations": 8, "reference_count": 1},
    }


def _save_site(client: TestClient, workspace: dict, site: dict) -> dict:
    response = client.put(
        f"/api/v1/workspaces/{workspace['workspace_id']}/plan/site",
        json={"expected_workspace_revision": workspace["workspace_revision"], "site": site},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    workspace["workspace_revision"] = saved["workspace_revision"]
    return saved


def _save_routing(client: TestClient, workspace: dict, routing: dict) -> dict:
    response = client.put(
        f"/api/v1/workspaces/{workspace['workspace_id']}/plan/routing",
        json={"expected_workspace_revision": workspace["workspace_revision"], "routing": routing},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    workspace["workspace_revision"] = saved["workspace_revision"]
    return saved


def _submit(client: TestClient, workspace: dict, plugin: str, name: str, options: dict | None = None):
    return client.post(
        f"/api/v1/workspaces/{workspace['workspace_id']}/jobs",
        json={
            "plugin_id": plugin,
            "expected_workspace_revision": workspace["workspace_revision"],
            "experiment_name": name,
            "overwrite_existing": False,
            "run_options": RUN if options is None else options,
        },
    )


def _wait(client: TestClient, job_id: str, status: str, timeout: float = 90) -> dict:
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


def _install_standins(monkeypatch: pytest.MonkeyPatch, box: dict[str, ExecutionLog]) -> None:
    def site_search(problem, *args, **_kwargs):
        reporter = next((arg for arg in args if callable(arg)), None)
        return box["log"].hold(problem, reporter, type("Result", (), {
            "solutions": [], "normalization": {}, "objective_names": ("dem_soft", "road_distance", "demand_distance"),
        })())

    def route_search(problem, _config, reporter):
        return box["log"].hold(problem, reporter, RoutingResult([], [], [], 0, 0, 0, 0, [], "stub", 0, 0, {"devices": ["cpu"]}))

    monkeypatch.setattr("algorithms.guided_search.search.run_guided_search", site_search)
    monkeypatch.setattr("algorithms.routing.search.routing_search", route_search)


def _summary(tmp_path: Path, experiment_id: str) -> dict:
    return json.loads((tmp_path / "outputs" / experiment_id / "run_summary.json").read_text(encoding="utf-8"))


def test_h01_independent_sessions_csrf_logout_and_disabled_account(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        user_a = _user(admin, "user-a")
        _user(admin, "user-b")
        alice, bob = TestClient(app), TestClient(app)
        _login(alice, "user-a")
        _login(bob, "user-b")
        assert alice.cookies.get("site_session") != bob.cookies.get("site_session")
        assert alice.get("/api/v1/auth/me").json()["user"]["id"] == user_a
        assert bob.get("/api/v1/auth/me").json()["user"]["username"] == "user-b"
        rejected = _quiet(bob, "POST", "/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "越权"}, headers={"X-CSRF-Token": alice.csrf_token})
        assert rejected.status_code == 403 and rejected.json()["detail"]["code"] == "csrf_failed"
        anonymous = _quiet(TestClient(app), "GET", "/api/v1/auth/me")
        assert anonymous.status_code == 401
        assert alice.post("/api/v1/auth/logout").status_code == 200
        assert _quiet(alice, "GET", "/api/v1/auth/me").status_code == 401
        assert bob.get("/api/v1/auth/me").status_code == 200
        _login(alice, "user-a")
        disabled = admin.patch(f"/api/v1/admin/users/{user_a}", json={"disabled": True})
        assert disabled.status_code == 200 and disabled.json()["disabled_at"]
        assert alice.get("/api/v1/auth/me").status_code == 401
        token = skip_auto_login.set(True)
        try:
            again = alice.post("/api/v1/auth/login", json={"username": "user-a", "password": PASSWORD})
        finally:
            skip_auto_login.reset(token)
        assert again.status_code == 401
        assert bob.get("/api/v1/auth/me").json()["user"]["username"] == "user-b"


def test_h02_h03_same_scene_and_cross_scene_plans_stay_separate(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    _scene(tmp_path / "scenes", "scene-y", 230000, "rev-y1")
    frame_x, frame_y = _frame(221000), _frame(230000)
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        _user(admin, "user-a")
        _user(admin, "user-b")
        alice, bob = TestClient(app), TestClient(app)
        _login(alice, "user-a")
        _login(bob, "user-b")
        ax = _workspace(alice, "scene-x", "AX1")
        ay = _workspace(alice, "scene-y", "AY1")
        bx = _workspace(bob, "scene-x", "BX1")
        by = _workspace(bob, "scene-y", "BY1")
        _save_site(alice, ax, _site(20, 1, 0.4, "blocked"))
        _save_site(bob, bx, _site(28, 4, 2.0, "allowed"))
        route_ax = _routing(frame_x, [1, 2], [6, 2], "30")
        route_ay = _routing(frame_y, [1, 3], [5, 4], "44")
        _save_routing(alice, ax, route_ax)
        _save_routing(alice, ay, route_ay)
        _save_routing(bob, bx, _routing(frame_x, [2, 2], [6, 3], "36"))
        _save_routing(bob, by, _routing(frame_y, [1, 1], [4, 5], "50"))
        revision_a = ax["workspace_revision"]
        revision_b = bx["workspace_revision"]
        plan_a = alice.get(f"/api/v1/workspaces/{ax['workspace_id']}/plan").json()["site"]
        plan_b = bob.get(f"/api/v1/workspaces/{bx['workspace_id']}/plan").json()["site"]
        assert plan_a["rect_w_m"] == 20 and plan_a["road_setback_m"] == 1 and plan_a["field_policy"] == "blocked"
        assert plan_a["field_cost"] == 0.5 and plan_a["include_demand"] is False
        assert plan_b["rect_w_m"] == 28 and plan_b["road_setback_m"] == 4 and plan_b["exclusion_zones"] != plan_a["exclusion_zones"]
        for method, url in (
            ("GET", f"/api/v1/workspaces/{ax['workspace_id']}"),
            ("GET", f"/api/v1/workspaces/{ax['workspace_id']}/plan"),
            ("DELETE", f"/api/v1/workspaces/{ax['workspace_id']}"),
        ):
            foreign = bob.request(method, url)
            assert foreign.status_code == 404, foreign.text
        stolen = bob.put(
            f"/api/v1/workspaces/{ax['workspace_id']}/plan/site",
            json={"expected_workspace_revision": revision_a, "site": _site(99, 9, 3, "allowed")},
        )
        assert stolen.status_code == 404
        assert alice.get(f"/api/v1/workspaces/{bx['workspace_id']}").status_code == 404
        _save_site(alice, ax, _site(21, 1, 0.4, "blocked"))
        assert bob.get(f"/api/v1/workspaces/{bx['workspace_id']}").json()["workspace_revision"] == revision_b
        _save_site(bob, bx, _site(29, 4, 2.0, "allowed"))
        assert alice.get(f"/api/v1/workspaces/{ax['workspace_id']}").json()["workspace_revision"] != revision_b
        listed_x = {item["workspace_id"] for item in alice.get("/api/v1/workspaces", params={"base_scene_id": "scene-x"}).json()}
        listed_y = {item["workspace_id"] for item in alice.get("/api/v1/workspaces", params={"base_scene_id": "scene-y"}).json()}
        assert listed_x == {ax["workspace_id"]} and listed_y == {ay["workspace_id"]}
        ay_route = alice.get(f"/api/v1/workspaces/{ay['workspace_id']}/plan").json()["routing"]
        ax_route = alice.get(f"/api/v1/workspaces/{ax['workspace_id']}/plan").json()["routing"]
        assert ay_route["start"] == route_ay["start"] and ay_route["max_span_m"] == "44"
        assert ax_route["start"] == route_ax["start"] and ax_route["start"] != ay_route["start"]
        assert len(alice.get(f"/api/v1/workspaces/{ax['workspace_id']}/revisions").json()) >= 2
        assert len(alice.get(f"/api/v1/workspaces/{ay['workspace_id']}/revisions").json()) >= 1


def test_h04_h05_same_scene_and_cross_scene_submissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    _scene(tmp_path / "scenes", "scene-y", 230000, "rev-y1")
    box = {"log": ExecutionLog()}
    box["log"].release.set()
    _install_standins(monkeypatch, box)
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        _user(admin, "user-a")
        _user(admin, "user-b")

        def prepare(username: str, scene_id: str, name: str, width: float):
            client = TestClient(app)
            _login(client, username)
            workspace = _workspace(client, scene_id, name)
            _save_site(client, workspace, _site(width, width / 10, 0.5, "allowed"))
            return client, workspace

        left = prepare("user-a", "scene-x", "AX1", 20)
        right = prepare("user-b", "scene-x", "BX1", 28)

        def send(pair: tuple[TestClient, dict], name: str) -> dict:
            response = _submit(pair[0], pair[1], "site.guided_search", name)
            assert response.status_code == 202, response.text
            return response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            job_a, job_b = list(pool.map(send, (left, right), ("same-a", "same-b")))
        stored_a = app.state.job_service.repository.get_job(job_a["job_id"])
        stored_b = app.state.job_service.repository.get_job(job_b["job_id"])
        assert stored_a.owner_id != stored_b.owner_id
        assert job_a["workspace_id"] != job_b["workspace_id"]
        assert job_a["planning_content_hash"] != job_b["planning_content_hash"]
        assert job_a["base_snapshot_id"] == job_b["base_snapshot_id"]
        assert job_a["base_scene_id"] == "scene-x" and job_b["base_scene_id"] == "scene-x"
        _wait(left[0], job_a["job_id"], "succeeded")
        _wait(right[0], job_b["job_id"], "succeeded")

        alice, bob = TestClient(app), TestClient(app)
        _login(alice, "user-a")
        _login(bob, "user-b")
        ay = _workspace(alice, "scene-x", "AX-route")
        by = _workspace(bob, "scene-y", "BY-route")
        _save_site(alice, ay, _site(22, 1, 0.6, "blocked"))
        _save_routing(bob, by, _routing(_frame(230000), [1, 2], [6, 3], "40"))
        cross_a = _submit(alice, ay, "site.guided_search", "cross-site").json()
        cross_b = _submit(bob, by, "routing.nsga2", "cross-route", {}).json()
        assert cross_a["base_scene_id"] == "scene-x" and cross_b["base_scene_id"] == "scene-y"
        assert cross_a["base_frame_id"] != cross_b["base_frame_id"]
        assert cross_a["base_revision"] == "rev-x1" and cross_b["base_revision"] == "rev-y1"
        assert cross_a["base_snapshot_id"] != cross_b["base_snapshot_id"]
        done_a = _wait(alice, cross_a["job_id"], "succeeded")
        done_b = _wait(bob, cross_b["job_id"], "succeeded")
        assert _summary(tmp_path, done_a["result"]["data"]["experiment_id"])["base_scene_id"] == "scene-x"
        assert _summary(tmp_path, done_b["result"]["data"]["experiment_id"])["base_scene_id"] == "scene-y"


def test_h06_one_worker_runs_jobs_serially(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    _scene(tmp_path / "scenes", "scene-y", 230000, "rev-y1")
    box = {"log": ExecutionLog()}
    _install_standins(monkeypatch, box)
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        _user(admin, "user-a")
        _user(admin, "user-b")
        alice, bob = TestClient(app), TestClient(app)
        _login(alice, "user-a")
        _login(bob, "user-b")
        ax, bx = _workspace(alice, "scene-x", "AX1"), _workspace(bob, "scene-x", "BX1")
        _save_site(alice, ax, _site(20, 1, 0.4, "blocked"))
        _save_site(bob, bx, _site(28, 4, 2.0, "allowed"))
        first = _submit(alice, ax, "site.guided_search", "serial-a").json()
        box["log"].wait_entries(1)
        assert alice.get(f"/api/v1/jobs/{first['job_id']}").json()["status"] == "running"
        second = _submit(bob, bx, "site.guided_search", "serial-b").json()
        assert bob.get(f"/api/v1/jobs/{second['job_id']}").json()["status"] == "queued"
        assert box["log"].max_active == 1 and box["log"].entries == 1
        box["log"].release.set()
        assert _wait(alice, first["job_id"], "succeeded")["status"] == "succeeded"
        assert _wait(bob, second["job_id"], "succeeded")["status"] == "succeeded"
        assert box["log"].max_active == 1 and box["log"].entries == 2
        spans = sorted(box["log"].spans)
        assert spans[0][1] <= spans[1][0]

        box["log"] = ExecutionLog()
        ay, by = _workspace(alice, "scene-x", "AX2"), _workspace(bob, "scene-y", "BY2")
        _save_site(alice, ay, _site(22, 1, 0.6, "allowed"))
        _save_routing(bob, by, _routing(_frame(230000), [1, 2], [6, 3], "40"))
        site_job = _submit(alice, ay, "site.guided_search", "serial-cross-site").json()
        box["log"].wait_entries(1)
        route_job = _submit(bob, by, "routing.nsga2", "serial-cross-route", {}).json()
        assert alice.get(f"/api/v1/jobs/{site_job['job_id']}").json()["status"] == "running"
        assert bob.get(f"/api/v1/jobs/{route_job['job_id']}").json()["status"] == "queued"
        box["log"].release.set()
        assert _wait(alice, site_job["job_id"], "succeeded")
        assert _wait(bob, route_job["job_id"], "succeeded")
        assert box["log"].max_active == 1 and box["log"].entries == 2


def test_h07_running_job_keeps_the_frozen_plan_and_scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene_x = _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    _scene(tmp_path / "scenes", "scene-y", 230000, "rev-y1")
    box = {"log": ExecutionLog()}
    _install_standins(monkeypatch, box)
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        _user(admin, "user-a")
        alice = TestClient(app)
        _login(alice, "user-a")
        workspace = _workspace(alice, "scene-x", "AX1")
        _save_site(alice, workspace, _site(20, 1, 0.4, "blocked"))
        job = _submit(alice, workspace, "site.guided_search", "frozen-site").json()
        box["log"].wait_entries(1)
        _save_site(alice, workspace, _site(33, 6, 1.2, "allowed"))
        listed = admin.get("/api/v1/scenes/scene-x/landuse-edits")
        assert listed.status_code == 200, listed.text
        blocked = admin.post("/api/v1/scenes/scene-x/landuse-edits/batch", json={
            "expected_scene_revision": listed.json()["scene_revision"],
            "items": [{"id": "pond", "class_id": 5, "points": [[3, 3], [6, 3], [6, 6], [3, 6]]}],
        })
        assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "farmland_scene_busy"
        _republish(scene_x, 4, "rev-x2")
        box["log"].release.set()
        done = _wait(alice, job["job_id"], "succeeded")
        experiment = done["result"]["data"]["experiment_id"]
        form = json.loads((tmp_path / "outputs" / experiment / "site_form_snapshot.json").read_text(encoding="utf-8"))
        frozen = np.load(tmp_path / "snapshots" / job["base_snapshot_id"] / "landuse_1m.npy")
        assert form["rect_w_m"] == 20 and form["field_policy"] == "blocked" and form["include_demand"] is False
        assert int(frozen[0, 0]) == 0 and int(np.load(scene_x / "landuse_1m.npy")[0, 0]) == 4
        assert int(box["log"].seen[0][0, 0]) == 0

        box["log"] = ExecutionLog()
        route_workspace = _workspace(alice, "scene-y", "AY1")
        original = _routing(_frame(230000), [1, 2], [6, 3], "40")
        _save_routing(alice, route_workspace, original)
        route_job = _submit(alice, route_workspace, "routing.nsga2", "frozen-route", {}).json()
        box["log"].wait_entries(1)
        _save_routing(alice, route_workspace, _routing(_frame(230000), [2, 2], [5, 4], "55"))
        _republish(tmp_path / "scenes" / "scene-y", 3, "rev-y2")
        box["log"].release.set()
        route_done = _wait(alice, route_job["job_id"], "succeeded")
        route_experiment = route_done["result"]["data"]["experiment_id"]
        resolved = json.loads((tmp_path / "outputs" / route_experiment / "resolved_config.json").read_text(encoding="utf-8"))
        route_landuse = np.load(tmp_path / "outputs" / route_experiment / "scene_snapshot" / "landuse_1m.npy")
        assert resolved["start"]["lng"] == pytest.approx(float(original["start"]["lng"]))
        assert resolved["max_span_m"] == 40
        assert int(route_landuse[0, 0]) == 0


def test_h08_h09_cancel_queued_and_running_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    box = {"log": ExecutionLog()}
    _install_standins(monkeypatch, box)
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        _user(admin, "user-a")
        _user(admin, "user-b")
        alice, bob = TestClient(app), TestClient(app)
        _login(alice, "user-a")
        _login(bob, "user-b")
        ax, bx = _workspace(alice, "scene-x", "AX1"), _workspace(bob, "scene-x", "BX1")
        _save_site(alice, ax, _site(20, 1, 0.4, "blocked"))
        _save_site(bob, bx, _site(28, 4, 2.0, "allowed"))
        running = _submit(alice, ax, "site.guided_search", "cancel-running-later").json()
        box["log"].wait_entries(1)
        queued = _submit(bob, bx, "site.guided_search", "cancel-queued").json()
        assert bob.get(f"/api/v1/jobs/{queued['job_id']}").json()["status"] == "queued"
        assert alice.post(f"/api/v1/jobs/{queued['job_id']}/cancel").status_code == 404
        cancelled = bob.post(f"/api/v1/jobs/{queued['job_id']}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        snapshot = tmp_path / "snapshots" / queued["base_snapshot_id"] / "READY"
        assert snapshot.is_file()
        box["log"].release.set()
        assert _wait(alice, running["job_id"], "succeeded")["status"] == "succeeded"
        assert bob.get(f"/api/v1/jobs/{queued['job_id']}").json()["status"] == "cancelled"
        assert box["log"].entries == 1
        assert not (tmp_path / "outputs" / "cancel-queued").exists()
        assert snapshot.is_file()

        box["log"] = ExecutionLog()
        ay, by = _workspace(alice, "scene-x", "AX2"), _workspace(bob, "scene-x", "BX2")
        _save_site(alice, ay, _site(22, 1, 0.5, "allowed"))
        _save_site(bob, by, _site(26, 2, 1.5, "blocked"))
        live = _submit(alice, ay, "site.guided_search", "cancel-live").json()
        box["log"].wait_entries(1)
        follower = _submit(bob, by, "site.guided_search", "cancel-follower").json()
        started = time.monotonic()
        stopping = alice.post(f"/api/v1/jobs/{live['job_id']}/cancel")
        assert stopping.status_code == 200 and stopping.json()["status"] == "cancelling"
        stopped = _wait(alice, live["job_id"], "cancelled")
        assert stopped["status"] == "cancelled" and time.monotonic() - started < 5
        box["log"].release.set()
        assert _wait(bob, follower["job_id"], "succeeded")["status"] == "succeeded"
        assert alice.get(f"/api/v1/jobs/{live['job_id']}").json()["status"] == "cancelled"


def test_h10_failed_enqueue_is_requeued_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    box = {"log": ExecutionLog()}
    box["log"].release.set()
    _install_standins(monkeypatch, box)
    app = _app(tmp_path)

    class FlakyQueue:
        def __init__(self, inner) -> None:
            self.inner = inner
            self.fail = True

        def enqueue(self, job_id: str) -> None:
            if self.fail:
                raise RuntimeError("redis down")
            self.inner.enqueue(job_id)

        def dequeue(self, timeout: int = 5):
            return self.inner.dequeue(timeout)

    with TestClient(app, raise_server_exceptions=False) as admin:
        app.state.job_service.queue = FlakyQueue(app.state.job_service.queue)
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        _user(admin, "user-a")
        alice = TestClient(app)
        _login(alice, "user-a")
        workspace = _workspace(alice, "scene-x", "AX1")
        _save_site(alice, workspace, _site(20, 1, 0.4, "allowed"))
        failed = _submit(alice, workspace, "site.guided_search", "enqueue-once")
        assert failed.status_code == 202 and failed.json()["status"] == "queued"
        queued = app.state.job_service.repository.list_active_jobs()
        assert len(queued) == 1 and queued[0].status.value == "queued"
        app.state.job_service.queue.fail = False
        app.state.job_service.recover_jobs()
        done = _wait(alice, queued[0].id, "succeeded")
        assert box["log"].entries == 1
        app.state.job_service.queue.enqueue(done["job_id"])
        time.sleep(0.4)
        assert box["log"].entries == 1
        assert alice.get(f"/api/v1/jobs/{done['job_id']}").json()["status"] == "succeeded"


def test_h11_worker_recovery_fails_the_interrupted_job_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    box = {"log": ExecutionLog()}
    _install_standins(monkeypatch, box)
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        _user(admin, "user-a")
        _user(admin, "user-b")
        alice, bob = TestClient(app), TestClient(app)
        _login(alice, "user-a")
        _login(bob, "user-b")
        ax, bx = _workspace(alice, "scene-x", "AX1"), _workspace(bob, "scene-x", "BX1")
        _save_site(alice, ax, _site(20, 1, 0.4, "blocked"))
        _save_site(bob, bx, _site(28, 4, 2.0, "allowed"))
        running = _submit(alice, ax, "site.guided_search", "interrupted").json()
        box["log"].wait_entries(1)
        waiting = _submit(bob, bx, "site.guided_search", "still-queued").json()
        app.state.job_service.recover_jobs()
        failed = alice.get(f"/api/v1/jobs/{running['job_id']}").json()
        assert failed["status"] == "failed"
        assert "Worker 已中断" in failed["error"]["message"] and "未自动重跑" in failed["error"]["message"]
        assert bob.get(f"/api/v1/jobs/{waiting['job_id']}").json()["status"] == "queued"
        box["log"].release.set()
        assert _wait(bob, waiting["job_id"], "succeeded")["status"] == "succeeded"
        assert alice.get(f"/api/v1/jobs/{running['job_id']}").json()["status"] == "failed"
        assert box["log"].entries == 2 and box["log"].max_active == 1


def test_h12_results_follow_the_job_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    box = {"log": ExecutionLog()}
    box["log"].release.set()
    _install_standins(monkeypatch, box)
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        owner_a = _user(admin, "user-a")
        _user(admin, "user-b")
        alice, bob = TestClient(app), TestClient(app)
        _login(alice, "user-a")
        _login(bob, "user-b")
        ax, bx = _workspace(alice, "scene-x", "AX1"), _workspace(bob, "scene-x", "BX1")
        _save_site(alice, ax, _site(20, 1, 0.4, "blocked"))
        _save_site(bob, bx, _site(28, 4, 2.0, "allowed"))
        job_a = _wait(alice, _submit(alice, ax, "site.guided_search", "result-a").json()["job_id"], "succeeded")
        job_b = _wait(bob, _submit(bob, bx, "site.guided_search", "result-b").json()["job_id"], "succeeded")
        experiment_a = job_a["result"]["data"]["experiment_id"]
        experiment_b = job_b["result"]["data"]["experiment_id"]
        own = alice.get(f"/api/v1/experiments/{experiment_a}")
        assert own.status_code == 200, own.text
        assert bob.get(f"/api/v1/jobs/{job_a['job_id']}").status_code == 404
        assert bob.get(f"/api/v1/jobs/{job_a['job_id']}/result").status_code == 404
        assert bob.get(f"/api/v1/experiments/{experiment_a}").status_code == 404
        assert alice.get(f"/api/v1/experiments/{experiment_b}").status_code == 404
        artifacts = own.json()["artifacts"]
        assert artifacts
        assert bob.get(f"/api/v1/experiments/{experiment_a}/artifacts/{artifacts[0]['id']}").status_code == 404
        published = own.text + alice.get(f"/api/v1/jobs/{job_a['job_id']}").text
        assert str(tmp_path) not in published and "resolved_config_json" not in published
        summary = _summary(tmp_path, experiment_a)
        assert summary["owner_id"] == owner_a
        assert summary["workspace_id"] == ax["workspace_id"]
        assert summary["workspace_revision"] == job_a["workspace_revision"]
        assert summary["base_scene_id"] == "scene-x"
        assert summary["base_snapshot_id"] == job_a["base_snapshot_id"]
        assert summary["job_id"] == job_a["job_id"]


def test_h15_public_scene_writes_stay_with_the_admin(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    app = _app(tmp_path)
    with TestClient(app) as admin:
        _login(admin, os.environ["BOOTSTRAP_ADMIN_USERNAME"], ADMIN_PASSWORD)
        _user(admin, "user-a")
        alice = TestClient(app)
        _login(alice, "user-a")
        body = {"expected_scene_revision": "rev-x1", "items": [{"id": "pond", "class_id": 5, "points": [[3, 3], [6, 3], [6, 6], [3, 6]]}]}
        assert alice.post("/api/v1/scenes/scene-x/landuse-edits/batch", json=body).status_code == 403
        assert alice.post("/api/v1/scenes/scene-x/cad-files").status_code == 403
        assert alice.delete("/api/v1/scenes/scene-x").status_code == 403
        assert alice.post("/api/v1/jobs", json={"plugin_id": "site.prepare_scene", "config": {"scene_name": "scene-x"}}).status_code == 403
        current = admin.get("/api/v1/scenes/scene-x/landuse-edits").json()["scene_revision"]
        published = admin.post("/api/v1/scenes/scene-x/landuse-edits/batch", json={**body, "expected_scene_revision": current})
        assert published.status_code == 200, published.text
        assert published.json()["changed"] is True
