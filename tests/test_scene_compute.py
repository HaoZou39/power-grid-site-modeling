"""Deterministic scene snapshot, admission and complete re-evaluation contracts."""
import threading

import numpy as np
import pytest
import torch

from config.project_config import load_default_config
from experiments.scene_lock import SceneBusyError, scene_compute_lock, scene_write_lock
from experiments.scene_store import read_scene_snapshot, load_scene, initialize_scene_catalog, list_scenes
from tests.test_scene_store import _write_products


def test_snapshot_is_complete_after_source_files_disappear(tmp_path):
    directory = tmp_path / "sample"
    _write_products(directory)
    np.save(directory / "protected_farmland_mask_1m.npy", np.ones((2, 3), dtype=bool))
    snapshot = read_scene_snapshot("sample", tmp_path)
    for path in directory.glob("*.npy"):
        path.unlink()
    defaults = load_default_config().modeling
    problem, metadata = load_scene("sample", torch.device("cpu"), tmp_path,
        road_setback_m=defaults.road_setback_m, water_setback_m=defaults.water_setback_m,
        highway_setback_m=defaults.highway_setback_m, snapshot=snapshot)
    assert problem.dem.shape == (2, 3)
    assert snapshot["farmland"].all()
    assert metadata["data_version"]["scene_revision"]
    assert metadata["scene_signature"]


def test_catalog_returns_while_scene_data_is_locked(tmp_path):
    _write_products(tmp_path / "sample")
    initialize_scene_catalog(tmp_path)
    done = threading.Event()
    results = []
    def read():
        results.extend(list_scenes(tmp_path))
        done.set()
    with scene_write_lock("sample", tmp_path):
        thread = threading.Thread(target=read)
        thread.start()
        returned = done.wait(2)
    thread.join(2)
    assert returned, "catalog must return before the data lock is released"
    assert any(item["id"] == "sample" and item["ready"] for item in results)


def test_constraint_construction_releases_data_lock(tmp_path, monkeypatch):
    from experiments import launch_site_run as launch
    _write_products(tmp_path / "sample")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path))
    acquired = threading.Event()
    def build(*args, **kwargs):
        def inspect():
            with scene_write_lock("sample", tmp_path):
                acquired.set()
        thread = threading.Thread(target=inspect)
        thread.start()
        thread.join(2)
        assert acquired.is_set()
        return "problem", kwargs["snapshot"]["metadata"]
    monkeypatch.setattr(launch, "_constrained_problem", build)
    launch.constrained_problem({"scene_name": "sample"}, torch.device("cpu"), load_default_config().modeling)
    with pytest.raises(ValueError, match="版本"):
        launch.constrained_problem({"scene_name": "sample", "expected_revision": "outdated"}, "cpu", load_default_config().modeling)


def test_reevaluation_builds_once_and_publishes_only_complete_result(monkeypatch):
    from plugins.reevaluation_plugin import ReevaluatePosesPlugin
    import experiments.launch_site_run as launch
    import algorithms.guided_search.search as search
    monkeypatch.setattr("config.project_config.resolve_guided_search_device", lambda _: torch.device("cpu"))
    counts = {"context": 0, "field": 0, "sizes": []}
    def context(*args):
        counts["context"] += 1
        return object(), {"data_version": {"scene_revision": "v2"}, "coordinate_context": {"scene_id": "sample"}}
    def field(*args):
        counts["field"] += 1
        return object()
    def records(problem, modeling, origin, poses, **kwargs):
        counts["sizes"].append(len(poses))
        return [{"is_feasible": True} for _ in poses]
    monkeypatch.setattr(launch, "constrained_problem", context)
    monkeypatch.setattr(launch, "_shared_haul_field", field)
    monkeypatch.setattr(search, "pose_records", records)
    config = {"scene_name": "sample", "experiment_name": "review", "expected_revision": "v2",
              "poses": [{"id": str(i), "x": float(i), "y": 1, "theta": 0} for i in range(401)]}
    result = ReevaluatePosesPlugin().run(config, lambda *args: None)
    assert counts == {"context": 1, "field": 1, "sizes": [200, 200, 1]}
    assert len(result.data["items"]) == 401
    assert result.data["items"][-1]["id"] == "400"
    assert result.data["coordinate_context"]["scene_id"] == "sample"
    from backend.app.domain.jobs import JobCancelled
    def cancel(progress, stage, message):
        if stage == "evaluating":
            raise JobCancelled()
    with pytest.raises(JobCancelled):
        ReevaluatePosesPlugin().run(config, cancel)


def test_job_admission_reserves_queued_scene_and_checks_revision(tmp_path, monkeypatch):
    from backend.app.application.registry import build_registry
    from backend.app.application.service import JobService
    from backend.app.infrastructure.repository import create_job_repository
    from backend.app.infrastructure.queue import create_task_queue
    _write_products(tmp_path / "sample")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path))
    service = JobService(create_job_repository("sqlite://:memory:"), create_task_queue(""), build_registry())
    enqueue = service.queue.enqueue
    def enqueue_after_admission(job_id):
        released = threading.Event()
        def probe():
            with scene_compute_lock("sample", tmp_path):
                released.set()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(2)
        assert released.is_set(), "worker must not be notified before admission locks are released"
        enqueue(job_id)
    monkeypatch.setattr(service.queue, "enqueue", enqueue_after_admission)
    config = {"scene_name": "sample", "experiment_name": "review", "expected_revision": "bad",
              "poses": [{"id": "a", "x": 1, "y": 1, "theta": 0}]}
    with pytest.raises(SceneBusyError, match="版本"):
        service.create_job("site.reevaluate_poses", config)
    config["expected_revision"] = read_scene_snapshot("sample", tmp_path)["metadata"]["data_version"]["scene_revision"]
    job = service.create_job("site.reevaluate_poses", config)
    with pytest.raises(SceneBusyError):
        service.create_job("site.reevaluate_poses", config)
    service.cancel_job(job.id)
    assert service.create_job("site.reevaluate_poses", config)


def test_sync_compute_excludes_jobs_and_mutation_but_not_catalog(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    _write_products(tmp_path / "sample")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path))
    entered, release = threading.Event(), threading.Event()
    def evaluate(*args):
        entered.set()
        assert release.wait(5)
        return [{"is_feasible": True}]
    monkeypatch.setattr("experiments.launch_site_run.evaluate_form_poses", evaluate)
    app = create_app("sqlite://:memory:", "", experiment_root=tmp_path / "outputs", favorite_db_path=tmp_path / "favorites.db")
    with TestClient(app) as client, ThreadPoolExecutor(1) as pool:
        pending = pool.submit(client.post, "/api/v1/scenes/sample/pose-objectives", json={
            "rect_w_m": 1, "rect_h_m": 1, "mountain_policy": "allowed", "field_policy": "allowed",
            "field_cost": 0.5, "exclusion_zones": [], "feasible_zones": [], "include_demand": False,
            "poses": [{"x": 1, "y": 1, "theta": 0}]})
        try:
            assert entered.wait(3)
            response = client.get("/api/v1/scenes")
            assert response.status_code == 200
            assert next(s for s in response.json() if s["id"] == "sample")["computing"]
            response = client.delete("/api/v1/scenes/sample/protected-farmland")
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "scene_busy"
            config = {"scene_name": "sample", "experiment_name": "review", "expected_revision": "v2",
                      "poses": [{"id": "a", "x": 1, "y": 1, "theta": 0}]}
            assert client.post("/api/v1/jobs", json={"plugin_id": "site.reevaluate_poses", "config": config}).status_code == 409
        finally:
            release.set()
        assert pending.result(timeout=3).status_code == 200


def test_compute_lock_excludes_processes_and_survives_crash(tmp_path):
    import subprocess
    import sys
    code = """
import sys
from pathlib import Path
from experiments.scene_lock import scene_compute_lock
with scene_compute_lock('sample', Path(sys.argv[1])):
    print('locked', flush=True)
    sys.stdin.read()
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(SceneBusyError):
            with scene_compute_lock("sample", tmp_path):
                pass
        with scene_write_lock("sample", tmp_path):
            pass
    finally:
        child.kill()
        child.wait(timeout=3)
    with scene_compute_lock("sample", tmp_path):
        pass


def test_prepare_holds_compute_admission_but_not_data_lock(tmp_path, monkeypatch):
    from experiments import scene_store
    def prepare(*args, **kwargs):
        acquired = threading.Event()
        def probe():
            with scene_write_lock("sample", tmp_path):
                acquired.set()
            with pytest.raises(SceneBusyError):
                with scene_compute_lock("sample", tmp_path):
                    pass
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(2)
        assert acquired.is_set()
        return tmp_path / "sample"
    monkeypatch.setattr(scene_store, "_prepare_scene_from_sources", prepare)
    scene_store.prepare_scene_from_sources("sample", {}, lambda *args: None,
        title="sample", source_site_id="sample", root=tmp_path)
