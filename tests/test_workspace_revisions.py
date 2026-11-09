"""Immutable planning revisions stay readable after the current workspace moves on."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from backend.app.domain.planning_content import SitePlan, canonical_plan, plan_sha256
from backend.app.infrastructure.workspace_repository import (
    EMPTY_PLAN,
    RevisionConsistencyError,
    WorkspaceRepository,
    _Conn,
)
from backend.app.main import create_app
from tests.auth_flags import skip_auto_login

PASSWORD = "user-pass-9f3c"


def _ready_scene(root: Path, name: str = "demo", revision: str = "rev-1") -> Path:
    import numpy as np

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


def _site(width: float = 210) -> dict:
    return {
        "rect_w_m": width,
        "rect_h_m": 200,
        "field_policy": "costly",
        "mountain_policy": "blocked",
        "field_cost": 0.3,
        "include_demand": True,
        "diagonal_access": False,
        "road_setback_m": 8,
        "water_setback_m": 9,
        "highway_setback_m": 11,
        "elevation_enabled": True,
        "elevation_draft": "12.50",
        "exclusion_zones": [{"id": "zone-1", "points": [[1.25, 2], [8.5, 2], [8.5, 9.75]]}],
        "feasible_zones": [],
        "origin": {"x": 3.5, "y": 4.25},
    }


def _routing(span: str = "15") -> dict:
    return {
        "start": {"lng": "120.123456789", "lat": ""},
        "end": {"lng": "", "lat": ""},
        "max_span_m": span,
        "tower_radius_m": "",
        "max_turn_deg": "",
        "road_setback_m": "",
        "highway_setback_m": "",
        "no_tower_zones": [],
        "no_cross_zones": [],
        "algorithm_overrides": {},
    }


def _put_site(client: TestClient, workspace_id: str, revision: str, site: dict | None, status_code: int = 200) -> dict:
    response = client.put(
        f"/api/v1/workspaces/{workspace_id}/plan/site",
        json={"expected_workspace_revision": revision, "site": site},
    )
    assert response.status_code == status_code, response.text
    return response.json()


def _legacy_table(path: Path, rows: list[tuple]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE planning_workspaces (
            workspace_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            base_scene_id TEXT NOT NULL,
            base_frame_id TEXT NOT NULL,
            base_revision TEXT NOT NULL,
            workspace_revision TEXT NOT NULL,
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )"""
    )
    connection.executemany(
        "INSERT INTO planning_workspaces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()


def test_canonical_hash_covers_the_whole_document_and_ignores_key_order() -> None:
    first = canonical_plan({"schema_version": 1, "site": None, "routing": None})
    second = canonical_plan({"routing": None, "site": None, "schema_version": 1})
    assert first == second == EMPTY_PLAN
    assert plan_sha256(first) == plan_sha256(second)
    changed = canonical_plan({"routing": None, "schema_version": 1, "site": _site(4)})
    assert plan_sha256(changed) != plan_sha256(first)


def test_new_workspace_revision_matches_the_current_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    before = _files(scene)
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    with TestClient(_app(tmp_path)) as client:
        _add_user(client, "planner-a")
        _login(client, "planner-a", PASSWORD)
        created = client.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "初始"}).json()
        plan = client.get(f"/api/v1/workspaces/{created['workspace_id']}/plan").json()
        listed = client.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions")
        assert listed.status_code == 200, listed.text
        assert [item["revision_id"] for item in listed.json()] == [created["workspace_revision"]]
        detail = client.get(
            f"/api/v1/workspaces/{created['workspace_id']}/revisions/{created['workspace_revision']}"
        ).json()
        assert detail["site"] == plan["site"] is None
        assert detail["routing"] == plan["routing"] is None
        assert detail["content_sha256"] == plan_sha256(EMPTY_PLAN)
        assert detail["base_revision"] == created["base_revision"]
        assert detail["base_frame_id"] == created["base_frame_id"]
        assert _files(scene) == before


def test_content_rules_keep_one_history_per_real_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    before = _files(scene)
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    with TestClient(_app(tmp_path)) as client:
        _add_user(client, "planner-a")
        _login(client, "planner-a", PASSWORD)
        created = client.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "方案"}).json()
        workspace_id = created["workspace_id"]
        original = client.get(f"/api/v1/workspaces/{workspace_id}").json()
        same = _put_site(client, workspace_id, created["workspace_revision"], None)
        assert same == {"workspace_revision": created["workspace_revision"], "changed": False}
        assert client.get(f"/api/v1/workspaces/{workspace_id}").json()["updated_at"] == original["updated_at"]
        assert len(client.get(f"/api/v1/workspaces/{workspace_id}/revisions").json()) == 1
        saved = _put_site(client, workspace_id, created["workspace_revision"], _site())
        assert saved["changed"] is True
        routed = client.put(
            f"/api/v1/workspaces/{workspace_id}/plan/routing",
            json={"expected_workspace_revision": saved["workspace_revision"], "routing": _routing()},
        )
        assert routed.status_code == 200, routed.text
        repeated = client.put(
            f"/api/v1/workspaces/{workspace_id}/plan/routing",
            json={"expected_workspace_revision": routed.json()["workspace_revision"], "routing": _routing()},
        )
        assert repeated.json()["changed"] is False
        renamed = client.patch(f"/api/v1/workspaces/{workspace_id}", json={"display_name": "只改名"})
        assert renamed.status_code == 200
        assert renamed.json()["workspace_revision"] == routed.json()["workspace_revision"]
        history = client.get(f"/api/v1/workspaces/{workspace_id}/revisions").json()
        assert [item["revision_id"] for item in history] == [
            created["workspace_revision"], saved["workspace_revision"], routed.json()["workspace_revision"],
        ]
        first = client.get(f"/api/v1/workspaces/{workspace_id}/revisions/{saved['workspace_revision']}").json()
        second = client.get(f"/api/v1/workspaces/{workspace_id}/revisions/{routed.json()['workspace_revision']}").json()
        assert first["site"]["rect_w_m"] == 210 and first["routing"] is None
        assert second["site"]["rect_w_m"] == 210 and second["routing"]["max_span_m"] == "15"
        stale = _put_site(client, workspace_id, created["workspace_revision"], _site(1), 409)
        assert stale["detail"]["code"] == "workspace_revision_conflict"
        assert len(client.get(f"/api/v1/workspaces/{workspace_id}/revisions").json()) == 3
        removed = client.delete(f"/api/v1/workspaces/{workspace_id}")
        assert removed.status_code == 200
        assert client.get(f"/api/v1/workspaces/{workspace_id}/revisions").status_code == 404
        stored = client.app.state.workspace_repository
        assert stored.get_revision(workspace_id, created["workspace_revision"]) is not None
        assert len(stored.list_revisions(workspace_id)) == 3
        hidden = client.put(
            f"/api/v1/workspaces/{workspace_id}/plan/site",
            json={"expected_workspace_revision": routed.json()["workspace_revision"], "site": _site(2)},
        )
        assert hidden.status_code == 404
        assert len(stored.list_revisions(workspace_id)) == 3
        assert _files(scene) == before


def test_other_users_cannot_read_or_invent_revisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    with TestClient(_app(tmp_path)) as owner, TestClient(_app(tmp_path, output_name="outputs-b")) as other:
        user_id = _add_user(owner, "planner-a")
        _add_user(owner, "planner-b")
        _login(owner, "planner-a", PASSWORD)
        _login(other, "planner-b", PASSWORD)
        created = owner.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "甲"}).json()
        saved = _put_site(owner, created["workspace_id"], created["workspace_revision"], _site())
        again = _put_site(owner, created["workspace_id"], saved["workspace_revision"], _site(30))
        for revision in (created["workspace_revision"], saved["workspace_revision"], again["workspace_revision"]):
            denied = other.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions/{revision}")
            assert denied.status_code == 404
        assert other.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions").status_code == 404
        assert other.put(
            f"/api/v1/workspaces/{created['workspace_id']}/plan/site",
            json={"expected_workspace_revision": again["workspace_revision"], "site": _site(1)},
        ).status_code == 404
        forged = owner.post("/api/v1/workspaces", json={
            "base_scene_id": "demo", "display_name": "伪造", "revision_id": "client-rev", "owner_id": "other",
        })
        assert forged.status_code == 422
        extra = owner.put(
            f"/api/v1/workspaces/{created['workspace_id']}/plan/site",
            json={
                "expected_workspace_revision": again["workspace_revision"],
                "site": _site(),
                "content_sha256": "0" * 64,
                "revision_id": "client-rev",
            },
        )
        assert extra.status_code == 422
        _login(other, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
        listed = other.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions")
        assert listed.status_code == 200
        assert len(listed.json()) == 3
        detail = other.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions/{saved['workspace_revision']}")
        assert detail.status_code == 200
        assert detail.json()["site"]["rect_w_m"] == 210
        assert other.put(
            f"/api/v1/workspaces/{created['workspace_id']}/revisions/{saved['workspace_revision']}",
            json={"site": None},
        ).status_code == 405
        assert other.patch(f"/api/v1/admin/users/{user_id}", json={"disabled": True}).status_code == 200
        assert owner.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions").status_code == 401


def test_concurrent_saves_leave_one_revision_and_failed_writes_roll_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    database = f"sqlite:///{tmp_path / 'shared.sqlite3'}"
    with TestClient(_app(tmp_path, database, "outputs-a")) as first, TestClient(_app(tmp_path, database, "outputs-b")) as second:
        _add_user(first, "planner-a")
        _login(first, "planner-a", PASSWORD)
        _login(second, "planner-a", PASSWORD)
        created = first.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "并发"}).json()
        barrier = threading.Barrier(2)

        def send(client: TestClient, width: float):
            barrier.wait(5)
            return client.put(
                f"/api/v1/workspaces/{created['workspace_id']}/plan/site",
                json={"expected_workspace_revision": created["workspace_revision"], "site": _site(width)},
            )

        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(send, first, 10), pool.submit(send, second, 20)]
            assert sorted(item.result(5).status_code for item in results) == [200, 409]
        history = first.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions").json()
        assert len(history) == 2
        seen = second.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions/{history[-1]['revision_id']}").json()
        again = first.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions/{history[-1]['revision_id']}").json()
        assert seen == again
        assert seen["site"]["rect_w_m"] in {10, 20}

    repository = WorkspaceRepository(database)
    current = repository.get(created["workspace_id"])
    original_execute = _Conn.execute

    def fail_insert(self, sql, params=()):
        if "INSERT INTO planning_workspace_revisions" in sql:
            raise RuntimeError("insert failed")
        return original_execute(self, sql, params)

    monkeypatch.setattr(_Conn, "execute", fail_insert)
    with pytest.raises(RuntimeError, match="insert failed"):
        repository.save_plan_side(current.workspace_id, current.owner_id, current.workspace_revision, "site", _site(7))
    monkeypatch.setattr(_Conn, "execute", original_execute)
    assert repository.get(current.workspace_id).workspace_revision == current.workspace_revision
    assert len(repository.list_revisions(current.workspace_id)) == 2

    original_query = _Conn.query

    def fail_update(self, sql, params=()):
        if sql.lstrip().startswith("UPDATE"):
            raise RuntimeError("update failed")
        return original_query(self, sql, params)

    monkeypatch.setattr(_Conn, "query", fail_update)
    with pytest.raises(RuntimeError, match="update failed"):
        repository.save_plan_side(current.workspace_id, current.owner_id, current.workspace_revision, "site", _site(8))
    monkeypatch.setattr(_Conn, "query", original_query)
    assert repository.get(current.workspace_id).content_json == current.content_json
    assert [item.revision_id for item in repository.list_revisions(current.workspace_id)] == [
        row["revision_id"] for row in history
    ]


def test_sqlite_rejects_revision_mutation_and_a_bad_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    database = tmp_path / "app.sqlite3"
    with TestClient(_app(tmp_path, f"sqlite:///{database}")) as client:
        _add_user(client, "planner-a")
        _login(client, "planner-a", PASSWORD)
        created = client.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "保护"}).json()
        workspace_id = created["workspace_id"]
    connection = sqlite3.connect(database)
    for sql in (
        "UPDATE planning_workspace_revisions SET content_json = '{}'",
        "UPDATE planning_workspace_revisions SET content_sha256 = '0'",
        "UPDATE planning_workspace_revisions SET owner_id = 'other'",
        "UPDATE planning_workspace_revisions SET base_revision = 'other'",
        "DELETE FROM planning_workspace_revisions",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(sql)
        connection.rollback()
    forged = canonical_plan({"routing": None, "schema_version": 1, "site": _site(12345.25)})
    connection.execute(
        """INSERT INTO planning_workspace_revisions
           (workspace_id, revision_id, owner_id, base_scene_id, base_frame_id, base_revision,
            schema_version, content_json, content_sha256, created_at)
           VALUES (?, 'forged', 'ignored', 'demo', 'frame', 'rev', 1, ?, ?, 't-same')""",
        (workspace_id, forged, "0" * 64),
    )
    connection.commit()
    connection.close()
    with TestClient(_app(tmp_path, f"sqlite:///{database}")) as client:
        _login(client, "planner-a", PASSWORD)
        detail = client.get(f"/api/v1/workspaces/{workspace_id}/revisions/forged")
        listed = client.get(f"/api/v1/workspaces/{workspace_id}/revisions")
    assert detail.status_code == 422 and detail.json()["detail"]["code"] == "plan_hash_mismatch"
    assert listed.status_code == 422
    assert "12345.25" not in detail.text
    assert "12345.25" not in listed.text
    with pytest.raises(Exception):
        WorkspaceRepository(f"sqlite:///{database}").get_revision(workspace_id, "forged")


def test_legacy_backfill_keeps_only_the_current_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    _legacy_table(path, [
        ("ws-live", "owner-a", "demo", "frame-a", "base-a", "revision-live", "活着", "t0", "t1", None),
        ("ws-gone", "owner-a", "demo", "frame-a", "base-a", "revision-gone", "已删", "t0", "t1", "t2"),
    ])
    repository = WorkspaceRepository(f"sqlite:///{path}")
    repository.migrate()
    live = repository.get("ws-live")
    gone = repository.get("ws-gone")
    assert live.workspace_revision == "revision-live"
    assert live.owner_id == "owner-a" and live.base_revision == "base-a" and live.base_frame_id == "frame-a"
    assert live.created_at == "t0" and live.updated_at == "t1" and live.deleted_at is None
    assert gone.deleted_at == "t2" and gone.workspace_revision == "revision-gone"
    assert [item.revision_id for item in repository.list_revisions("ws-live")] == ["revision-live"]
    assert [item.revision_id for item in repository.list_revisions("ws-gone")] == ["revision-gone"]
    assert repository.get_revision("ws-gone", "revision-gone").content_sha256 == plan_sha256(EMPTY_PLAN)
    repository.migrate()
    assert len(repository.list_revisions("ws-live")) == 1
    raw = sqlite3.connect(path)
    replacement = canonical_plan({"routing": None, "schema_version": 1, "site": _site(6)})
    raw.execute("UPDATE planning_workspaces SET content_json = ? WHERE workspace_id = 'ws-live'", (replacement,))
    raw.commit()
    raw.close()
    with pytest.raises(RevisionConsistencyError):
        repository.migrate()
    assert repository.get_revision("ws-live", "revision-live").content_json == EMPTY_PLAN
    assert json.loads(repository.get("ws-live").content_json)["site"]["rect_w_m"] == 6


def test_concurrent_migration_does_not_duplicate_history(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    _legacy_table(path, [
        ("ws-1", "owner", "demo", "frame", "base", "revision-a", "旧", "t0", "t0", None),
    ])
    barrier = threading.Barrier(2)

    def open_repository():
        barrier.wait(5)
        return WorkspaceRepository(f"sqlite:///{path}")

    with ThreadPoolExecutor(2) as pool:
        opened = [pool.submit(open_repository) for _ in range(2)]
        assert all(item.result(5).get("ws-1").workspace_revision == "revision-a" for item in opened)
    assert len(WorkspaceRepository(f"sqlite:///{path}").list_revisions("ws-1")) == 1


def test_failed_revision_insert_does_not_leave_a_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = WorkspaceRepository(f"sqlite:///{tmp_path / 'workspaces.sqlite3'}")
    original = _Conn.execute

    def fail_insert(self, sql, params=()):
        if "INSERT INTO planning_workspace_revisions" in sql:
            raise RuntimeError("revision insert failed")
        return original(self, sql, params)

    monkeypatch.setattr(_Conn, "execute", fail_insert)
    with pytest.raises(RuntimeError, match="revision insert failed"):
        repository.insert(
            owner_id="owner", base_scene_id="demo", base_frame_id="frame", base_revision="rev", display_name="半成品",
        )
    assert repository.list_active("owner") == []


def test_history_stays_readable_after_the_public_scene_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    with TestClient(_app(tmp_path)) as client:
        _add_user(client, "planner-a")
        _login(client, "planner-a", PASSWORD)
        created = client.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "旧基线"}).json()
        saved = _put_site(client, created["workspace_id"], created["workspace_revision"], _site())
        metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
        metadata["scene_revision"] = "rev-2"
        (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        detail = client.get(f"/api/v1/workspaces/{created['workspace_id']}/revisions/{saved['workspace_revision']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["base_revision"] == created["base_revision"]
        assert detail.json()["site"]["rect_w_m"] == 210
        blocked = _put_site(client, created["workspace_id"], saved["workspace_revision"], _site(9), 409)
        assert blocked["detail"]["code"] == "workspace_base_changed"
        stored = client.app.state.workspace_repository.get_revision(created["workspace_id"], saved["workspace_revision"])
        assert stored.base_revision == created["base_revision"]


def test_reordered_keys_do_not_create_another_revision(tmp_path: Path) -> None:
    repository = WorkspaceRepository(f"sqlite:///{tmp_path / 'workspaces.sqlite3'}")
    record = repository.insert(
        owner_id="owner", base_scene_id="demo", base_frame_id="frame", base_revision="rev", display_name="顺序",
    )
    site = SitePlan.model_validate(_site()).model_dump(mode="json")
    updated, changed = repository.save_plan_side(record.workspace_id, "owner", record.workspace_revision, "site", site)
    assert changed is True
    reversed_site = {key: site[key] for key in reversed(site)}
    again, changed_again = repository.save_plan_side(
        record.workspace_id, "owner", updated.workspace_revision, "site", reversed_site,
    )
    assert changed_again is False
    assert again.workspace_revision == updated.workspace_revision
    assert again.updated_at == updated.updated_at
    assert len(repository.list_revisions(record.workspace_id)) == 2


def _postgres_url() -> str:
    url = os.getenv("TEST_ACCOUNT_DATABASE_URL", "")
    if not url:
        pytest.skip("requires an isolated TEST_ACCOUNT_DATABASE_URL")
    parsed = urlparse(url)
    if parsed.path.lstrip("/") != "p1_account_repair" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail(f"refusing non-isolated database {url!r}")
    return url


def test_postgres_revisions_match_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = _postgres_url()
    import psycopg

    scene = _ready_scene(tmp_path / "scenes", revision="pg-rev")
    before = _files(scene)
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    with psycopg.connect(url) as connection:
        connection.execute("DROP TABLE IF EXISTS planning_workspace_revisions, planning_workspaces, sessions, login_attempts, users, jobs")
        connection.execute("DROP FUNCTION IF EXISTS planning_workspace_revisions_immutable()")
        connection.execute(
            """CREATE TABLE planning_workspaces (
                workspace_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                base_scene_id TEXT NOT NULL,
                base_frame_id TEXT NOT NULL,
                base_revision TEXT NOT NULL,
                workspace_revision TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO planning_workspaces VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ("legacy", "owner-a", "demo", "frame-a", "pg-rev", "legacy-rev", "旧行", "t0", "t1", None),
        )
        connection.execute(
            "INSERT INTO planning_workspaces VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ("gone", "owner-a", "demo", "frame-a", "pg-rev", "gone-rev", "已删", "t0", "t1", "t2"),
        )
    barrier = threading.Barrier(2)

    def open_repository():
        barrier.wait(5)
        return WorkspaceRepository(url)

    with ThreadPoolExecutor(2) as pool:
        opened = [item.result(5) for item in (pool.submit(open_repository), pool.submit(open_repository))]
    assert all(item.get("legacy").workspace_revision == "legacy-rev" for item in opened)
    assert len(opened[0].list_revisions("legacy")) == 1
    assert opened[0].get("gone").deleted_at == "t2"
    assert opened[0].get_revision("gone", "gone-rev") is not None
    opened[0].migrate()
    assert len(opened[0].list_revisions("legacy")) == 1
    with psycopg.connect(url) as connection:
        for sql in (
            "UPDATE planning_workspace_revisions SET content_json = '{}'",
            "UPDATE planning_workspace_revisions SET content_sha256 = '0'",
            "UPDATE planning_workspace_revisions SET owner_id = 'other'",
            "UPDATE planning_workspace_revisions SET base_revision = 'other'",
            "DELETE FROM planning_workspace_revisions",
        ):
            with pytest.raises(Exception, match="immutable"):
                connection.execute(sql)
            connection.rollback()
    with TestClient(_app(tmp_path, url, "pg-a")) as first, TestClient(_app(tmp_path, url, "pg-b")) as second:
        created = first.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "库一致"})
        assert created.status_code == 201, created.text
        body = created.json()
        saved = _put_site(first, body["workspace_id"], body["workspace_revision"], _site())
        detail = second.get(f"/api/v1/workspaces/{body['workspace_id']}/revisions/{saved['workspace_revision']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["base_revision"] == "pg-rev"
        assert detail.json()["site"]["rect_w_m"] == 210
        assert _files(scene) == before
    with psycopg.connect(url) as connection:
        connection.execute("DROP TABLE IF EXISTS planning_workspace_revisions, planning_workspaces")
        connection.execute("DROP FUNCTION IF EXISTS planning_workspace_revisions_immutable()")
