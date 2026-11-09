"""Personal planning content is saved independently of the public scene."""

from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.infrastructure.workspace_repository import EMPTY_PLAN, WorkspaceRepository
from backend.app.main import create_app
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


def _site(width: float = 210, height: float = 200) -> dict:
    return {
        "rect_w_m": width,
        "rect_h_m": height,
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
        "feasible_zones": [{"id": "zone-2", "points": [[20, 20], [30.5, 20], [30.5, 40], [20, 40]]}],
        "origin": {"x": 3.5, "y": 4.25},
    }


def _routing(span: str = "", bias: float | None = None) -> dict:
    return {
        "start": {"lng": "120.123456789", "lat": ""},
        "end": {"lng": "", "lat": ""},
        "max_span_m": span,
        "tower_radius_m": "",
        "max_turn_deg": "",
        "road_setback_m": "",
        "highway_setback_m": "",
        "no_tower_zones": [[[10.25, 10], [16, 10], [16, 18.5]]] if span else [],
        "no_cross_zones": [],
        "algorithm_overrides": {} if bias is None else {"pilot": {"rrt_goal_bias": bias}},
    }


def _put_site(client: TestClient, workspace_id: str, revision: str, site: dict | None, status_code: int = 200) -> dict:
    response = client.put(
        f"/api/v1/workspaces/{workspace_id}/plan/site",
        json={"expected_workspace_revision": revision, "site": site},
    )
    assert response.status_code == status_code, response.text
    return response.json()


def _put_routing(client: TestClient, workspace_id: str, revision: str, routing: dict | None, status_code: int = 200) -> dict:
    response = client.put(
        f"/api/v1/workspaces/{workspace_id}/plan/routing",
        json={"expected_workspace_revision": revision, "routing": routing},
    )
    assert response.status_code == status_code, response.text
    return response.json()


def test_plan_round_trip_keeps_sides_revisions_and_scene_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    before = _files(scene)
    with TestClient(_app(tmp_path)) as client:
        jobs = client.app.state.job_service.repository
        owner = client.get("/api/v1/auth/me").json()["user"]["id"]
        jobs.create_job("kept-job", "demo.algorithm", "0", {"scene_name": "demo", "rect_w_m": 77}, owner_id=owner)
        user_id = _add_user(client, "planner-a")
        _add_user(client, "planner-b")
        _login(client, "planner-a", PASSWORD)
        created = client.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "方案甲"})
        assert created.status_code == 201, created.text
        workspace_id = created.json()["workspace_id"]
        revision = created.json()["workspace_revision"]

        empty = client.get(f"/api/v1/workspaces/{workspace_id}/plan")
        assert empty.status_code == 200, empty.text
        assert empty.json()["site"] is None and empty.json()["routing"] is None
        assert empty.json()["schema_version"] == 1
        assert empty.json()["workspace_revision"] == revision
        assert empty.json()["base_status"] == "current"

        token = skip_auto_login.set(True)
        try:
            blocked = client.put(
                f"/api/v1/workspaces/{workspace_id}/plan/site",
                json={"expected_workspace_revision": revision, "site": _site()},
                headers={"X-CSRF-Token": "wrong"},
            )
        finally:
            skip_auto_login.reset(token)
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "csrf_failed"

        forged = client.put(
            f"/api/v1/workspaces/{workspace_id}/plan/site",
            json={"expected_workspace_revision": revision, "site": _site(), "owner_id": "forged", "workspace_revision": "forged"},
        )
        assert forged.status_code == 422
        saved = _put_site(client, workspace_id, revision, _site())
        assert saved["changed"] is True and saved["workspace_revision"] != revision
        again = _put_site(client, workspace_id, saved["workspace_revision"], _site())
        assert again == {"workspace_revision": saved["workspace_revision"], "changed": False}
        stale = _put_site(client, workspace_id, revision, _site(), status_code=409)
        assert stale["detail"]["code"] == "workspace_revision_conflict"
        body = client.get(f"/api/v1/workspaces/{workspace_id}/plan").json()
        assert body["workspace_revision"] == saved["workspace_revision"]
        assert body["site"]["rect_w_m"] == 210
        assert body["site"]["exclusion_zones"][0]["points"][0] == [1.25, 2]
        assert body["site"]["elevation_draft"] == "12.50"
        assert body["site"]["origin"] == {"x": 3.5, "y": 4.25}
        assert "poses" not in body["site"]

        routed = _put_routing(client, workspace_id, saved["workspace_revision"], _routing("30.5", 0.41))
        assert routed["changed"] is True
        partial = _put_routing(client, workspace_id, routed["workspace_revision"], _routing())
        assert partial["changed"] is True
        both = client.get(f"/api/v1/workspaces/{workspace_id}/plan").json()
        assert both["site"]["rect_w_m"] == 210
        assert both["routing"]["max_span_m"] == ""
        assert both["routing"]["start"]["lng"] == "120.123456789"
        assert both["routing"]["algorithm_overrides"] == {}
        resized = _put_site(client, workspace_id, both["workspace_revision"], _site(220, 180))
        kept = client.get(f"/api/v1/workspaces/{workspace_id}/plan").json()
        assert kept["site"]["rect_w_m"] == 220
        assert kept["routing"]["start"]["lng"] == "120.123456789"
        cleared = _put_routing(client, workspace_id, kept["workspace_revision"], None)
        assert client.get(f"/api/v1/workspaces/{workspace_id}/plan").json()["site"]["rect_h_m"] == 180
        assert client.get(f"/api/v1/workspaces/{workspace_id}/plan").json()["routing"] is None

        renamed = client.patch(f"/api/v1/workspaces/{workspace_id}", json={"display_name": "方案甲改名"})
        assert renamed.status_code == 200
        assert renamed.json()["workspace_revision"] == cleared["workspace_revision"]
        assert renamed.json()["base_revision"] == created.json()["base_revision"]
        assert _files(scene) == before
        stored = client.app.state.workspace_repository.get(workspace_id)
        assert stored.base_revision == created.json()["base_revision"]
        assert jobs.get_job("kept-job").config == {"scene_name": "demo", "rect_w_m": 77}
        assert "workspace_id" not in jobs.get_job("kept-job").config

        with TestClient(_app(tmp_path, output_name="outputs-b")) as other:
            _login(other, "planner-b", PASSWORD)
            assert other.get(f"/api/v1/workspaces/{workspace_id}/plan").status_code == 404
            hidden = other.put(
                f"/api/v1/workspaces/{workspace_id}/plan/site",
                json={"expected_workspace_revision": cleared["workspace_revision"], "site": _site(1, 1)},
            )
            assert hidden.status_code == 404
        _login(client, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
        inspected = client.get(f"/api/v1/workspaces/{workspace_id}/plan")
        assert inspected.status_code == 200
        assert inspected.json()["site"]["rect_w_m"] == 220
        refused = client.put(
            f"/api/v1/workspaces/{workspace_id}/plan/site",
            json={"expected_workspace_revision": cleared["workspace_revision"], "site": _site(1, 1)},
        )
        assert refused.status_code == 404
        assert client.app.state.workspace_repository.get(workspace_id).owner_id == user_id

        _login(client, "planner-a", PASSWORD)
        metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
        metadata["scene_revision"] = "rev-2"
        (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        changed = _put_site(client, workspace_id, cleared["workspace_revision"], _site(9, 9), status_code=409)
        assert changed["detail"]["code"] == "workspace_base_changed"
        assert client.get(f"/api/v1/workspaces/{workspace_id}/plan").json()["base_status"] == "changed"
        assert client.get(f"/api/v1/workspaces/{workspace_id}/plan").json()["site"]["rect_w_m"] == 220
        assert client.app.state.workspace_repository.get(workspace_id).base_revision == created.json()["base_revision"]
        metadata["scene_revision"] = "rev-1"
        (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        assert _files(scene) == before

        removed = client.delete(f"/api/v1/workspaces/{workspace_id}")
        assert removed.status_code == 200
        deleted = _put_site(client, workspace_id, cleared["workspace_revision"], _site(), status_code=404)
        assert deleted["detail"]["code"] == "workspace_not_found"
        shutil.rmtree(scene)
        assert client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 404


def test_missing_base_disabled_user_and_invalid_plan_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    with TestClient(_app(tmp_path)) as admin, TestClient(_app(tmp_path, output_name="outputs-user")) as user:
        user_id = _add_user(admin, "planner-a")
        _login(user, "planner-a", PASSWORD)
        created = user.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "方案甲"}).json()
        short = _site()
        short["exclusion_zones"] = [{"id": "zone-1", "points": [[1, 1], [2, 2]]}]
        assert user.put(
            f"/api/v1/workspaces/{created['workspace_id']}/plan/site",
            json={"expected_workspace_revision": created["workspace_revision"], "site": short},
        ).status_code == 422
        huge = _site()
        huge["feasible_zones"] = []
        huge["exclusion_zones"] = []
        for index in range(100):
            center = 100 + index * 3
            ring = [[center + math.cos(2 * math.pi * step / 120), center + math.sin(2 * math.pi * step / 120)] for step in range(120)]
            huge["exclusion_zones"].append({"id": f"bulk-{index}", "points": ring})
        oversized = user.put(
            f"/api/v1/workspaces/{created['workspace_id']}/plan/site",
            json={"expected_workspace_revision": created["workspace_revision"], "site": huge},
        )
        assert oversized.status_code == 413, oversized.text
        assert oversized.json()["detail"]["code"] == "plan_too_large"
        crossed = _routing("1")
        crossed["no_tower_zones"] = [[[0, 0], [1, 1], [0, 1], [1, 0]]]
        assert user.put(
            f"/api/v1/workspaces/{created['workspace_id']}/plan/routing",
            json={"expected_workspace_revision": created["workspace_revision"], "routing": crossed},
        ).status_code == 422
        far = _site()
        far["origin"] = {"x": 1e20, "y": 0}
        assert user.put(
            f"/api/v1/workspaces/{created['workspace_id']}/plan/site",
            json={"expected_workspace_revision": created["workspace_revision"], "site": far},
        ).status_code == 422
        assert user.get(f"/api/v1/workspaces/{created['workspace_id']}/plan").json()["site"] is None

        shutil.rmtree(scene)
        missing = _put_site(user, created["workspace_id"], created["workspace_revision"], _site(), status_code=409)
        assert missing["detail"]["code"] == "workspace_base_missing"
        assert not scene.exists()
        readable = user.get(f"/api/v1/workspaces/{created['workspace_id']}/plan")
        assert readable.status_code == 200
        assert readable.json()["base_status"] == "missing"

        assert admin.patch(f"/api/v1/admin/users/{user_id}", json={"disabled": True}).status_code == 200
        denied = user.put(
            f"/api/v1/workspaces/{created['workspace_id']}/plan/site",
            json={"expected_workspace_revision": created["workspace_revision"], "site": _site()},
        )
        assert denied.status_code == 401


def test_concurrent_saves_from_two_instances_do_not_lose_an_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready_scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    database = f"sqlite:///{tmp_path / 'shared.sqlite3'}"
    with TestClient(_app(tmp_path, database, "outputs-a")) as first, TestClient(_app(tmp_path, database, "outputs-b")) as second:
        _add_user(first, "planner-a")
        _login(first, "planner-a", PASSWORD)
        _login(second, "planner-a", PASSWORD)
        created = first.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "共享"}).json()
        barrier = threading.Barrier(2)

        def send(client: TestClient, width: float):
            barrier.wait(5)
            return client.put(
                f"/api/v1/workspaces/{created['workspace_id']}/plan/site",
                json={"expected_workspace_revision": created["workspace_revision"], "site": _site(width, 200)},
            )

        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(send, first, 10), pool.submit(send, second, 20)]
            statuses = sorted(item.result(5).status_code for item in results)
        assert statuses == [200, 409]
        winner = first.get(f"/api/v1/workspaces/{created['workspace_id']}/plan").json()
        assert winner["site"]["rect_w_m"] in {10, 20}
        assert winner["routing"] is None
        assert winner["workspace_revision"] != created["workspace_revision"]
        routed = second.put(
            f"/api/v1/workspaces/{created['workspace_id']}/plan/routing",
            json={"expected_workspace_revision": winner["workspace_revision"], "routing": _routing("15")},
        )
        assert routed.status_code == 200, routed.text
        combined = first.get(f"/api/v1/workspaces/{created['workspace_id']}/plan").json()
        assert combined["site"]["rect_w_m"] == winner["site"]["rect_w_m"]
        assert combined["routing"]["max_span_m"] == "15"


def test_content_columns_can_be_added_twice_without_changing_an_old_row(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
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
    connection.execute(
        "INSERT INTO planning_workspaces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        ("ws-1", "owner", "demo", "frame", "rev", "revision-a", "旧行", "t0", "t0"),
    )
    connection.commit()
    connection.close()
    repository = WorkspaceRepository(f"sqlite:///{path}")
    repository.migrate()
    row = repository.get("ws-1")
    assert row is not None
    assert row.workspace_revision == "revision-a"
    assert row.content_schema_version == 1
    assert json.loads(row.content_json) == json.loads(EMPTY_PLAN)
    repository.migrate()
    assert repository.get("ws-1").workspace_revision == "revision-a"


def _postgres_url() -> str:
    url = os.getenv("TEST_ACCOUNT_DATABASE_URL", "")
    if not url:
        pytest.skip("requires an isolated TEST_ACCOUNT_DATABASE_URL")
    parsed = urlparse(url)
    if parsed.path.lstrip("/") != "p1_account_repair" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail(f"refusing non-isolated database {url!r}")
    return url


def test_postgres_plan_matches_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = _postgres_url()
    import psycopg

    scene = _ready_scene(tmp_path / "scenes", revision="pg-rev")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    before = _files(scene)
    with psycopg.connect(url) as connection:
        connection.execute(
            "DROP TABLE IF EXISTS planning_workspace_revisions, planning_workspaces, sessions, login_attempts, users, jobs"
        )
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
            "INSERT INTO planning_workspaces VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)",
            ("legacy", "owner", "demo", "frame", "pg-rev", "legacy-rev", "旧行", "t0", "t0"),
        )
    with TestClient(_app(tmp_path, url, "pg-a")) as first, TestClient(_app(tmp_path, url, "pg-b")) as second:
        legacy = first.app.state.workspace_repository.get("legacy")
        assert legacy.workspace_revision == "legacy-rev"
        assert json.loads(legacy.content_json)["site"] is None
        first.app.state.workspace_repository.migrate()
        assert first.app.state.workspace_repository.get("legacy").workspace_revision == "legacy-rev"
        created = first.post("/api/v1/workspaces", json={"base_scene_id": "demo", "display_name": "库一致"})
        assert created.status_code == 201, created.text
        workspace_id = created.json()["workspace_id"]
        saved = _put_site(first, workspace_id, created.json()["workspace_revision"], _site())
        routed = _put_routing(second, workspace_id, saved["workspace_revision"], _routing("4"))
        seen = first.get(f"/api/v1/workspaces/{workspace_id}/plan").json()
        assert seen["site"]["rect_w_m"] == 210 and seen["routing"]["max_span_m"] == "4"
        assert seen["workspace_revision"] == routed["workspace_revision"]
        barrier = threading.Barrier(2)

        def send(client: TestClient, width: float):
            barrier.wait(5)
            return client.put(
                f"/api/v1/workspaces/{workspace_id}/plan/site",
                json={"expected_workspace_revision": seen["workspace_revision"], "site": _site(width, 200)},
            )

        with ThreadPoolExecutor(2) as pool:
            raced = [pool.submit(send, first, 30), pool.submit(send, second, 40)]
            assert sorted(item.result(5).status_code for item in raced) == [200, 409]
        raced_plan = first.get(f"/api/v1/workspaces/{workspace_id}/plan").json()
        assert raced_plan["site"]["rect_w_m"] in {30, 40}
        assert raced_plan["routing"]["max_span_m"] == "4"
        conflict = second.put(
            f"/api/v1/workspaces/{workspace_id}/plan/site",
            json={"expected_workspace_revision": created.json()["workspace_revision"], "site": _site(1, 1)},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "workspace_revision_conflict"
        final = first.get(f"/api/v1/workspaces/{workspace_id}/plan").json()
        assert final["site"]["rect_w_m"] == raced_plan["site"]["rect_w_m"]
        assert final["routing"]["max_span_m"] == "4"
        assert final["workspace_revision"] == raced_plan["workspace_revision"]
        assert _files(scene) == before
    with psycopg.connect(url) as connection:
        connection.execute("DROP TABLE IF EXISTS planning_workspace_revisions, planning_workspaces")
