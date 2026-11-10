"""Workspace jobs keep the revision and base snapshot they were submitted with."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pytest
from fastapi.testclient import TestClient

from algorithms.routing.types import RoutingResult
from backend.app.main import create_app
from experiments.scene_version import scene_data_version
from modeling.routing.types import RoutingFrame
from tests.auth_flags import skip_auto_login

PASSWORD = "user-pass-9f3c"


@pytest.fixture(autouse=True)
def _keep_jobs_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API starts a local worker for the in-memory queue. These tests execute jobs themselves."""

    monkeypatch.setattr("backend.app.infrastructure.queue.InMemoryTaskQueue.dequeue", lambda self, timeout=5: None)
FRAME = RoutingFrame("EPSG:32651", (1, 0, 221000, 0, -1, 3046000), 8, 8)


def _scene(root: Path, name: str = "demo", revision: str = "rev-b1", landuse: int = 0) -> Path:
    scene = root / name
    scene.mkdir(parents=True, exist_ok=True)
    shape = (8, 8)
    arrays = {
        "dem_1m.npy": np.ones(shape, np.float32),
        "landuse_1m.npy": np.full(shape, landuse, np.uint8),
        "obstacle_mask_1m.npy": np.zeros(shape, np.uint8),
        "road_segments_local.npy": np.array([[0, 1, 6, 1]], np.float32),
        "road_segment_kind.npy": np.zeros(1, np.int8),
        "road_voronoi_1m.npy": np.zeros(shape, np.int64),
        "demand_points.npy": np.array([[1.0, 1.0]], np.float32),
        "protected_farmland_mask_1m.npy": np.zeros(shape, dtype=bool),
    }
    arrays["protected_farmland_mask_1m.npy"][2, 2] = 1
    for filename, array in arrays.items():
        np.save(scene / filename, array)
    (scene / "data_metadata.json").write_text(json.dumps({
        "scene_revision": revision,
        "dem": {"reference_crs": FRAME.crs, "target_transform": list(FRAME.transform), "shape": [8, 8]},
    }), encoding="utf-8")
    (scene / "scene.json").write_text("{}\n", encoding="utf-8")
    return scene


def _republish(scene: Path, landuse: int, revision: str) -> None:
    np.save(scene / "landuse_1m.npy", np.full((8, 8), landuse, np.uint8))
    metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
    metadata["scene_revision"] = revision
    (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def _app(tmp_path: Path, database: str | None = None):
    url = database or f"sqlite:///{tmp_path / 'app.sqlite3'}"
    os.environ["DATABASE_URL"] = url
    os.environ["SCENE_ROOT"] = str(tmp_path / "scenes")
    os.environ["EXPERIMENT_OUTPUT_ROOT"] = str(tmp_path / "outputs")
    os.environ["BASE_SNAPSHOT_ROOT"] = str(tmp_path / "snapshots")
    return create_app(url, "", experiment_root=tmp_path / "outputs", favorite_db_path=tmp_path / "favorites.sqlite3")


def _login(client: TestClient, username: str, password: str = PASSWORD) -> None:
    client.cookies.clear()
    token = skip_auto_login.set(True)
    try:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    finally:
        skip_auto_login.reset(token)
    assert response.status_code == 200, response.text
    client.csrf_token = response.json()["csrf_token"]


def _user(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/admin/users", json={"username": username, "password": PASSWORD, "role": "user"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _workspace(client: TestClient, name: str = "方案甲") -> dict:
    response = client.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _site(width: float = 20, origin: float = 1.5) -> dict:
    return {
        "rect_w_m": width, "rect_h_m": 18, "field_policy": "allowed", "mountain_policy": "allowed",
        "field_cost": 0.5, "include_demand": False, "diagonal_access": True,
        "road_setback_m": 0, "water_setback_m": 0, "highway_setback_m": 0,
        "elevation_enabled": False, "elevation_draft": "", "exclusion_zones": [], "feasible_zones": [],
        "origin": {"x": origin, "y": 1.5},
    }


def _routing(start, end, span: str = "30") -> dict:
    return {
        "start": {"lng": f"{start[0]:.8f}", "lat": f"{start[1]:.8f}"},
        "end": {"lng": f"{end[0]:.8f}", "lat": f"{end[1]:.8f}"},
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
    return response.json()


def _save_routing(client: TestClient, workspace: dict, routing: dict) -> dict:
    response = client.put(
        f"/api/v1/workspaces/{workspace['workspace_id']}/plan/routing",
        json={"expected_workspace_revision": workspace["workspace_revision"], "routing": routing},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _submit(client: TestClient, workspace_id: str, revision: str, plugin: str, name: str, options: dict | None = None) -> object:
    return client.post(
        f"/api/v1/workspaces/{workspace_id}/jobs",
        json={
            "plugin_id": plugin,
            "expected_workspace_revision": revision,
            "experiment_name": name,
            "overwrite_existing": False,
            "run_options": options or {},
        },
    )


def _stub_site(monkeypatch: pytest.MonkeyPatch) -> list[np.ndarray]:
    seen: list[np.ndarray] = []

    def run_guided_search(problem, *_args, **_kwargs):
        seen.append(np.array(problem.landuse).copy())
        return type("Result", (), {"solutions": [], "normalization": {}, "objective_names": ("dem_soft", "road_distance", "demand_distance")})()

    monkeypatch.setattr("algorithms.guided_search.search.run_guided_search", run_guided_search)
    return seen


def _stub_routing(monkeypatch: pytest.MonkeyPatch) -> list[np.ndarray]:
    seen: list[np.ndarray] = []

    def routing_search(problem, *_args, **_kwargs):
        seen.append(np.array(problem.landuse).copy())
        return RoutingResult([], [], [], 0, 0, 0, 0, [], "stub", 0, 0, {"devices": ["cpu"]})

    monkeypatch.setattr("algorithms.routing.search.routing_search", routing_search)
    return seen


def _summary(tmp_path: Path, experiment_id: str) -> dict:
    return json.loads((tmp_path / "outputs" / experiment_id / "run_summary.json").read_text(encoding="utf-8"))


def test_site_job_keeps_v1_and_b1_after_later_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    seen = _stub_site(monkeypatch)
    with TestClient(app) as client:
        _user(client, "planner-a")
        _login(client, "planner-a")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site(origin=1.5))
        created = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "site-v1", {"device": "cpu", "seed": 3, "popsize": 4, "generations": 1})
        assert created.status_code == 202, created.text
        job = created.json()
        revised = _save_site(client, {**workspace, "workspace_revision": saved["workspace_revision"]}, _site(width=30, origin=4))
        _republish(scene, 3, "rev-b2")
        refused = _submit(client, workspace["workspace_id"], revised["workspace_revision"], "site.guided_search", "site-stale", {"device": "cpu"})
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "workspace_base_changed"
        finished = app.state.job_service.execute_job(job["job_id"])
    assert finished.status.value == "succeeded", finished.error
    assert seen and int(seen[0][0, 0]) == 0
    form = json.loads((tmp_path / "outputs" / finished.result["data"]["experiment_id"] / "site_form_snapshot.json").read_text(encoding="utf-8"))
    metadata = json.loads((tmp_path / "outputs" / finished.result["data"]["experiment_id"] / "data_metadata.json").read_text(encoding="utf-8"))
    summary = _summary(tmp_path, finished.result["data"]["experiment_id"])
    assert form["origin_x"] == 1.5 and form["rect_w_m"] == 20
    assert metadata["scene_dir"] == job["base_snapshot_id"] and "/" not in metadata["scene_dir"]
    assert summary["workspace_revision"] == job["workspace_revision"]
    assert summary["base_snapshot_id"] == job["base_snapshot_id"]
    assert summary["base_revision"] == "rev-b1"
    assert "snapshots" not in json.dumps(summary)


def test_routing_job_uses_frozen_plan_snapshot_and_pilot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from config.routing_task import RoutingRunConfig
    from dataclasses import replace
    import config.routing_task as routing_task

    _scene(tmp_path / "scenes")
    start, end = FRAME.to_wgs84([1, 2]), FRAME.to_wgs84([6, 2])
    app = _app(tmp_path)
    seen = _stub_routing(monkeypatch)
    with TestClient(app) as client:
        _user(client, "planner-route")
        _login(client, "planner-route")
        workspace = _workspace(client)
        saved = _save_routing(client, workspace, _routing(start, end))
        created = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "routing.nsga2", "route-v1")
        assert created.status_code == 202, created.text
        job = created.json()
        stored = json.loads(app.state.job_service.repository.get_job(job["job_id"]).resolved_config_json)
        original = stored["form"]["algorithm"]["pilot"]["rrt_goal_bias"]
        previous = routing_task._DEFAULTS
        routing_task._DEFAULTS = replace(
            previous,
            routing=replace(previous.routing, pilot=replace(previous.routing.pilot, rrt_goal_bias=original + 0.2)),
        )
        try:
            _republish(tmp_path / "scenes" / "demo", 4, "rev-b2")
            finished = app.state.job_service.execute_job(job["job_id"])
        finally:
            routing_task._DEFAULTS = previous
    assert finished.status.value == "succeeded", finished.error
    assert seen and int(seen[0][0, 0]) == 0
    resolved = json.loads((tmp_path / "outputs" / finished.result["data"]["experiment_id"] / "resolved_config.json").read_text(encoding="utf-8"))
    copied = np.load(tmp_path / "outputs" / finished.result["data"]["experiment_id"] / "scene_snapshot" / "landuse_1m.npy")
    assert resolved["start"]["lng"] == pytest.approx(start[0])
    assert resolved["algorithm"]["pilot"]["rrt_goal_bias"] == original
    assert int(copied[0, 0]) == 0
    assert RoutingRunConfig.model_validate(stored["form"]).algorithm.pilot.rrt_goal_bias == original
    summary = _summary(tmp_path, finished.result["data"]["experiment_id"])
    assert summary["base_snapshot_id"] == job["base_snapshot_id"] and summary["plugin_id"] == "routing.nsga2"


def test_two_users_share_one_snapshot_and_keep_separate_plans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    _stub_site(monkeypatch)
    with TestClient(app) as client:
        first = _user(client, "owner-a")
        second = _user(client, "owner-b")
        _login(client, "owner-a")
        workspace_a = _workspace(client, "甲")
        saved_a = _save_site(client, workspace_a, _site(width=20))
        job_a = _submit(client, workspace_a["workspace_id"], saved_a["workspace_revision"], "site.guided_search", "a-site", {"device": "cpu", "popsize": 4, "generations": 1}).json()
        _login(client, "owner-b")
        stolen = _submit(client, workspace_a["workspace_id"], saved_a["workspace_revision"], "site.guided_search", "stolen", {"device": "cpu"})
        assert stolen.status_code == 404
        workspace_b = _workspace(client, "乙")
        saved_b = _save_site(client, workspace_b, _site(width=24))
        job_b = _submit(client, workspace_b["workspace_id"], saved_b["workspace_revision"], "site.guided_search", "b-site", {"device": "cpu", "popsize": 4, "generations": 1}).json()
        finished_b = app.state.job_service.execute_job(job_b["job_id"])
        finished_a = app.state.job_service.execute_job(job_a["job_id"])
    assert job_a["base_snapshot_id"] == job_b["base_snapshot_id"]
    assert job_a["planning_content_hash"] != job_b["planning_content_hash"]
    summary_a = _summary(tmp_path, finished_a.result["data"]["experiment_id"])
    summary_b = _summary(tmp_path, finished_b.result["data"]["experiment_id"])
    assert summary_a["owner_id"] == first and summary_b["owner_id"] == second
    form_a = json.loads((tmp_path / "outputs" / finished_a.result["data"]["experiment_id"] / "site_form_snapshot.json").read_text(encoding="utf-8"))
    form_b = json.loads((tmp_path / "outputs" / finished_b.result["data"]["experiment_id"] / "site_form_snapshot.json").read_text(encoding="utf-8"))
    assert form_a["rect_w_m"] == 20 and form_b["rect_w_m"] == 24


def test_deleted_workspace_does_not_drop_a_queued_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    _stub_site(monkeypatch)
    with TestClient(app) as client:
        _user(client, "owner-delete")
        _login(client, "owner-delete")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site())
        job = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "kept", {"device": "cpu", "popsize": 4, "generations": 1}).json()
        deleted = client.delete(f"/api/v1/workspaces/{workspace['workspace_id']}")
        assert deleted.status_code == 200, deleted.text
        finished = app.state.job_service.execute_job(job["job_id"])
    assert finished.status.value == "succeeded", finished.error
    assert _summary(tmp_path, finished.result["data"]["experiment_id"])["workspace_id"] == workspace["workspace_id"]


def test_tampered_snapshot_revision_or_config_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    calls = _stub_site(monkeypatch)
    with TestClient(app) as client:
        _user(client, "owner-tamper")
        _login(client, "owner-tamper")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site())
        jobs = []
        for name in ("tamper-snapshot", "tamper-hash", "tamper-config"):
            created = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", name, {"device": "cpu", "popsize": 4, "generations": 1})
            assert created.status_code == 202, created.text
            jobs.append(created.json())
        snapshot = tmp_path / "snapshots" / jobs[0]["base_snapshot_id"] / "dem_1m.npy"
        snapshot.chmod(0o644)
        snapshot.write_bytes(snapshot.read_bytes() + b"x")
        failed_snapshot = app.state.job_service.execute_job(jobs[0]["job_id"])
        repository = app.state.job_service.repository
        repository._connection.execute("UPDATE jobs SET planning_content_hash = ? WHERE id = ?", ("0" * 64, jobs[1]["job_id"]))
        failed_hash = app.state.job_service.execute_job(jobs[1]["job_id"])
        repository._connection.execute(
            "UPDATE jobs SET resolved_config_json = ? WHERE id = ?",
            (json.dumps({"plugin_id": "site.guided_search"}), jobs[2]["job_id"]),
        )
        failed_config = app.state.job_service.execute_job(jobs[2]["job_id"])
    assert failed_snapshot.status.value == "failed" and calls == []
    assert failed_hash.status.value == "failed" and "哈希" in failed_hash.error["message"]
    assert failed_config.status.value == "failed" and "配置" in failed_config.error["message"]
    assert scene_data_version(scene)["scene_revision"] == "rev-b1"
    assert not (tmp_path / "outputs" / "tamper-snapshot").exists()


def test_frozen_farmland_width_ignores_later_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    _stub_site(monkeypatch)

    def live_width() -> float:
        raise AssertionError("workspace execution reread protected_farmland_access_width_m")

    monkeypatch.setattr("experiments.protected_farmland.access_road_width_m", live_width)
    with TestClient(app) as client:
        _user(client, "owner-width")
        _login(client, "owner-width")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site())
        created = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "width", {"device": "cpu", "popsize": 4, "generations": 1})
        assert created.status_code == 202, created.text
        stored = json.loads(app.state.job_service.repository.get_job(created.json()["job_id"]).resolved_config_json)
        finished = app.state.job_service.execute_job(created.json()["job_id"])
    assert finished.status.value == "succeeded", finished.error
    assert stored["protected_farmland_access_width_m"] == 4.0


def test_enqueue_failure_reference_failure_and_duplicate_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    seen = _stub_site(monkeypatch)
    service = app.state.job_service

    class FlakyQueue:
        def __init__(self) -> None:
            self.failed = True
            self.items: list[str] = []

        def enqueue(self, job_id: str) -> None:
            if self.failed:
                raise RuntimeError("redis down")
            self.items.append(job_id)

        def dequeue(self, timeout: int = 5):
            return None

    service.queue = FlakyQueue()
    with TestClient(app) as client:
        _user(client, "owner-queue")
        _login(client, "owner-queue")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site())
        queued = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "queued", {"device": "cpu", "popsize": 4, "generations": 1})
        assert queued.status_code == 202 and queued.json()["status"] == "queued"
        assert service.queue.items == []
        service.queue.failed = False
        service.recover_jobs()
        assert service.queue.items == [queued.json()["job_id"]]
        from backend.app.infrastructure.base_snapshot_repository import BaseSnapshotRepository

        real_add = BaseSnapshotRepository.add_reference

        def fail_once(self, snapshot_id: str, kind: str, reference_id: str) -> bool:
            fail_once.calls += 1
            if fail_once.calls == 1:
                raise RuntimeError("catalog down")
            return real_add(self, snapshot_id, kind, reference_id)

        fail_once.calls = 0
        monkeypatch.setattr(BaseSnapshotRepository, "add_reference", fail_once)
        referenced = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "reference", {"device": "cpu", "popsize": 4, "generations": 1})
        assert referenced.status_code == 202, referenced.text
        snapshot_id = referenced.json()["base_snapshot_id"]
        assert (tmp_path / "snapshots" / snapshot_id / "READY").is_file()
        finished = service.execute_job(referenced.json()["job_id"])
        again = service.execute_job(referenced.json()["job_id"])
    assert finished.status.value == "succeeded", finished.error
    assert again.status.value == "succeeded" and len(seen) == 1
    catalog = BaseSnapshotRepository(f"sqlite:///{tmp_path / 'app.sqlite3'}")
    assert catalog.reference_counts()[snapshot_id] >= 1


def test_cancel_interrupt_and_insert_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    seen = _stub_site(monkeypatch)
    service = app.state.job_service
    with TestClient(app) as client:
        _user(client, "owner-cancel")
        _login(client, "owner-cancel")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site())
        queued = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "cancel-me", {"device": "cpu", "popsize": 4, "generations": 1}).json()
        cancelled = client.post(f"/api/v1/jobs/{queued['job_id']}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert service.execute_job(queued["job_id"]).status.value == "cancelled"
        running = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "interrupt-me", {"device": "cpu", "popsize": 4, "generations": 1}).json()
        assert service.repository.start_job(running["job_id"]) is True
        service.recover_jobs()
        interrupted = service.get_job(running["job_id"])
        real_create = service.repository.create_job

        def fail_create(*_args, **_kwargs):
            raise RuntimeError("database down")

        monkeypatch.setattr(service.repository, "create_job", fail_create)
        with pytest.raises(RuntimeError, match="database down"):
            _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "not-stored", {"device": "cpu"})
        monkeypatch.setattr(service.repository, "create_job", real_create)
    assert seen == []
    assert interrupted.status.value == "failed" and "未自动重跑" in interrupted.error["message"]
    assert service.get_job(running["job_id"]).status.value == "failed"
    assert all(record.config.get("experiment_name") != "not-stored" for record in service.repository.list_active_jobs())


def test_legacy_jobs_reject_workspace_fields_and_still_read_the_live_scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    seen = _stub_site(monkeypatch)
    with TestClient(app) as client:
        _user(client, "owner-legacy")
        _login(client, "owner-legacy")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site())
        bound = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "bound", {"device": "cpu", "popsize": 4, "generations": 1}).json()
        _republish(scene, 1, "rev-b2")
        forged = client.post("/api/v1/jobs", json={"plugin_id": "site.guided_search", "config": {"workspace_id": workspace["workspace_id"], "experiment_name": "forged", "scene_name": "demo"}})
        assert forged.status_code == 422 and "工作区" in forged.json()["detail"]["message"]
        legacy = client.post("/api/v1/jobs", json={"plugin_id": "site.guided_search", "config": {**bound["config"], "experiment_name": "legacy-live", "device": "cpu"}})
        assert legacy.status_code == 202, legacy.text
        assert legacy.json()["workspace_id"] is None
        legacy_done = app.state.job_service.execute_job(legacy.json()["job_id"])
        bound_done = app.state.job_service.execute_job(bound["job_id"])
        routing = client.post("/api/v1/jobs", json={"plugin_id": "routing.nsga2", "config": {"workspace_id": "fake"}})
        assert routing.status_code == 422
        build = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.build_scene", "build")
        empty = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "routing.nsga2", "no-routing")
    assert legacy_done.status.value == "succeeded", legacy_done.error
    assert bound_done.status.value == "succeeded", bound_done.error
    assert int(seen[0][0, 0]) == 1 and int(seen[1][0, 0]) == 0
    assert build.status_code == 422 and empty.status_code == 422


def test_concurrent_submits_share_the_snapshot_without_clobbering_references(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    with TestClient(app) as client:
        _user(client, "owner-left")
        _user(client, "owner-right")

        def submit(username: str, name: str) -> dict:
            local = TestClient(app)
            _login(local, username)
            workspace = _workspace(local, name)
            saved = _save_site(local, workspace, _site(width=20 if username == "owner-left" else 22))
            response = _submit(local, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", name, {"device": "cpu", "popsize": 4, "generations": 1})
            assert response.status_code == 202, response.text
            return response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            left, right = list(pool.map(submit, ("owner-left", "owner-right"), ("left", "right")))
    assert left["base_snapshot_id"] == right["base_snapshot_id"]
    from backend.app.infrastructure.base_snapshot_repository import BaseSnapshotRepository

    counts = BaseSnapshotRepository(f"sqlite:///{tmp_path / 'app.sqlite3'}").reference_counts()
    assert counts[left["base_snapshot_id"]] == 2


def test_postgres_job_row_stores_the_same_frozen_binding(tmp_path: Path) -> None:
    url = os.getenv("TEST_JOB_DATABASE_URL", "")
    if not url:
        pytest.skip("requires an isolated TEST_JOB_DATABASE_URL")
    assert urlparse(url).path == "/p1_account_repair"
    _scene(tmp_path / "scenes")
    app = _app(tmp_path, url)
    with TestClient(app) as client:
        _user(client, "pg-owner")
        _login(client, "pg-owner")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site())
        created = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "pg-site", {"device": "cpu", "popsize": 4, "generations": 1})
        assert created.status_code == 202, created.text
        body = created.json()
        stored = app.state.job_service.repository.get_job(body["job_id"])
    assert stored is not None and stored.workspace_id == body["workspace_id"]
    assert stored.base_snapshot_id == body["base_snapshot_id"]
    assert stored.effective_config_hash == body["effective_config_hash"]
    assert stored.resolved_config_json and "protected_farmland_access_width_m" in stored.resolved_config_json


def test_old_experiment_and_snapshot_directory_stay_distinct(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    app = _app(tmp_path)
    old = tmp_path / "outputs" / "historical"
    old.mkdir(parents=True)
    (old / "run_summary.json").write_text(json.dumps({"result_origin": "auto", "problem_type": "site", "scene_name": "demo", "owner_id": "historical"}), encoding="utf-8")
    with TestClient(app) as client:
        _user(client, "owner-history")
        _login(client, "owner-history")
        workspace = _workspace(client)
        saved = _save_site(client, workspace, _site())
        created = _submit(client, workspace["workspace_id"], saved["workspace_revision"], "site.guided_search", "history", {"device": "cpu", "popsize": 4, "generations": 1})
        assert created.status_code == 202, created.text
    from backend.app.infrastructure.experiment_catalog import ExperimentCatalog

    names = {item.name for item in ExperimentCatalog(tmp_path / "outputs").list_experiments()}
    assert "historical" in names
    assert created.json()["base_snapshot_id"] not in names
    assert (tmp_path / "snapshots" / created.json()["base_snapshot_id"] / "READY").is_file()
