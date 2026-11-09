"""Personal planning workspaces store metadata only and stay behind the session owner."""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.infrastructure.workspace_repository import WorkspaceRepository
from backend.app.main import create_app
from experiments.scene_version import scene_data_version
from tests.auth_flags import skip_auto_login

PASSWORD = "user-pass-9f3c"


def _ready_scene(root: Path, name: str = "demo", revision: str = "rev-1") -> Path:
    scene = root / name
    scene.mkdir(parents=True)
    arrays = {
        "dem_1m.npy": np.ones((3, 4), np.float32),
        "landuse_1m.npy": np.zeros((3, 4), np.uint8),
        "obstacle_mask_1m.npy": np.zeros((3, 4), np.uint8),
        "road_segments_local.npy": np.array([[0, 1, 4, 1]], np.float32),
        "road_segment_kind.npy": np.zeros(1, np.int8),
        "road_voronoi_1m.npy": np.zeros((3, 4), np.int64),
        "demand_points.npy": np.array([[0.5, 0.5]], np.float32),
    }
    for filename, array in arrays.items():
        np.save(scene / filename, array)
    (scene / "data_metadata.json").write_text(json.dumps({
        "scene_revision": revision,
        "dem": {"reference_crs": "EPSG:3857", "target_transform": [1, 0, 100, 0, -1, 200], "shape": [3, 4]},
    }), encoding="utf-8")
    (scene / "scene.json").write_text("{}\n", encoding="utf-8")
    return scene


def _files(scene: Path) -> dict[str, bytes]:
    return {path.relative_to(scene).as_posix(): path.read_bytes() for path in scene.rglob("*") if path.is_file()}


def _app(tmp_path: Path, database: str | None = None, output_name: str = "outputs"):
    url = database or f"sqlite:///{tmp_path / 'app.sqlite3'}"
    return create_app(url, "", experiment_root=tmp_path / output_name, favorite_db_path=tmp_path / f"{output_name}-favorites.sqlite3")


def _login(client: TestClient, username: str, password: str) -> None:
    client.cookies.clear()
    token = skip_auto_login.set(True)
    try:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    finally:
        skip_auto_login.reset(token)
    assert response.status_code == 200, response.text
    client.csrf_token = response.json()["csrf_token"]


def _add_user(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/admin/users", json={"username": username, "password": PASSWORD, "role": "user"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create(client: TestClient, scene_id: str = "demo", name: str = "方案甲") -> dict:
    response = client.post("/api/v1/workspaces", json={"base_scene_id": scene_id, "display_name": name})
    assert response.status_code == 201, response.text
    return response.json()


def test_anonymous_workspace_access_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    with TestClient(_app(tmp_path)) as client:
        token = skip_auto_login.set(True)
        try:
            client.cookies.clear()
            response = client.get("/api/v1/workspaces")
        finally:
            skip_auto_login.reset(token)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthenticated"


def test_owner_can_create_list_rename_and_another_user_cannot_touch_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    before = _files(scene)
    expected = scene_data_version(scene)
    with TestClient(_app(tmp_path)) as admin, TestClient(_app(tmp_path, output_name="outputs-b")) as other:
        owner_id = _add_user(admin, "planner-a")
        _add_user(admin, "planner-b")
        _login(admin, "planner-a", PASSWORD)
        forged = admin.post("/api/v1/workspaces", json={
            "base_scene_id": "demo", "display_name": "越权", "owner_id": "someone-else",
            "base_revision": "forged", "base_frame_id": "forged", "workspace_revision": "forged",
        })
        assert forged.status_code == 422
        first = _create(admin, name="方案甲")
        second = _create(admin, name="方案乙")
        assert first["owner_id"] == owner_id
        assert first["base_frame_id"] == expected["frame_id"]
        assert first["base_revision"] == expected["scene_revision"] == "rev-1"
        assert first["workspace_id"] != second["workspace_id"]
        assert first["workspace_revision"] != second["workspace_revision"]
        assert first["base_status"] == "current"
        assert _files(scene) == before
        listed = admin.get("/api/v1/workspaces").json()
        assert {item["display_name"] for item in listed} == {"方案甲", "方案乙"}
        filtered = admin.get("/api/v1/workspaces", params={"base_scene_id": "demo"}).json()
        assert len(filtered) == 2
        assert admin.get("/api/v1/workspaces", params={"base_scene_id": "other"}).json() == []
        denied_filter = admin.get("/api/v1/workspaces", params={"owner_id": owner_id})
        assert denied_filter.status_code == 403
        renamed = admin.patch(f"/api/v1/workspaces/{first['workspace_id']}", json={"display_name": "方案甲改名"})
        assert renamed.status_code == 200, renamed.text
        body = renamed.json()
        assert body["display_name"] == "方案甲改名"
        assert body["workspace_revision"] == first["workspace_revision"]
        assert body["base_revision"] == first["base_revision"]
        assert body["base_frame_id"] == first["base_frame_id"]
        assert _files(scene) == before

        _login(other, "planner-b", PASSWORD)
        assert other.get("/api/v1/workspaces").json() == []
        hidden = other.get(f"/api/v1/workspaces/{first['workspace_id']}")
        assert hidden.status_code == 404
        assert other.patch(f"/api/v1/workspaces/{first['workspace_id']}", json={"display_name": "被改"}).status_code == 404
        assert other.delete(f"/api/v1/workspaces/{first['workspace_id']}").status_code == 404
        assert admin.app.state.workspace_repository.get(first["workspace_id"]).display_name == "方案甲改名"

        _login(admin, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
        inspected = admin.get(f"/api/v1/workspaces/{first['workspace_id']}")
        assert inspected.status_code == 200
        assert inspected.json()["owner_id"] == owner_id
        assert admin.get("/api/v1/workspaces").json() == []
        managed = admin.get("/api/v1/workspaces", params={"owner_id": owner_id})
        assert managed.status_code == 200
        assert {item["workspace_id"] for item in managed.json()} == {first["workspace_id"], second["workspace_id"]}
        assert admin.patch(f"/api/v1/workspaces/{first['workspace_id']}", json={"display_name": "管理员改名"}).status_code == 404
        assert admin.delete(f"/api/v1/workspaces/{first['workspace_id']}").status_code == 404


def test_scene_must_be_built_and_later_changes_are_reported_without_rebinding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    with TestClient(_app(tmp_path)) as client:
        _add_user(client, "planner-a")
        _login(client, "planner-a", PASSWORD)
        created = _create(client)
        assert client.post("/api/v1/workspaces", json={"base_scene_id": "missing", "display_name": "无场景"}).status_code == 404
        assert client.post("/api/v1/workspaces", json={"base_scene_id": "../outside", "display_name": "越界"}).status_code == 422
        partial = scene.parent / "partial"
        partial.mkdir()
        (partial / "scene.json").write_text("{}\n", encoding="utf-8")
        assert client.post("/api/v1/workspaces", json={"base_scene_id": "partial", "display_name": "未建完"}).status_code == 404

        metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
        metadata["scene_revision"] = "rev-2"
        (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        changed = client.get(f"/api/v1/workspaces/{created['workspace_id']}")
        assert changed.status_code == 200
        assert changed.json()["base_status"] == "changed"
        assert changed.json()["base_revision"] == "rev-1"
        assert changed.json()["base_frame_id"] == created["base_frame_id"]
        stored = client.app.state.workspace_repository.get(created["workspace_id"])
        assert stored.base_revision == "rev-1"

        shutil.rmtree(scene)
        missing = client.get(f"/api/v1/workspaces/{created['workspace_id']}")
        assert missing.status_code == 200
        assert missing.json()["base_status"] == "missing"
        assert missing.json()["base_revision"] == "rev-1"
        assert not scene.exists()


def test_soft_delete_keeps_scene_and_experiments_and_hides_the_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    before = _files(scene)
    experiment = tmp_path / "outputs" / "kept-run"
    experiment.mkdir(parents=True)
    (experiment / "run_summary.json").write_text("{}", encoding="utf-8")
    with TestClient(_app(tmp_path)) as client:
        owner = _add_user(client, "planner-a")
        _add_user(client, "planner-b")
        _login(client, "planner-a", PASSWORD)
        created = _create(client)
        blocked = client.delete("/api/v1/scenes/demo")
        assert blocked.status_code == 403
        _login(client, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
        refused = client.delete("/api/v1/scenes/demo")
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "scene_has_workspaces"
        assert _files(scene) == before
        _login(client, "planner-a", PASSWORD)
        deleted = client.delete(f"/api/v1/workspaces/{created['workspace_id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"workspace_id": created["workspace_id"], "deleted": True}
        assert client.get("/api/v1/workspaces").json() == []
        assert client.get(f"/api/v1/workspaces/{created['workspace_id']}").status_code == 404
        assert client.delete(f"/api/v1/workspaces/{created['workspace_id']}").status_code == 404
        row = client.app.state.workspace_repository.get(created["workspace_id"])
        assert row is not None and row.deleted_at is not None and row.owner_id == owner
        assert row.workspace_revision == created["workspace_revision"]
        assert _files(scene) == before
        assert (experiment / "run_summary.json").is_file()
        _login(client, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
        assert client.get(f"/api/v1/workspaces/{created['workspace_id']}").status_code == 404
        removed = client.delete("/api/v1/scenes/demo")
        assert removed.status_code == 200, removed.text
        assert not scene.exists()
        assert (experiment / "run_summary.json").is_file()


def test_disabled_user_session_cannot_use_an_existing_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    with TestClient(_app(tmp_path)) as admin, TestClient(_app(tmp_path, output_name="outputs-user")) as user:
        user_id = _add_user(admin, "planner-a")
        _login(user, "planner-a", PASSWORD)
        created = _create(user)
        assert admin.patch(f"/api/v1/admin/users/{user_id}", json={"disabled": True}).status_code == 200
        denied = user.get(f"/api/v1/workspaces/{created['workspace_id']}")
        assert denied.status_code == 401


def test_two_api_instances_and_repeated_migration_keep_existing_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    database = f"sqlite:///{tmp_path / 'shared.sqlite3'}"
    with TestClient(_app(tmp_path, database, "outputs-a")) as first, TestClient(_app(tmp_path, database, "outputs-b")) as second:
        repository = first.app.state.job_service.repository
        admin_id = first.get("/api/v1/auth/me").json()["user"]["id"]
        repository.create_job("kept-job", "demo.algorithm", "0", {"scene_name": "demo"}, owner_id=admin_id)
        created = _create(first, name="共享库")
        first.app.state.workspace_repository.migrate()
        second.app.state.workspace_repository.migrate()
        assert repository.get_job("kept-job").owner_id == admin_id
        assert second.get(f"/api/v1/workspaces/{created['workspace_id']}").json()["display_name"] == "共享库"
        renamed = second.patch(f"/api/v1/workspaces/{created['workspace_id']}", json={"display_name": "另一实例"})
        assert renamed.status_code == 200
        assert first.get(f"/api/v1/workspaces/{created['workspace_id']}").json()["workspace_revision"] == created["workspace_revision"]
        assert first.app.state.account_store.get_user(admin_id) is not None


def test_failed_insert_does_not_leave_a_second_row(tmp_path: Path) -> None:
    repository = WorkspaceRepository(f"sqlite:///{tmp_path / 'workspaces.sqlite3'}")
    repository.migrate()
    saved = repository.insert(
        owner_id="owner", base_scene_id="demo", base_frame_id="frame", base_revision="rev", display_name="一次",
    )

    def same_id():
        return uuid.UUID(saved.workspace_id)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("backend.app.infrastructure.workspace_repository.uuid.uuid4", same_id)
    try:
        with pytest.raises(Exception):
            repository.insert(
                owner_id="owner", base_scene_id="demo", base_frame_id="frame", base_revision="rev", display_name="冲突",
            )
    finally:
        monkeypatch.undo()
    assert [item.workspace_id for item in repository.list_active("owner")] == [saved.workspace_id]


def test_rename_and_delete_stay_consistent_under_concurrency(tmp_path: Path) -> None:
    repository = WorkspaceRepository(f"sqlite:///{tmp_path / 'workspaces.sqlite3'}")
    saved = repository.insert(
        owner_id="owner", base_scene_id="demo", base_frame_id="frame", base_revision="rev", display_name="原名",
    )
    barrier = threading.Barrier(2)

    def rename() -> None:
        barrier.wait(5)
        repository.rename(saved.workspace_id, "owner", "新名")

    def remove() -> None:
        barrier.wait(5)
        repository.soft_delete(saved.workspace_id, "owner")

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(rename)
        second = pool.submit(remove)
        first.result(5)
        second.result(5)
    row = repository.get(saved.workspace_id)
    assert row is not None and row.deleted_at is not None
    assert row.workspace_revision == saved.workspace_revision
    assert row.display_name in {"原名", "新名"}
    assert repository.list_active("owner") == []
    assert repository.rename(saved.workspace_id, "other", "别人") is None
    assert repository.soft_delete(saved.workspace_id, "other") is None


def test_create_and_scene_delete_cannot_leave_a_dangling_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    entered = threading.Event()
    release = threading.Event()
    original = WorkspaceRepository.insert

    def slow_insert(self, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, **kwargs)

    monkeypatch.setattr(WorkspaceRepository, "insert", slow_insert)
    with TestClient(_app(tmp_path), raise_server_exceptions=False) as client, ThreadPoolExecutor(2) as pool:
        _add_user(client, "planner-a")
        _login(client, "planner-a", PASSWORD)
        creating = pool.submit(client.post, "/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "先创建"})
        assert entered.wait(5)
        _login(client, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
        deleting = pool.submit(client.delete, "/api/v1/scenes/demo")
        release.set()
        created = creating.result(5)
        removed = deleting.result(5)
    assert created.status_code == 201, created.text
    assert removed.status_code == 409, removed.text
    assert scene.is_dir()
    assert client.app.state.workspace_repository.count_active_for_scene("demo") == 1

    scene_after = _ready_scene(tmp_path / "scenes-after")
    monkeypatch.setenv("SCENE_ROOT", str(scene_after.parent))
    started = threading.Event()
    allow = threading.Event()
    real_rmtree = shutil.rmtree

    def slow_rmtree(path, *args, **kwargs):
        if Path(path) == scene_after:
            started.set()
            assert allow.wait(5)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", slow_rmtree)
    with TestClient(_app(tmp_path, f"sqlite:///{tmp_path / 'race.sqlite3'}", "outputs-race"), raise_server_exceptions=False) as client, ThreadPoolExecutor(2) as pool:
        deleting = pool.submit(client.delete, "/api/v1/scenes/demo")
        assert started.wait(5)
        _add_user(client, "planner-c")
        _login(client, "planner-c", PASSWORD)
        creating = pool.submit(client.post, "/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "后创建"})
        allow.set()
        assert deleting.result(5).status_code == 200
        assert creating.result(5).status_code == 404
    assert not scene_after.exists()
    assert client.app.state.workspace_repository.count_active_for_scene("demo") == 0


def _postgres_url() -> str:
    url = os.getenv("TEST_ACCOUNT_DATABASE_URL", "")
    if not url:
        pytest.skip("requires an isolated TEST_ACCOUNT_DATABASE_URL")
    parsed = urlparse(url)
    if parsed.path.lstrip("/") != "p1_account_repair" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail(f"refusing non-isolated database {url!r}")
    return url


def test_postgres_workspace_semantics_match_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = _postgres_url()
    import psycopg

    scene = _ready_scene(tmp_path / "scenes", revision="pg-rev")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    before = _files(scene)
    with psycopg.connect(url) as connection:
        connection.execute("DROP TABLE IF EXISTS planning_workspaces, sessions, login_attempts, users, jobs")
    with TestClient(_app(tmp_path, url, "pg-a")) as first, TestClient(_app(tmp_path, url, "pg-b")) as second:
        first.app.state.workspace_repository.migrate()
        created = _create(first, name="库一致")
        assert second.get(f"/api/v1/workspaces/{created['workspace_id']}").json()["base_revision"] == "pg-rev"
        renamed = second.patch(f"/api/v1/workspaces/{created['workspace_id']}", json={"display_name": "已改"})
        assert renamed.json()["workspace_revision"] == created["workspace_revision"]
        assert first.delete(f"/api/v1/workspaces/{created['workspace_id']}").status_code == 200
        assert second.get("/api/v1/workspaces").json() == []
        with psycopg.connect(url) as connection:
            row = connection.execute(
                "SELECT owner_id, deleted_at IS NOT NULL FROM planning_workspaces WHERE workspace_id = %s",
                (created["workspace_id"],),
            ).fetchone()
        assert row[1] is True
        assert _files(scene) == before
    with psycopg.connect(url) as connection:
        connection.execute("DROP TABLE IF EXISTS planning_workspaces")
