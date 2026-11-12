"""PostgreSQL persistence through a separate API process. No in-memory queue."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from tests.integration.p2h2.api_process import ApiProcess
from tests.integration.p2h2.scenes import routing, site, write_scene

PASSWORD = "user-pass-9f3c"
ADMIN_PASSWORD = "p2h2-admin-pass-9f3c"
REDIS_CLOSED = "redis://127.0.0.1:9/15"


def _database_url() -> str:
    url = os.getenv("P2H2_DATABASE_URL", "")
    parsed = urlparse(url)
    if parsed.scheme not in {"postgresql", "postgres"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.skip("需要本机隔离的 PostgreSQL")
    if parsed.path.lstrip("/") != "p2h2":
        pytest.fail("拒绝连接 p2h2 以外的数据库")
    return url


def _login(client: httpx.Client, username: str, password: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def _reset(url: str) -> None:
    import psycopg

    with psycopg.connect(url) as connection:
        connection.execute(
            """DROP TABLE IF EXISTS
            base_snapshot_references, base_scene_snapshots, planning_workspace_revisions,
            planning_workspaces, sessions, login_attempts, users, jobs"""
        )


def _rows(url: str, sql: str) -> list[tuple]:
    import psycopg

    with psycopg.connect(url) as connection:
        return connection.execute(sql).fetchall()


def test_postgres_keeps_two_users_across_an_api_restart(tmp_path: Path) -> None:
    url = _database_url()
    _reset(url)
    write_scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    write_scene(tmp_path / "scenes", "scene-y", 230000, "rev-y1")
    lock = Path("outputs/user-state/worker.lock")
    lock_before = lock.stat().st_mtime_ns if lock.exists() else None
    api = ApiProcess(tmp_path, url, REDIS_CLOSED)
    api.start(bootstrap=True)
    try:
        with api.client() as admin, api.client() as alice, api.client() as bob:
            _login(admin, "p2h2-admin", ADMIN_PASSWORD)
            user_a = admin.post("/api/v1/admin/users", json={"username": "user-a", "password": PASSWORD, "role": "user"})
            user_b = admin.post("/api/v1/admin/users", json={"username": "user-b", "password": PASSWORD, "role": "user"})
            assert user_a.status_code == 201 and user_b.status_code == 201
            owner_a, owner_b = user_a.json()["id"], user_b.json()["id"]
            _login(alice, "user-a", PASSWORD)
            _login(bob, "user-b", PASSWORD)
            assert alice.cookies.get("site_session") != bob.cookies.get("site_session")
            rejected = bob.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "越权"}, headers={"X-CSRF-Token": alice.headers["X-CSRF-Token"]})
            assert rejected.status_code == 403
            ax = alice.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "AX"}).json()
            bx = bob.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "BX"}).json()
            ay = alice.post("/api/v1/workspaces", json={"base_scene_id": "scene-y", "display_name": "AY"}).json()
            by = bob.post("/api/v1/workspaces", json={"base_scene_id": "scene-y", "display_name": "BY"}).json()
            saved_a = alice.put(f"/api/v1/workspaces/{ax['workspace_id']}/plan/site", json={"expected_workspace_revision": ax["workspace_revision"], "site": site(20, 1, 0.4, "blocked")})
            saved_b = bob.put(f"/api/v1/workspaces/{bx['workspace_id']}/plan/site", json={"expected_workspace_revision": bx["workspace_revision"], "site": site(28, 4, 2.0, "allowed")})
            assert saved_a.status_code == 200 and saved_b.status_code == 200, (saved_a.text, saved_b.text)
            ax["workspace_revision"] = saved_a.json()["workspace_revision"]
            route_ay = routing(230000, [1, 3], [5, 4], "44")
            route_by = routing(230000, [1, 1], [4, 5], "50")
            saved_ay = alice.put(f"/api/v1/workspaces/{ay['workspace_id']}/plan/routing", json={"expected_workspace_revision": ay["workspace_revision"], "routing": route_ay})
            saved_by = bob.put(f"/api/v1/workspaces/{by['workspace_id']}/plan/routing", json={"expected_workspace_revision": by["workspace_revision"], "routing": route_by})
            assert saved_ay.status_code == 200 and saved_by.status_code == 200
            assert bob.get(f"/api/v1/workspaces/{ax['workspace_id']}").status_code == 404
            assert alice.get(f"/api/v1/workspaces/{bx['workspace_id']}").status_code == 404
            revision_b = bob.get(f"/api/v1/workspaces/{bx['workspace_id']}").json()["workspace_revision"]
            changed = alice.put(f"/api/v1/workspaces/{ax['workspace_id']}/plan/site", json={"expected_workspace_revision": ax["workspace_revision"], "site": site(21, 1, 0.4, "blocked")})
            assert changed.status_code == 200
            assert bob.get(f"/api/v1/workspaces/{bx['workspace_id']}").json()["workspace_revision"] == revision_b
            listed_x = {item["workspace_id"] for item in alice.get("/api/v1/workspaces", params={"base_scene_id": "scene-x"}).json()}
            listed_y = {item["workspace_id"] for item in alice.get("/api/v1/workspaces", params={"base_scene_id": "scene-y"}).json()}
            assert listed_x == {ax["workspace_id"]} and listed_y == {ay["workspace_id"]}
            stored = {row[0]: row[1] for row in _rows(url, "SELECT workspace_id, owner_id FROM planning_workspaces")}
            assert stored[ax["workspace_id"]] == owner_a and stored[bx["workspace_id"]] == owner_b
            revisions = _rows(url, "SELECT workspace_id, revision_id FROM planning_workspace_revisions")
            assert {row[0] for row in revisions} >= {ax["workspace_id"], bx["workspace_id"], ay["workspace_id"], by["workspace_id"]}
        api.stop()
        api.start(bootstrap=False)
        with api.client() as alice, api.client() as bob:
            _login(alice, "user-a", PASSWORD)
            _login(bob, "user-b", PASSWORD)
            plan_a = alice.get(f"/api/v1/workspaces/{ax['workspace_id']}/plan").json()["site"]
            plan_b = bob.get(f"/api/v1/workspaces/{bx['workspace_id']}/plan").json()["site"]
            assert plan_a["rect_w_m"] == 21 and plan_a["road_setback_m"] == 1 and plan_a["field_policy"] == "blocked"
            assert plan_a["field_cost"] == 0.5 and plan_a["include_demand"] is False
            assert plan_b["rect_w_m"] == 28 and plan_b["exclusion_zones"] != plan_a["exclusion_zones"]
            ay_route = alice.get(f"/api/v1/workspaces/{ay['workspace_id']}/plan").json()["routing"]
            by_route = bob.get(f"/api/v1/workspaces/{by['workspace_id']}/plan").json()["routing"]
            assert ay_route["max_span_m"] == "44" and by_route["max_span_m"] == "50"
            assert ay_route["start"] != by_route["start"]
            assert alice.get(f"/api/v1/workspaces/{bx['workspace_id']}").status_code == 404
            owners = {row[0]: row[1] for row in _rows(url, "SELECT workspace_id, owner_id FROM planning_workspaces")}
            assert owners[ax["workspace_id"]] == owner_a and owners[by["workspace_id"]] == owner_b
    finally:
        api.stop()
    assert (lock.stat().st_mtime_ns if lock.exists() else None) == lock_before


def test_enqueue_failure_keeps_the_postgres_job_queued(tmp_path: Path) -> None:
    url = _database_url()
    _reset(url)
    write_scene(tmp_path / "scenes", "scene-x", 221000, "rev-x1")
    api = ApiProcess(tmp_path, url, REDIS_CLOSED)
    api.start(bootstrap=True)
    try:
        with api.client() as admin, api.client() as alice:
            _login(admin, "p2h2-admin", ADMIN_PASSWORD)
            assert admin.post("/api/v1/admin/users", json={"username": "user-a", "password": PASSWORD, "role": "user"}).status_code == 201
            _login(alice, "user-a", PASSWORD)
            workspace = alice.post("/api/v1/workspaces", json={"base_scene_id": "scene-x", "display_name": "AX"}).json()
            saved = alice.put(
                f"/api/v1/workspaces/{workspace['workspace_id']}/plan/site",
                json={"expected_workspace_revision": workspace["workspace_revision"], "site": site(20, 1, 0.4, "allowed")},
            )
            created = alice.post(
                f"/api/v1/workspaces/{workspace['workspace_id']}/jobs",
                json={
                    "plugin_id": "site.guided_search",
                    "expected_workspace_revision": saved.json()["workspace_revision"],
                    "experiment_name": "redis-down",
                    "overwrite_existing": False,
                    "run_options": {"device": "cpu", "popsize": 4, "generations": 1},
                },
            )
            assert created.status_code == 202, created.text
            body = created.json()
            assert body["status"] == "queued"
            stored = _rows(url, "SELECT status FROM jobs")
            assert stored == [("queued",)]
    finally:
        api.stop()
    assert "stayed queued because enqueue failed" in api.log.read_text(encoding="utf-8", errors="replace")
